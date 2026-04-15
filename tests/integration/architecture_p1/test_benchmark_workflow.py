import hashlib
import uuid
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
from shared.enums import (
    EpisodePhase,
    EpisodeStatus,
    TerminalReason,
)
from shared.models.schemas import AssemblyDefinition, BenchmarkDefinition
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.schema import (
    ReviewManifest,
)
from tests.integration.agent.helpers import (
    repo_git_revision,
    wait_for_benchmark_state,
)

# Adjust URL to your controller if different
CONTROLLER_URL = "http://127.0.0.1:18000"

pytestmark = pytest.mark.xdist_group(name="physics_sims")


def _asset_path(asset_path: str | Path) -> Path:
    return Path(str(asset_path).lstrip("/"))


async def _wait_for_planned_or_failed_episode(
    client: AsyncClient, episode_id: str
) -> EpisodeResponse:
    return EpisodeResponse.model_validate(
        await wait_for_benchmark_state(
            client,
            episode_id,
            timeout_s=120.0,
            terminal_statuses={EpisodeStatus.PLANNED, EpisodeStatus.FAILED},
        )
    )


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_benchmark_planner_cad_reviewer_path():
    """
    INT-031: Benchmark planner -> CAD -> reviewer path

    Verifies:
    1. Benchmark generation trigger
    2. Successful completion of the workflow
    3. Existence of required artifacts (benchmark_plan.md, benchmark_definition.yaml, Reviews)
    """
    async with AsyncClient(base_url=CONTROLLER_URL, timeout=300.0) as client:
        # 1. Trigger Benchmark Generation
        request = BenchmarkGenerateRequest(
            prompt="INT-005: Create a simple path planning benchmark with a wall and a goal.",
            backend=SimulatorBackendType.GENESIS,
        )
        resp = await client.post("/benchmark/generate", json=request.model_dump())
        assert resp.status_code in [
            200,
            202,
        ], f"Failed to trigger benchmark: {resp.text}"
        benchmark_resp = BenchmarkGenerateResponse.model_validate(resp.json())
        session_id = str(benchmark_resp.session_id)

        initial_episode = EpisodeResponse.model_validate(
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
        if initial_episode.status == EpisodeStatus.PLANNED:
            # WP08: Call confirm to continue from planning to execution
            confirm_resp = await client.post(
                f"/benchmark/{session_id}/confirm",
                json=ConfirmRequest(comment="Looks good").model_dump(),
            )
            assert confirm_resp.status_code in [200, 202]
            final_episode = EpisodeResponse.model_validate(
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
        else:
            final_episode = initial_episode

        if final_episode.status == EpisodeStatus.FAILED:
            pytest.fail(
                f"Benchmark generation failed with status: {final_episode.status}"
            )

        final_metadata = final_episode.metadata_vars
        assert final_metadata is not None, "Episode metadata is missing."
        assert final_metadata.terminal_reason == TerminalReason.APPROVED
        assert final_metadata.failure_class is None
        assert final_metadata.episode_phase == EpisodePhase.BENCHMARK_REVIEWING

        # 3. Verify Artifacts from episode assets
        episode_resp = await client.get(f"/api/episodes/{session_id}")
        assert episode_resp.status_code == 200, (
            f"Failed to fetch episode assets: {episode_resp.text}"
        )
        episode_data = EpisodeResponse.model_validate(episode_resp.json())
        artifact_paths = [_asset_path(a.s3_path) for a in (episode_data.assets or [])]
        traces = episode_data.traces or []
        submit_plan_traces = [
            t
            for t in traces
            if t.trace_type.value == "TOOL_START" and t.name == "submit_benchmark_plan"
        ]
        inspect_media_traces = [
            t
            for t in traces
            if t.trace_type.value == "TOOL_START" and t.name == "inspect_media"
        ]

        assert Path("benchmark_plan.md") in artifact_paths, (
            f"benchmark_plan.md missing. Artifacts: {artifact_paths}"
        )
        assert Path("benchmark_definition.yaml") in artifact_paths, (
            f"benchmark_definition.yaml missing. Artifacts: {artifact_paths}"
        )
        assert Path("benchmark_plan_evidence_script.py") in artifact_paths, (
            f"benchmark_plan_evidence_script.py missing. Artifacts: {artifact_paths}"
        )
        assert Path("benchmark_script.py") in artifact_paths, (
            f"benchmark_script.py missing. Artifacts: {artifact_paths}"
        )
        assert Path(".manifests/current_role.json") in artifact_paths, (
            f"current_role.json missing. Artifacts: {artifact_paths}"
        )
        benchmark_definition_paths = [
            p for p in artifact_paths if p == Path("benchmark_definition.yaml")
        ]
        benchmark_definition_resp = await client.get(
            f"/api/episodes/{session_id}/assets/{benchmark_definition_paths[0]}"
        )
        assert benchmark_definition_resp.status_code == 200, (
            benchmark_definition_resp.text
        )
        benchmark_definition = BenchmarkDefinition.model_validate(
            yaml.safe_load(benchmark_definition_resp.text)
        )
        assert benchmark_definition.benchmark_parts, (
            "benchmark_definition.yaml must persist at least one benchmark_parts entry."
        )
        assert len(
            {part.part_id for part in benchmark_definition.benchmark_parts}
        ) == len(benchmark_definition.benchmark_parts), (
            "benchmark_definition.yaml must preserve unique benchmark_parts.part_id "
            "values."
        )
        assert len(
            {part.label for part in benchmark_definition.benchmark_parts}
        ) == len(benchmark_definition.benchmark_parts), (
            "benchmark_definition.yaml must preserve unique benchmark_parts.label "
            "values."
        )
        assert benchmark_definition.payload.material_id
        assert benchmark_definition.randomization.runtime_jitter_enabled is True
        assert "randomization:" in benchmark_definition_resp.text
        assert "runtime_jitter:" in benchmark_definition_resp.text
        plan_paths = [p for p in artifact_paths if p == Path("benchmark_plan.md")]
        plan_resp = await client.get(
            f"/api/episodes/{session_id}/assets/{plan_paths[0]}"
        )
        assert plan_resp.status_code == 200, plan_resp.text
        assert Path("benchmark_assembly_definition.yaml") in artifact_paths, (
            f"benchmark_assembly_definition.yaml missing. Artifacts: {artifact_paths}"
        )
        assembly_paths = [
            p for p in artifact_paths if p == Path("benchmark_assembly_definition.yaml")
        ]
        assembly_resp = await client.get(
            f"/api/episodes/{session_id}/assets/{assembly_paths[0]}"
        )
        assert assembly_resp.status_code == 200, assembly_resp.text
        benchmark_assembly_definition = AssemblyDefinition.model_validate(
            yaml.safe_load(assembly_resp.text)
        )
        assert benchmark_assembly_definition.manufactured_parts == []
        assert benchmark_assembly_definition.final_assembly == []
        assert submit_plan_traces, (
            "Expected planner to call submit_benchmark_plan before workflow completion."
        )
        assert inspect_media_traces, (
            "Expected benchmark reviewer to inspect a render before approval."
        )
        assert any(t.name == "media_inspection" for t in traces), (
            "media_inspection event missing from benchmark reviewer run."
        )
        assert any(t.name == "llm_media_attached" for t in traces), (
            "llm_media_attached event missing from benchmark reviewer run."
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
        assert Path("benchmark-plan-review-decision-round-1.yaml") in artifact_paths, (
            "benchmark plan review decision file missing from artifacts. "
            f"Artifacts: {artifact_paths}"
        )
        assert Path("benchmark-plan-review-comments-round-1.yaml") in artifact_paths, (
            "benchmark plan review comments file missing from artifacts. "
            f"Artifacts: {artifact_paths}"
        )
        manifest_paths = [
            p
            for p in artifact_paths
            if p == Path(".manifests/benchmark_review_manifest.json")
        ]
        assert manifest_paths, (
            f"benchmark_review_manifest.json missing. Artifacts: {artifact_paths}"
        )
        assert not any(
            p == Path(".manifests/engineering_execution_handoff_manifest.json")
            for p in artifact_paths
        ), (
            "Benchmark workflow must not emit "
            "'engineering_execution_handoff_manifest.json'. "
            f"Artifacts: {artifact_paths}"
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
        assert manifest.preview_evidence_paths
        assert set(manifest.preview_evidence_paths) == set(manifest.renders)

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

        script_resp = await client.get(
            f"/api/episodes/{session_id}/assets/{manifest.script_path}"
        )
        assert script_resp.status_code == 200, script_resp.text
        assert (
            hashlib.sha256(script_resp.text.encode("utf-8")).hexdigest()
            == manifest.script_sha256
        )


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_benchmark_request_validation_rejects_invalid_objectives():
    """The benchmark API must reject invalid deterministic objective values."""
    async with AsyncClient(base_url=CONTROLLER_URL, timeout=300.0) as client:
        invalid_generate = await client.post(
            "/benchmark/generate",
            json={
                "prompt": "Create a benchmark",
                "max_cost": -1,
            },
        )
        assert invalid_generate.status_code == 422

        invalid_update = await client.post(
            f"/benchmark/{uuid.uuid4()}/objectives",
            json={
                "max_cost": 0,
                "max_weight": -5,
                "target_quantity": 0,
            },
        )
        assert invalid_update.status_code == 422
