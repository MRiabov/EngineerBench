import hashlib
from pathlib import Path

import pytest
import yaml
from httpx import AsyncClient

from controller.api.schemas import (
    BenchmarkGenerateRequest,
    BenchmarkGenerateResponse,
    ConfirmRequest,
    EpisodeResponse,
)
from shared.enums import EpisodeStatus
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.schema import (
    RenderManifest,
    ReviewManifest,
    ValidationResultRecord,
)
from tests.integration.agent.helpers import repo_git_revision, wait_for_benchmark_state

# Adjust URL to your controller if different
CONTROLLER_URL = "http://127.0.0.1:18000"

pytestmark = pytest.mark.xdist_group(name="physics_sims")


def _asset_path(asset_path: str | Path) -> Path:
    return Path(str(asset_path).lstrip("/"))


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_benchmark_to_engineer_handoff():
    """
    INT-032: Benchmark-to-engineer handoff package

    Verifies that the engineer receives the expected artifact bundle for a
    generated benchmark.
    """
    async with AsyncClient(base_url=CONTROLLER_URL, timeout=300.0) as client:
        # 1. Trigger Benchmark Generation
        request = BenchmarkGenerateRequest(
            prompt="Create a benchmark with a moving platform.",
            backend=SimulatorBackendType.GENESIS,
        )
        resp = await client.post("/benchmark/generate", json=request.model_dump())
        assert resp.status_code in [
            200,
            202,
        ], f"Failed to trigger benchmark: {resp.text}"
        benchmark_resp = BenchmarkGenerateResponse.model_validate(resp.json())
        session_id = str(benchmark_resp.session_id)

        last_episode = EpisodeResponse.model_validate(
            await wait_for_benchmark_state(
                client,
                session_id,
                timeout_s=150.0,
                terminal_statuses={
                    EpisodeStatus.PLANNED,
                    EpisodeStatus.COMPLETED,
                    EpisodeStatus.FAILED,
                    EpisodeStatus.CANCELLED,
                },
            )
        )
        if last_episode.status == EpisodeStatus.PLANNED:
            await client.post(
                f"/benchmark/{session_id}/confirm",
                json=ConfirmRequest(comment="Handoff confirm").model_dump(),
            )
            last_episode = EpisodeResponse.model_validate(
                await wait_for_benchmark_state(
                    client,
                    session_id,
                    timeout_s=150.0,
                    terminal_statuses={
                        EpisodeStatus.COMPLETED,
                        EpisodeStatus.FAILED,
                        EpisodeStatus.CANCELLED,
                    },
                )
            )

        if last_episode.status == EpisodeStatus.FAILED:
            pytest.fail(f"Benchmark generation failed: {last_episode.status}")

        # 3. Verify Handoff Package Artifacts from episode assets
        episode_resp = await client.get(f"/api/episodes/{session_id}")
        assert episode_resp.status_code == 200, (
            f"Failed to fetch episode assets: {episode_resp.text}"
        )
        episode_data = EpisodeResponse.model_validate(episode_resp.json())
        artifact_paths = [_asset_path(a.s3_path) for a in (episode_data.assets or [])]

        # Check existence of required files
        assert Path("benchmark_definition.yaml") in artifact_paths, (
            f"benchmark_definition.yaml missing. Artifacts: {artifact_paths}"
        )

        # Check for renders (expecting a directory or multiple files)
        # Renders usually in renders/ folder.
        render_files = [
            p
            for p in artifact_paths
            if p.parent.name == "renders"
            and p.suffix.lower() in {".png", ".jpg", ".jpeg"}
        ]
        assert len(render_files) > 0, f"No renders found. Artifacts: {artifact_paths}"
        render_manifest_paths = [
            p for p in artifact_paths if p == Path("renders/render_manifest.json")
        ]
        assert render_manifest_paths, (
            f"renders/render_manifest.json missing. Artifacts: {artifact_paths}"
        )
        assert Path("validation_results.json") in artifact_paths, (
            f"validation_results.json missing. Artifacts: {artifact_paths}"
        )
        assert Path("simulation_result.json") in artifact_paths, (
            f"simulation_result.json missing. Artifacts: {artifact_paths}"
        )
        manifest_paths = [
            p
            for p in artifact_paths
            if p == Path(".manifests/benchmark_plan_review_manifest.json")
        ]
        assert manifest_paths, (
            f"benchmark_plan_review_manifest.json missing. Artifacts: {artifact_paths}"
        )
        manifest_paths = [
            p
            for p in artifact_paths
            if p == Path(".manifests/benchmark_review_manifest.json")
        ]
        assert manifest_paths, (
            f"benchmark_review_manifest.json missing. Artifacts: {artifact_paths}"
        )
        assert any(p.parent.name == ".manifests" for p in manifest_paths), (
            f"review manifest must be in .manifests/. Found: {manifest_paths}"
        )
        manifest_resp = await client.get(
            f"/api/episodes/{session_id}/assets/{manifest_paths[0]}"
        )
        assert manifest_resp.status_code == 200, manifest_resp.text
        manifest = ReviewManifest.model_validate_json(manifest_resp.text)
        assert manifest.status == "ready_for_review"
        assert manifest.session_id == session_id
        assert manifest.episode_id == str(benchmark_resp.episode_id)
        assert manifest.worker_session_id == session_id
        assert manifest.revision == repo_git_revision()
        assert manifest.benchmark_episode_id == str(benchmark_resp.episode_id)
        assert manifest.benchmark_worker_session_id == session_id
        assert manifest.benchmark_revision == repo_git_revision()
        assert manifest.solution_revision == repo_git_revision()
        assert manifest.validation_success is True
        assert manifest.simulation_success is True
        assert manifest.motion_evidence_verified is True
        assert manifest.goal_reached is None
        assert '"goal_reached"' not in manifest_resp.text
        assert "goal achieved" not in manifest.simulation_summary.lower()
        benchmark_assembly_definition_path = next(
            p for p in artifact_paths if p == Path("benchmark_assembly_definition.yaml")
        )
        benchmark_assembly_definition_resp = await client.get(
            f"/api/episodes/{session_id}/assets/{benchmark_assembly_definition_path}"
        )
        assert benchmark_assembly_definition_resp.status_code == 200, (
            benchmark_assembly_definition_resp.text
        )
        benchmark_assembly_definition = yaml.safe_load(
            benchmark_assembly_definition_resp.text
        )
        assert manifest.environment_version == benchmark_assembly_definition["version"]
        assert manifest.preview_evidence_paths
        assert {_asset_path(path) for path in manifest.preview_evidence_paths} == {
            _asset_path(path) for path in manifest.renders
        }

        plan_review_decision_paths = [
            p
            for p in artifact_paths
            if p == Path("benchmark-plan-review-decision-round-1.yaml")
        ]
        plan_review_comments_paths = [
            p
            for p in artifact_paths
            if p == Path("benchmark-plan-review-comments-round-1.yaml")
        ]
        assert plan_review_decision_paths, (
            f"benchmark-plan-review-decision-round-1.yaml missing. "
            f"Artifacts: {artifact_paths}"
        )
        assert plan_review_comments_paths, (
            f"benchmark-plan-review-comments-round-1.yaml missing. "
            f"Artifacts: {artifact_paths}"
        )

        plan_review_comments_resp = await client.get(
            f"/api/episodes/{session_id}/assets/{plan_review_comments_paths[0]}"
        )
        assert plan_review_comments_resp.status_code == 200, (
            plan_review_comments_resp.text
        )
        plan_review_comments = yaml.safe_load(plan_review_comments_resp.text)
        assert plan_review_comments["summary"].startswith("APPROVED:"), (
            plan_review_comments
        )
        assert plan_review_comments["checklist"]["latest_revision_verified"] is True
        assert plan_review_comments["checklist"]["render_count"] == 2
        assert plan_review_comments["checklist"]["visual_inspection_satisfied"] is True
        assert "review_manifest_revision" in plan_review_comments["checklist"]

        script_resp = await client.get(
            f"/api/episodes/{session_id}/assets/{manifest.script_path}"
        )
        assert script_resp.status_code == 200, script_resp.text
        assert (
            hashlib.sha256(script_resp.text.encode("utf-8")).hexdigest()
            == manifest.script_sha256
        )

        validation_manifest_resp = await client.get(
            f"/api/episodes/{session_id}/assets/validation_results.json"
        )
        assert validation_manifest_resp.status_code == 200, (
            validation_manifest_resp.text
        )
        validation_record = ValidationResultRecord.model_validate_json(
            validation_manifest_resp.text
        )
        assert validation_record.success is True
        assert validation_record.script_sha256 == manifest.script_sha256

        render_manifest_resp = await client.get(
            f"/api/episodes/{session_id}/assets/{render_manifest_paths[0]}"
        )
        assert render_manifest_resp.status_code == 200, render_manifest_resp.text
        render_manifest = RenderManifest.model_validate_json(render_manifest_resp.text)
        assert render_manifest.artifacts, "render_manifest.json must not be empty."
        assert render_manifest.episode_id == str(benchmark_resp.episode_id)
        assert render_manifest.worker_session_id == session_id
        assert render_manifest.revision == repo_git_revision()
        assert (
            render_manifest.environment_version
            == benchmark_assembly_definition["version"]
        )
        assert render_manifest.preview_evidence_paths
        assert set(manifest.renders).issubset(set(render_manifest.artifacts.keys())), (
            render_manifest.artifacts
        )
        assert set(render_manifest.preview_evidence_paths) == set(manifest.renders)
