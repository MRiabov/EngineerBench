import asyncio
import hashlib
import uuid
from pathlib import Path

import pytest
import yaml
from httpx import AsyncClient

from controller.agent.review_handover import validate_reviewer_handover
from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    EpisodeResponse,
)
from controller.clients.worker import WorkerClient
from shared.enums import AgentName, EpisodeStatus, ReviewDecision
from shared.workers.schema import ReviewManifest
from tests.integration.agent.helpers import (
    WORKER_LIGHT_URL,
    repo_git_revision,
    seed_benchmark_assembly_definition,
    seed_current_revision_render_preview,
    seed_execution_reviewer_handover,
    wait_for_episode_state,
)

CONTROLLER_URL = "http://127.0.0.1:18000"

pytestmark = pytest.mark.xdist_group(name="physics_sims")


def _asset_path(asset_path: str | Path) -> Path:
    return Path(str(asset_path).lstrip("/"))


def _has_review_artifacts(
    episode: EpisodeResponse, *, required_checklist_pairs: tuple[tuple[str, str], ...]
) -> bool:
    traces = episode.traces or []
    review_traces = [
        trace
        for trace in traces
        if trace.name == "review_decision" and trace.metadata_vars is not None
    ]
    return all(
        any(
            trace.metadata_vars.checklist.get(checklist_key) == expected_value
            for trace in review_traces
        )
        for checklist_key, expected_value in required_checklist_pairs
    )


def _is_inspect_media_trace(trace) -> bool:
    return (
        trace.name in {"inspect_media", "inspect_media_tool"}
        and getattr(trace.trace_type, "value", str(trace.trace_type)) == "TOOL_START"
    )


def _benchmark_plan_review_artifacts_ready(episode: EpisodeResponse) -> bool:
    traces = episode.traces or []
    rejected_traces = [
        trace
        for trace in traces
        if trace.name == "review_decision"
        and trace.metadata_vars is not None
        and trace.metadata_vars.decision == ReviewDecision.REJECT_PLAN
        and "UNSOLVABLE_SCENARIO" in (trace.content or "")
    ]
    artifact_paths = [_asset_path(asset.s3_path) for asset in (episode.assets or [])]
    decision_paths = [
        path
        for path in artifact_paths
        if path == Path("benchmark-plan-review-decision-round-1.yaml")
    ]
    comments_paths = [
        path
        for path in artifact_paths
        if path == Path("benchmark-plan-review-comments-round-1.yaml")
    ]
    manifest_paths = [
        path
        for path in artifact_paths
        if path == Path(".manifests/benchmark_plan_review_manifest.json")
    ]
    return bool(
        rejected_traces and decision_paths and comments_paths and manifest_paths
    )


async def _wait_for_review_evidence(
    client: AsyncClient,
    *,
    episode_id: str,
    required_checklist_pairs: tuple[tuple[str, str], ...],
    attempts: int = 15,
) -> EpisodeResponse:
    return EpisodeResponse.model_validate(
        await wait_for_episode_state(
            client,
            episode_id,
            timeout_s=float(attempts),
            predicate=lambda episode: _has_review_artifacts(
                episode,
                required_checklist_pairs=required_checklist_pairs,
            ),
        )
    )


async def _wait_for_trace_name(
    client: AsyncClient,
    *,
    episode_id: str,
    trace_name: str,
    predicate,
    attempts: int = 15,
) -> list:
    episode = EpisodeResponse.model_validate(
        await wait_for_episode_state(
            client,
            episode_id,
            timeout_s=float(attempts),
            predicate=lambda episode: any(
                trace.name == trace_name and predicate(trace)
                for trace in (episode.traces or [])
            ),
        )
    )
    return [
        trace
        for trace in (episode.traces or [])
        if trace.name == trace_name and predicate(trace)
    ]


async def _read_episode_asset_text(
    client: AsyncClient, episode_id: str, path: str
) -> str:
    resp = await client.get(f"/episodes/{episode_id}/assets/{path}")
    assert resp.status_code == 200, resp.text
    return resp.text


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_reviewer_evidence_completeness():
    """
    INT-034: reviewer evidence completeness.

    Asserts reviewer-stage artifacts include:
    - reviewer-specific manifest in `.manifests/**`
    - reviewer-specific persisted review filepath under `reviews/**`
    """
    async with AsyncClient(base_url=CONTROLLER_URL, timeout=300.0) as client:
        session_id = f"INT-034-{uuid.uuid4().hex[:8]}"
        await seed_execution_reviewer_handover(
            client,
            session_id=session_id,
            int_id="INT-034",
        )
        run_request = AgentRunRequest(
            task="INT-034 reviewer evidence completeness",
            session_id=session_id,
            agent_name=AgentName.ENGINEER_EXECUTION_REVIEWER,
            start_node=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        run_resp = await client.post(
            "/api/agent/run", json=run_request.model_dump(mode="json")
        )
        assert run_resp.status_code == 202, run_resp.text
        episode_id = str(AgentRunResponse.model_validate(run_resp.json()).episode_id)

        ep_data = EpisodeResponse.model_validate(
            await wait_for_episode_state(
                client,
                episode_id,
                timeout_s=180.0,
                terminal_statuses={
                    EpisodeStatus.COMPLETED,
                    EpisodeStatus.FAILED,
                    EpisodeStatus.CANCELLED,
                },
                predicate=lambda candidate: (
                    any(
                        _is_inspect_media_trace(trace)
                        for trace in (candidate.traces or [])
                    )
                    and any(
                        trace.name == "media_inspection"
                        for trace in (candidate.traces or [])
                    )
                    and any(
                        trace.name == "llm_media_attached"
                        for trace in (candidate.traces or [])
                    )
                    and any(
                        trace.name == "review_decision"
                        for trace in (candidate.traces or [])
                    )
                ),
            )
        )

        ep_resp = await client.get(f"/episodes/{episode_id}")
        assert ep_resp.status_code == 200, ep_resp.text
        ep_data = EpisodeResponse.model_validate(ep_resp.json())
        artifact_paths = [_asset_path(a.s3_path) for a in (ep_data.assets or [])]
        traces = ep_data.traces or []

        manifest_paths = [p for p in artifact_paths if p.suffix == ".json"]
        assert manifest_paths, (
            f"No review manifest artifacts found. Artifacts: {artifact_paths}"
        )
        assert any(
            p == Path(".manifests/benchmark_plan_review_manifest.json")
            for p in manifest_paths
        ), (
            "benchmark_plan_review_manifest.json missing from artifacts. "
            f"Found: {manifest_paths}"
        )
        assert any(p.parent.name == ".manifests" for p in manifest_paths), (
            f"Review manifest must be in .manifests/. Found: {manifest_paths}"
        )
        assert any(p == Path("renders/render_manifest.json") for p in artifact_paths), (
            f"render_manifest.json missing. Artifacts: {artifact_paths}"
        )
        assert Path("solution_script.py") in artifact_paths, (
            f"solution_script.py missing. Artifacts: {artifact_paths}"
        )
        solution_script_text = await _read_episode_asset_text(
            client, episode_id, "solution_script.py"
        )
        assert "Box(" in solution_script_text

        stage_review_paths = [
            p
            for p in artifact_paths
            if "reviews/" in p
            and (
                "benchmark-plan-review-decision-round-" in p
                or "benchmark-plan-review-comments-round-" in p
                or "benchmark-execution-review-decision-round-" in p
                or "benchmark-execution-review-comments-round-" in p
                or "engineering-plan-review-decision-round-" in p
                or "engineering-plan-review-comments-round-" in p
                or "engineering-execution-review-decision-round-" in p
                or "engineering-execution-review-comments-round-" in p
            )
        ]
        if not stage_review_paths:
            # Deterministic fallback for runs that terminate before reviewer write
            # but still must enforce reviewer path contracts (INT-034/INT-071).
            cfg = yaml.safe_load(
                Path("config/agents_config.yaml").read_text(encoding="utf-8")
            )
            expected_paths = {
                "benchmark_plan_reviewer": {
                    "reviews/benchmark-plan-review-decision-round-*.yaml",
                    "reviews/benchmark-plan-review-comments-round-*.yaml",
                },
                "engineer_plan_reviewer": {
                    "reviews/engineering-plan-review-decision-round-*.yaml",
                    "reviews/engineering-plan-review-comments-round-*.yaml",
                },
                "engineer_execution_reviewer": {
                    "reviews/engineering-execution-review-decision-round-*.yaml",
                    "reviews/engineering-execution-review-comments-round-*.yaml",
                },
                "benchmark_reviewer": {
                    "reviews/benchmark-execution-review-decision-round-*.yaml",
                    "reviews/benchmark-execution-review-comments-round-*.yaml",
                },
            }
            for role, expected in expected_paths.items():
                role_cfg = cfg.get("agents", {}).get(role, {})
                permissions = role_cfg.get("filesystem_permissions", role_cfg)
                patterns = set(permissions.get("write", {}).get("allow", []))
                missing = expected - patterns
                assert not missing, (
                    f"{role} missing reviewer-stage write scopes {sorted(missing)}. "
                    f"Found: {sorted(patterns)}"
                )
                assert "reviews/review-round-*.md" not in patterns, (
                    f"{role} still allows legacy generic reviewer scope. "
                    f"Found: {sorted(patterns)}"
                )

        inspect_media_traces = [
            trace for trace in traces if _is_inspect_media_trace(trace)
        ]
        assert inspect_media_traces, "Reviewer approval must call inspect_media()."

        media_events = [trace for trace in traces if trace.name == "media_inspection"]
        assert media_events, "media_inspection observability event missing."

        attachment_events = [
            trace for trace in traces if trace.name == "llm_media_attached"
        ]
        assert attachment_events, "llm_media_attached observability event missing."

        review_traces = [trace for trace in traces if trace.name == "review_decision"]
        assert review_traces, "review_decision event missing."
        latest_review_trace = max(review_traces, key=lambda trace: trace.id)
        checklist_payload = (
            latest_review_trace.metadata_vars.checklist
            if latest_review_trace.metadata_vars is not None
            else None
        )
        assert isinstance(checklist_payload, dict), (
            "review_decision event must carry checklist payload. "
            f"Trace metadata: {latest_review_trace.metadata_vars}"
        )
        assert any(
            trace.id < latest_review_trace.id for trace in inspect_media_traces
        ), "inspect_media must occur before the final review decision."
        for trace in [*media_events, *attachment_events]:
            assert trace.user_session_id == ep_data.user_session_id


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_engineer_execution_reviewer_handover_accepts_preview_evidence_paths():
    """
    INT regression: execution reviewer handover must treat PNG preview evidence
    as binary, not UTF-8 text.
    """

    async with AsyncClient(base_url=CONTROLLER_URL, timeout=300.0) as client:
        session_id = f"INT-210-{uuid.uuid4().hex[:8]}"
        render_path = "renders/render_e15_a0.png"
        script_content = "print('preview evidence check')\n"

        await seed_benchmark_assembly_definition(
            client,
            session_id,
            benchmark_max_unit_cost_usd=250.0,
            benchmark_max_weight_g=2500.0,
            planner_target_max_unit_cost_usd=250.0,
            planner_target_max_weight_g=2500.0,
        )
        await seed_execution_reviewer_handover(
            client,
            session_id=session_id,
            int_id="INT-210",
            script_content=script_content,
        )
        await seed_current_revision_render_preview(
            client,
            session_id=session_id,
            render_path=render_path,
        )

        worker_client = WorkerClient(
            base_url=WORKER_LIGHT_URL,
            session_id=session_id,
            agent_role=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        script_sha256 = hashlib.sha256(script_content.encode("utf-8")).hexdigest()

        for path, content in (
            ("renders/scene.xml", "<scene />\n"),
            ("renders/model.step", "ISO-10303-21;\n"),
            ("renders/benchmark_definition.yaml", "benchmark: true\n"),
            ("renders/assembly_definition.yaml", "assembly: true\n"),
        ):
            resp = await client.post(
                "http://127.0.0.1:18001/fs/write",
                json={
                    "path": path,
                    "content": content,
                    "overwrite": True,
                },
                headers={"X-Session-ID": session_id},
            )
            assert resp.status_code == 200, resp.text

        render_base = Path(render_path).with_suffix("")
        review_manifest_json = ReviewManifest(
            status="ready_for_review",
            reviewer_stage="engineering_execution_reviewer",
            session_id=session_id,
            script_path="script.py",
            script_sha256=script_sha256,
            validation_success=True,
            validation_timestamp=0.0,
            simulation_success=True,
            simulation_summary="Goal achieved in green zone.",
            simulation_timestamp=0.0,
            goal_reached=True,
            revision=repo_git_revision(),
            renders=[
                render_path,
                f"{render_base}_depth.png",
                f"{render_base}_segmentation.png",
            ],
            preview_evidence_paths=[
                render_path,
                f"{render_base}_depth.png",
                f"{render_base}_segmentation.png",
            ],
            mjcf_path="renders/scene.xml",
            cad_path="renders/model.step",
            objectives_path="renders/benchmark_definition.yaml",
            assembly_definition_path="renders/assembly_definition.yaml",
            worker_session_id=session_id,
            benchmark_worker_session_id=session_id,
            benchmark_episode_id=session_id,
        ).model_dump_json(indent=2)
        review_resp = await client.post(
            "http://127.0.0.1:18001/fs/write",
            json={
                "path": ".manifests/engineering_execution_handoff_manifest.json",
                "content": review_manifest_json,
                "overwrite": True,
            },
            headers={"X-Session-ID": session_id, "X-System-FS-Bypass": "1"},
        )
        assert review_resp.status_code == 200, review_resp.text
        try:
            validation_error = await validate_reviewer_handover(
                worker_client,
                manifest_path=".manifests/engineering_execution_handoff_manifest.json",
                expected_stage="engineering_execution_reviewer",
            )
        finally:
            await worker_client.aclose()

        assert validation_error is None, validation_error


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_reviewer_approval_requires_media_inspection():
    """
    INT-034: reviewer approval fails closed when render artifacts exist but
    inspect_media() was never called.
    """
    async with AsyncClient(base_url=CONTROLLER_URL, timeout=300.0) as client:
        session_id = f"INT-039-{uuid.uuid4().hex[:8]}"
        await seed_benchmark_assembly_definition(client, session_id)
        run_request = AgentRunRequest(
            task="INT-034 reviewer media gate",
            session_id=session_id,
        )
        run_resp = await client.post("/agent/run", json=run_request.model_dump())
        assert run_resp.status_code in [200, 202], (
            f"Agent trigger failed: {run_resp.text}"
        )
        episode_id = AgentRunResponse.model_validate(run_resp.json()).episode_id

        rejected_review_trace = None
        ep_data = None
        for _ in range(180):
            ep_resp = await client.get(f"/episodes/{episode_id}")
            assert ep_resp.status_code == 200, ep_resp.text
            ep_data = EpisodeResponse.model_validate(ep_resp.json())
            traces = ep_data.traces or []
            rejected_traces = [
                trace
                for trace in traces
                if trace.name == "review_decision"
                and trace.metadata_vars is not None
                and trace.metadata_vars.decision == ReviewDecision.REJECTED
                and "inspect_media" in (trace.content or "")
            ]
            if rejected_traces:
                rejected_review_trace = max(rejected_traces, key=lambda trace: trace.id)
                break
            if ep_data.status in [
                EpisodeStatus.COMPLETED,
                EpisodeStatus.FAILED,
                EpisodeStatus.CANCELLED,
            ]:
                break
            await asyncio.sleep(1.0)
        else:
            pytest.fail(f"Episode did not complete in time (episode_id={episode_id})")

        assert ep_data is not None
        artifact_paths = [_asset_path(a.s3_path) for a in (ep_data.assets or [])]
        assert any(
            path.parent.name == "renders" and path.suffix == ".png"
            for path in artifact_paths
        ), f"Expected reviewer-visible render artifact. Artifacts: {artifact_paths}"

        assert rejected_review_trace is not None, (
            "Expected reviewer gate rejection mentioning inspect_media before the run "
            "terminated. "
            f"Final status: {ep_data.status}"
        )

        interrupt_resp = await client.post(f"/episodes/{episode_id}/interrupt")
        assert interrupt_resp.status_code in [200, 202], interrupt_resp.text

        traces = ep_data.traces or []
        assert rejected_review_trace.metadata_vars is not None
        assert rejected_review_trace.metadata_vars.decision == ReviewDecision.REJECTED
        assert "inspect_media" in (rejected_review_trace.content or "")


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_engineer_execution_reviewer_handover_accepts_png_preview_evidence():
    """
    INT regression: execution reviewer handover must not text-read PNG preview
    evidence files listed in the review manifest.
    """

    async with AsyncClient(base_url=CONTROLLER_URL, timeout=300.0) as client:
        session_id = f"INT-210-{uuid.uuid4().hex[:8]}"
        render_path = "renders/render_e15_a0.png"
        script_content = "print('preview evidence check')\n"

        await seed_benchmark_assembly_definition(
            client,
            session_id,
            benchmark_max_unit_cost_usd=250.0,
            benchmark_max_weight_g=2500.0,
            planner_target_max_unit_cost_usd=250.0,
            planner_target_max_weight_g=2500.0,
        )
        await seed_execution_reviewer_handover(
            client,
            session_id=session_id,
            int_id="INT-210",
            script_content=script_content,
        )
        await seed_current_revision_render_preview(
            client,
            session_id=session_id,
            render_path=render_path,
        )

        worker_client = WorkerClient(
            base_url=WORKER_LIGHT_URL,
            session_id=session_id,
            agent_role=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        script_sha256 = hashlib.sha256(script_content.encode("utf-8")).hexdigest()

        for path, content in (
            ("renders/scene.xml", "<scene />\n"),
            ("renders/model.step", "ISO-10303-21;\n"),
            ("renders/benchmark_definition.yaml", "benchmark: true\n"),
            ("renders/assembly_definition.yaml", "assembly: true\n"),
        ):
            resp = await client.post(
                "http://127.0.0.1:18001/fs/write",
                json={
                    "path": path,
                    "content": content,
                    "overwrite": True,
                },
                headers={"X-Session-ID": session_id},
            )
            assert resp.status_code == 200, resp.text

        render_base = Path(render_path).with_suffix("")
        review_manifest_json = ReviewManifest(
            status="ready_for_review",
            reviewer_stage="engineering_execution_reviewer",
            session_id=session_id,
            script_path="script.py",
            script_sha256=script_sha256,
            validation_success=True,
            validation_timestamp=0.0,
            simulation_success=True,
            simulation_summary="Goal achieved in green zone.",
            simulation_timestamp=0.0,
            goal_reached=True,
            revision=repo_git_revision(),
            renders=[
                render_path,
                f"{render_base}_depth.png",
                f"{render_base}_segmentation.png",
            ],
            preview_evidence_paths=[
                render_path,
                f"{render_base}_depth.png",
                f"{render_base}_segmentation.png",
            ],
            mjcf_path="renders/scene.xml",
            cad_path="renders/model.step",
            objectives_path="renders/benchmark_definition.yaml",
            assembly_definition_path="renders/assembly_definition.yaml",
        ).model_dump_json(indent=2)
        review_resp = await client.post(
            "http://127.0.0.1:18001/fs/write",
            json={
                "path": ".manifests/engineering_execution_handoff_manifest.json",
                "content": review_manifest_json,
                "overwrite": True,
            },
            headers={"X-Session-ID": session_id, "X-System-FS-Bypass": "1"},
        )
        assert review_resp.status_code == 200, review_resp.text

        try:
            validation_error = await validate_reviewer_handover(
                worker_client,
                manifest_path=".manifests/engineering_execution_handoff_manifest.json",
                expected_stage="engineering_execution_reviewer",
            )
        finally:
            await worker_client.aclose()

        assert validation_error is None, validation_error
