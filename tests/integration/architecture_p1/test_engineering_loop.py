import hashlib
import uuid
from pathlib import Path

import pytest
import yaml
from httpx import AsyncClient

from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    EpisodeCreateResponse,
    EpisodeResponse,
)
from shared.current_role import current_role_manifest_json
from shared.enums import (
    AgentName,
    EpisodeStatus,
    EpisodeType,
    ReviewDecision,
    TerminalReason,
    TraceType,
)
from shared.models.schemas import BenchmarkDefinition
from shared.models.simulation import SimulationResult
from shared.simulation.scene_builder import PreviewScene, moved_object_scene_name
from shared.workers.schema import (
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    PlanReviewManifest,
    RenderManifest,
    ReviewManifest,
    ValidationResultRecord,
)
from tests.integration.agent.helpers import (
    repo_git_revision,
    seed_approved_benchmark_bundle,
    wait_for_episode_state,
    wait_for_episode_terminal,
)

# Adjust URL to your controller if different
CONTROLLER_URL = "http://127.0.0.1:18000"
WORKER_HEAVY_URL = "http://127.0.0.1:18002"

pytestmark = pytest.mark.xdist_group(name="physics_sims")


def _asset_path(asset_path: str | Path) -> Path:
    return Path(str(asset_path).lstrip("/"))


async def _read_episode_asset_text(
    client: AsyncClient, episode_id: str, asset_path: str | Path
) -> str:
    resp = await client.get(f"/api/episodes/{episode_id}/assets/{asset_path}")
    assert resp.status_code == 200, resp.text
    return resp.text


async def _write_workspace_file(
    client: AsyncClient, session_id: str, path: str, content: str
) -> None:
    resp = await client.post(
        "http://127.0.0.1:18001/fs/write",
        json={
            "path": path,
            "content": content,
            "overwrite": True,
            "bypass_agent_permissions": True,
        },
        headers={"X-Session-ID": session_id},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration_p1
@pytest.mark.int_id("INT-033")
@pytest.mark.asyncio
async def test_engineering_full_loop():
    """
    INT-033: Engineering full loop.

    Verifies the live engineer path from benchmark bootstrap through planner,
    coder, validation, simulation, handoff, and final execution review.
    """
    async with AsyncClient(base_url=CONTROLLER_URL, timeout=300.0) as client:
        benchmark_session_id = f"INT-033-benchmark-{uuid.uuid4().hex[:8]}"
        benchmark_request = AgentRunRequest(
            task="INT-033 approved benchmark fixture for engineering full loop.",
            session_id=benchmark_session_id,
        )
        benchmark_resp = await client.post(
            "/api/test/episodes", json=benchmark_request.model_dump(mode="json")
        )
        assert benchmark_resp.status_code == 201, benchmark_resp.text
        benchmark_episode_id = str(
            EpisodeCreateResponse.model_validate(benchmark_resp.json()).episode_id
        )
        await seed_approved_benchmark_bundle(
            client,
            benchmark_session_id=benchmark_session_id,
            benchmark_episode_id=benchmark_episode_id,
        )
        benchmark_episode_resp = await client.get(
            f"/api/episodes/{benchmark_episode_id}"
        )
        assert benchmark_episode_resp.status_code == 200, benchmark_episode_resp.text
        benchmark_episode = EpisodeResponse.model_validate(
            benchmark_episode_resp.json()
        )
        assert benchmark_episode.status == EpisodeStatus.COMPLETED, (
            f"Benchmark bootstrap failed. Last status: {benchmark_episode.status}"
        )
        assert benchmark_episode.metadata_vars is not None
        assert benchmark_episode.metadata_vars.episode_type == EpisodeType.BENCHMARK
        assert (
            benchmark_episode.metadata_vars.detailed_status
            == EpisodeStatus.COMPLETED.value
        )
        assert (
            benchmark_episode.metadata_vars.terminal_reason == TerminalReason.APPROVED
        )
        assert benchmark_episode.metadata_vars.worker_session_id == benchmark_session_id
        benchmark_review_manifest = ReviewManifest.model_validate_json(
            await _read_episode_asset_text(
                client,
                benchmark_episode_id,
                ".manifests/benchmark_review_manifest.json",
            )
        )
        assert benchmark_review_manifest.status == "ready_for_review"
        assert benchmark_review_manifest.reviewer_stage == "benchmark_reviewer"
        assert benchmark_review_manifest.episode_id == benchmark_episode_id
        assert benchmark_review_manifest.worker_session_id == benchmark_session_id
        assert benchmark_review_manifest.benchmark_episode_id == benchmark_episode_id
        assert (
            benchmark_review_manifest.benchmark_worker_session_id
            == benchmark_session_id
        )
        assert benchmark_review_manifest.revision == repo_git_revision()

        engineer_session_id = f"INT-033-{uuid.uuid4().hex[:8]}"
        user_session_id = uuid.uuid4()

        async def _launch_engineer_run(
            *,
            task_suffix: str,
            agent_name: AgentName,
            start_node: AgentName | None = None,
        ) -> str:
            engineer_request = AgentRunRequest(
                task=(f"INT-033 {task_suffix} for benchmark {benchmark_episode_id}."),
                session_id=engineer_session_id,
                user_session_id=user_session_id,
                agent_name=agent_name,
                start_node=start_node,
                metadata_vars={"benchmark_id": benchmark_episode_id},
            )
            engineer_resp = await client.post(
                "/api/agent/run", json=engineer_request.model_dump(mode="json")
            )
            assert engineer_resp.status_code == 202, engineer_resp.text
            return str(AgentRunResponse.model_validate(engineer_resp.json()).episode_id)

        planner_episode_id = await _launch_engineer_run(
            task_suffix="engineer planner stage",
            agent_name=AgentName.ENGINEER_PLANNER,
            start_node=AgentName.ENGINEER_PLANNER,
        )
        planner_episode = EpisodeResponse.model_validate(
            await wait_for_episode_state(
                client,
                planner_episode_id,
                timeout_s=240.0,
                terminal_statuses={
                    EpisodeStatus.PLANNED,
                    EpisodeStatus.FAILED,
                    EpisodeStatus.CANCELLED,
                },
            )
        )
        assert planner_episode.status == EpisodeStatus.PLANNED, (
            f"Planner stage failed. Last status: {planner_episode.status}"
        )
        assert planner_episode.user_session_id == user_session_id
        assert planner_episode.metadata_vars is not None
        assert planner_episode.metadata_vars.episode_type == EpisodeType.ENGINEER
        assert planner_episode.metadata_vars.benchmark_id == benchmark_episode_id

        planner_artifact_paths = [
            _asset_path(asset.s3_path) for asset in (planner_episode.assets or [])
        ]
        planner_required_artifacts = (
            "engineering_plan.md",
            "todo.md",
            "assembly_definition.yaml",
            "benchmark_definition.yaml",
            "benchmark_assembly_definition.yaml",
            "manufacturing_config.yaml",
            ".manifests/engineering_plan_review_manifest.json",
            "renders/render_manifest.json",
        )
        for required_path in planner_required_artifacts:
            assert Path(required_path) in planner_artifact_paths, (
                f"{required_path} missing from planner stage artifacts. "
                f"Artifacts: {planner_artifact_paths}"
            )
        planner_render_paths = [
            path
            for path in planner_artifact_paths
            if path.parent.name == "renders"
            and path.suffix in {".png", ".jpg", ".jpeg"}
        ]
        assert planner_render_paths, (
            f"Expected real render artifacts in planner stage. Artifacts: {planner_artifact_paths}"
        )

        planner_tool_traces = [
            trace
            for trace in planner_episode.traces
            if trace.trace_type == TraceType.TOOL_START
        ]
        planner_tool_trace_names = [
            trace.name for trace in planner_tool_traces if trace.name
        ]
        assert "submit_engineering_plan" in planner_tool_trace_names, (
            f"Expected TOOL_START trace for submit_engineering_plan. Observed: {planner_tool_trace_names}"
        )
        assert any(
            trace.name in {"inspect_media", "inspect_media_tool"}
            for trace in planner_tool_traces
        ), (
            f"Expected inspect_media TOOL_START trace. Observed: {planner_tool_trace_names}"
        )
        assert any(
            trace.name == "media_inspection" for trace in planner_episode.traces
        ), "Expected media_inspection trace from planner stage render review."
        assert any(
            trace.name == "llm_media_attached" for trace in planner_episode.traces
        ), "Expected llm_media_attached trace from planner stage render review."

        plan_manifest_path = next(
            path
            for path in planner_artifact_paths
            if path == Path(".manifests/engineering_plan_review_manifest.json")
        )
        plan_manifest = PlanReviewManifest.model_validate_json(
            await _read_episode_asset_text(
                client,
                planner_episode_id,
                plan_manifest_path,
            )
        )
        assert plan_manifest.status == "ready_for_review"
        assert plan_manifest.reviewer_stage == AgentName.ENGINEER_PLAN_REVIEWER
        assert plan_manifest.planner_node_type == AgentName.ENGINEER_PLANNER
        assert plan_manifest.session_id == engineer_session_id
        assert plan_manifest.episode_id == planner_episode_id
        assert plan_manifest.worker_session_id == engineer_session_id
        assert plan_manifest.benchmark_revision == repo_git_revision()
        expected_plan_hashes = {
            "engineering_plan.md",
            "todo.md",
            "benchmark_definition.yaml",
            "manufacturing_config.yaml",
        }
        assert expected_plan_hashes <= set(plan_manifest.artifact_hashes), (
            plan_manifest.artifact_hashes
        )
        planner_render_manifest_path = next(
            path
            for path in planner_artifact_paths
            if path == Path("renders/render_manifest.json")
        )
        planner_render_manifest = RenderManifest.model_validate_json(
            await _read_episode_asset_text(
                client, planner_episode_id, planner_render_manifest_path
            )
        )
        assert planner_render_manifest.preview_evidence_paths, (
            "Planner render manifest must preserve preview evidence paths."
        )
        assert {
            _asset_path(path) for path in planner_render_manifest.preview_evidence_paths
        } <= set(planner_artifact_paths), planner_render_manifest.preview_evidence_paths
        for asset_path in expected_plan_hashes:
            asset_text = await _read_episode_asset_text(
                client, planner_episode_id, asset_path
            )
            assert (
                hashlib.sha256(asset_text.encode("utf-8")).hexdigest()
                == plan_manifest.artifact_hashes[asset_path]
            ), f"Hash mismatch for {asset_path}"

        assembly_definition_text = await _read_episode_asset_text(
            client, planner_episode_id, "assembly_definition.yaml"
        )
        assembly_definition_model = yaml.safe_load(assembly_definition_text)
        assert assembly_definition_model is not None
        assert (
            assembly_definition_model["constraints"]["planner_target_max_unit_cost_usd"]
            == 200
        )
        assert (
            assembly_definition_model["constraints"]["planner_target_max_weight_g"]
            == 600
        )

        plan_reviewer_episode_id = await _launch_engineer_run(
            task_suffix="engineer plan reviewer stage",
            agent_name=AgentName.ENGINEER_PLAN_REVIEWER,
            start_node=AgentName.ENGINEER_PLAN_REVIEWER,
        )
        plan_reviewer_episode = EpisodeResponse.model_validate(
            await wait_for_episode_terminal(
                client,
                plan_reviewer_episode_id,
                timeout_s=240.0,
                terminal_statuses={
                    EpisodeStatus.COMPLETED,
                    EpisodeStatus.FAILED,
                    EpisodeStatus.CANCELLED,
                },
            )
        )
        assert plan_reviewer_episode.status == EpisodeStatus.COMPLETED, (
            f"Plan reviewer stage failed. Last status: {plan_reviewer_episode.status}"
        )
        assert plan_reviewer_episode.user_session_id == user_session_id
        assert plan_reviewer_episode.metadata_vars is not None
        assert plan_reviewer_episode.metadata_vars.episode_type == EpisodeType.ENGINEER
        assert plan_reviewer_episode.metadata_vars.benchmark_id == benchmark_episode_id
        assert (
            plan_reviewer_episode.metadata_vars.detailed_status
            == EpisodeStatus.COMPLETED.value
        )
        assert plan_reviewer_episode.metadata_vars.terminal_reason == (
            TerminalReason.APPROVED
        )

        plan_reviewer_traces = [
            trace
            for trace in plan_reviewer_episode.traces
            if trace.trace_type == TraceType.TOOL_START
        ]
        plan_reviewer_trace_names = [
            trace.name for trace in plan_reviewer_traces if trace.name
        ]
        assert any(
            trace.name in {"inspect_media", "inspect_media_tool"}
            for trace in plan_reviewer_traces
        ), (
            f"Expected inspect_media TOOL_START trace during plan review. "
            f"Observed: {plan_reviewer_trace_names}"
        )
        plan_review_traces = [
            trace
            for trace in plan_reviewer_episode.traces
            if trace.name == "review_decision" and trace.metadata_vars is not None
        ]
        assert plan_review_traces, "Expected plan review_decision trace trail."
        latest_plan_review_trace = max(plan_review_traces, key=lambda trace: trace.id)
        assert (
            latest_plan_review_trace.metadata_vars.decision == ReviewDecision.APPROVED
        )
        assert latest_plan_review_trace.metadata_vars.review_id is not None

        plan_comments = yaml.safe_load(
            await _read_episode_asset_text(
                client,
                plan_reviewer_episode_id,
                "reviews/engineering-plan-review-comments-round-1.yaml",
            )
        )
        assert plan_comments["summary"].startswith("APPROVED:"), plan_comments
        assert isinstance(plan_comments.get("checklist"), dict), plan_comments

        plan_decision = yaml.safe_load(
            await _read_episode_asset_text(
                client,
                plan_reviewer_episode_id,
                "reviews/engineering-plan-review-decision-round-1.yaml",
            )
        )
        assert plan_decision["decision"] == ReviewDecision.APPROVED.value

        engineer_episode_id = await _launch_engineer_run(
            task_suffix="engineer coder stage",
            agent_name=AgentName.ENGINEER_CODER,
        )
        engineer_episode = EpisodeResponse.model_validate(
            await wait_for_episode_terminal(
                client,
                engineer_episode_id,
                timeout_s=240.0,
                terminal_statuses={
                    EpisodeStatus.COMPLETED,
                    EpisodeStatus.FAILED,
                    EpisodeStatus.CANCELLED,
                },
            )
        )
        assert engineer_episode.status == EpisodeStatus.COMPLETED, (
            f"Engineer loop failed. Last status: {engineer_episode.status}"
        )
        assert engineer_episode.user_session_id == user_session_id
        assert engineer_episode.metadata_vars is not None
        assert engineer_episode.metadata_vars.episode_type == EpisodeType.ENGINEER
        assert engineer_episode.metadata_vars.benchmark_id == benchmark_episode_id
        assert (
            engineer_episode.metadata_vars.detailed_status
            == EpisodeStatus.COMPLETED.value
        )
        assert engineer_episode.metadata_vars.terminal_reason == TerminalReason.APPROVED

        episode_resp = await client.get(f"/api/episodes/{engineer_episode_id}")
        assert episode_resp.status_code == 200, episode_resp.text
        episode_data = EpisodeResponse.model_validate(episode_resp.json())
        artifact_paths = [
            _asset_path(asset.s3_path) for asset in (episode_data.assets or [])
        ]
        traces = episode_data.traces or []

        required_artifacts = (
            "engineering_plan.md",
            "todo.md",
            "assembly_definition.yaml",
            "benchmark_definition.yaml",
            "benchmark_assembly_definition.yaml",
            "manufacturing_config.yaml",
            "benchmark_script.py",
            "solution_script.py",
            "validation_results.json",
            "simulation_result.json",
            ".manifests/benchmark_plan_review_manifest.json",
            ".manifests/benchmark_review_manifest.json",
            ".manifests/engineering_plan_review_manifest.json",
            ".manifests/engineering_execution_handoff_manifest.json",
            "renders/render_manifest.json",
            "reviews/engineering-plan-review-decision-round-1.yaml",
            "reviews/engineering-plan-review-comments-round-1.yaml",
            "reviews/engineering-execution-review-decision-round-1.yaml",
            "reviews/engineering-execution-review-comments-round-1.yaml",
        )
        for required_path in required_artifacts:
            assert Path(required_path) in artifact_paths, (
                f"{required_path} missing from engineer episode artifacts. "
                f"Artifacts: {artifact_paths}"
            )
        assert any(
            path.parent.name == "renders" and path.suffix in {".png", ".jpg", ".jpeg"}
            for path in artifact_paths
        ), f"Expected render images in engineer artifacts. Artifacts: {artifact_paths}"
        assert Path("benchmark_script.py") in artifact_paths, (
            f"Expected benchmark_script.py in engineer artifacts. Artifacts: {artifact_paths}"
        )
        assert Path("solution_script.py") in artifact_paths, (
            f"Expected solution_script.py in engineer artifacts. Artifacts: {artifact_paths}"
        )
        assert Path(".manifests/current_role.json") in artifact_paths, (
            f"Expected current_role.json in engineer artifacts. Artifacts: {artifact_paths}"
        )

        tool_traces = [
            trace for trace in traces if trace.trace_type == TraceType.TOOL_START
        ]
        tool_trace_names = [trace.name for trace in tool_traces if trace.name]
        assert any(
            trace.name in {"inspect_media", "inspect_media_tool"}
            for trace in tool_traces
        ), f"Expected inspect_media TOOL_START trace. Observed: {tool_trace_names}"
        assert any(trace.name == "media_inspection" for trace in traces), (
            "Expected media_inspection trace from latest-revision render review."
        )
        assert any(trace.name == "llm_media_attached" for trace in traces), (
            "Expected llm_media_attached trace from latest-revision render review."
        )

        review_traces = [
            trace
            for trace in traces
            if trace.name == "review_decision" and trace.metadata_vars is not None
        ]
        assert review_traces, "Expected review_decision trace trail from live review."
        latest_review_trace = max(review_traces, key=lambda trace: trace.id)
        assert latest_review_trace.metadata_vars.decision == ReviewDecision.APPROVED
        assert latest_review_trace.metadata_vars.review_id is not None

        validation_result_text = await _read_episode_asset_text(
            client, engineer_episode_id, "validation_results.json"
        )
        validation_result = ValidationResultRecord.model_validate_json(
            validation_result_text
        )
        assert validation_result.success is True
        assert validation_result.script_path == "solution_script.py"
        assert validation_result.script_sha256 is not None
        script_text = await _read_episode_asset_text(
            client, engineer_episode_id, validation_result.script_path
        )
        assert hashlib.sha256(script_text.encode("utf-8")).hexdigest() == (
            validation_result.script_sha256
        )
        assert validation_result.verification_result is not None
        assert validation_result.verification_result.scene_build_count == 1
        assert validation_result.verification_result.backend_run_count == 1
        assert validation_result.verification_result.batched_execution is True
        assert validation_result.verification_result.success_count == (
            validation_result.verification_result.num_scenes
        )
        assert validation_result.verification_result.fail_reasons == []
        assert validation_result.verification_result.is_consistent is True

        simulation_result_text = await _read_episode_asset_text(
            client, engineer_episode_id, "simulation_result.json"
        )
        simulation_result = SimulationResult.model_validate_json(simulation_result_text)
        assert simulation_result.success is True
        assert simulation_result.render_paths

        render_manifest_path = next(
            path
            for path in artifact_paths
            if path == Path("renders/render_manifest.json")
        )
        render_manifest = RenderManifest.model_validate_json(
            await _read_episode_asset_text(
                client, engineer_episode_id, render_manifest_path
            )
        )
        assert render_manifest.revision == repo_git_revision()
        assert render_manifest.episode_id == engineer_episode_id
        assert render_manifest.worker_session_id == engineer_session_id
        assert render_manifest.preview_evidence_paths
        assert {
            _asset_path(path) for path in render_manifest.preview_evidence_paths
        } == {_asset_path(path) for path in simulation_result.render_paths}

        execution_manifest_path = next(
            path
            for path in artifact_paths
            if path == Path(".manifests/engineering_execution_handoff_manifest.json")
        )
        execution_manifest = ReviewManifest.model_validate_json(
            await _read_episode_asset_text(
                client, engineer_episode_id, execution_manifest_path
            )
        )
        assert execution_manifest.status == "ready_for_review"
        assert execution_manifest.reviewer_stage == "engineering_execution_reviewer"
        assert execution_manifest.session_id == engineer_session_id
        assert execution_manifest.episode_id == engineer_episode_id
        assert execution_manifest.worker_session_id == engineer_session_id
        assert execution_manifest.benchmark_episode_id == benchmark_episode_id
        assert execution_manifest.benchmark_worker_session_id == benchmark_session_id
        assert execution_manifest.revision == repo_git_revision()
        assert execution_manifest.benchmark_revision == repo_git_revision()
        assert execution_manifest.solution_revision == repo_git_revision()
        assert execution_manifest.script_path == "solution_script.py"
        assert execution_manifest.validation_success is True
        assert execution_manifest.simulation_success is True
        assert execution_manifest.goal_reached is True
        assert execution_manifest.script_sha256 == validation_result.script_sha256
        assert {
            _asset_path(path) for path in execution_manifest.preview_evidence_paths
        } == {_asset_path(path) for path in execution_manifest.renders}
        assert {_asset_path(path) for path in execution_manifest.renders} == {
            _asset_path(path) for path in render_manifest.preview_evidence_paths
        }
        assert {
            _asset_path(path) for path in execution_manifest.preview_evidence_paths
        } == {_asset_path(path) for path in render_manifest.preview_evidence_paths}

        final_preview_scene_path = next(
            path
            for path in artifact_paths
            if path
            == Path("renders/final_solution_submission_renders/preview_scene.json")
        )
        benchmark_definition = BenchmarkDefinition.model_validate(
            yaml.safe_load(
                await _read_episode_asset_text(
                    client, engineer_episode_id, "benchmark_definition.yaml"
                )
            )
        )
        final_preview_scene = PreviewScene.model_validate_json(
            await _read_episode_asset_text(
                client, engineer_episode_id, final_preview_scene_path
            )
        )
        assert final_preview_scene.component_label == "benchmark_environment"
        final_preview_labels = {entity.label for entity in final_preview_scene.entities}
        assert len(final_preview_scene.entities) == len(final_preview_labels), (
            final_preview_scene.entities
        )
        assert {
            "left_start_deck",
            "right_goal_deck",
            "bridge_reference_table",
            "gap_floor_guard",
            benchmark_definition.payload.label,
        } <= final_preview_labels
        payload_entity = next(
            entity
            for entity in final_preview_scene.entities
            if entity.label == benchmark_definition.payload.label
        )
        assert payload_entity.body_name == moved_object_scene_name(payload_entity.label)
        assert payload_entity.pos == tuple(
            float(value) for value in benchmark_definition.payload.start_position
        )

        execution_comments = yaml.safe_load(
            await _read_episode_asset_text(
                client,
                engineer_episode_id,
                "reviews/engineering-execution-review-comments-round-1.yaml",
            )
        )
        assert execution_comments["summary"].startswith("APPROVED:"), execution_comments
        assert isinstance(execution_comments.get("checklist"), dict), execution_comments

        execution_decision = yaml.safe_load(
            await _read_episode_asset_text(
                client,
                engineer_episode_id,
                "reviews/engineering-execution-review-decision-round-1.yaml",
            )
        )
        assert execution_decision["decision"] == ReviewDecision.APPROVED.value


@pytest.mark.integration_p1
@pytest.mark.allow_backend_errors(
    regexes=["plan_md_invalid", "plan_md_missing_sections"]
)
@pytest.mark.int_id("INT-033")
@pytest.mark.asyncio
async def test_engineering_submit_rejects_shuffled_calc_headings():
    """
    INT-033: Engineering submit must reject a shuffled-but-complete Detailed
    Calculations block with a descriptive order error.
    """
    async with AsyncClient(base_url=CONTROLLER_URL, timeout=300.0) as client:
        session_id = f"INT-033-order-{uuid.uuid4().hex[:8]}"
        await _write_workspace_file(
            client,
            session_id,
            "solution_script.py",
            """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod


def build():
    part = Box(1, 1, 1)
    part = part.move(Location((0, 0, 0.5)))
    part.label = "test_part"
    part.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum-6061",
    )
    return part
""".strip()
            + "\n",
        )
        await _write_workspace_file(
            client,
            session_id,
            ".manifests/current_role.json",
            current_role_manifest_json(AgentName.ENGINEER_CODER),
        )
        shuffled_plan = """## 1. Solution Overview
A concise engineering overview.

## 2. Parts List
- `support_frame`

## 3. Assembly Strategy
1. Mount the support frame.

## 4. Assumption Register
- Assumption: The frame geometry is sourced from the approved handoff.

## 5. Detailed Calculations
| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Support-frame clearance check | Pass | Confirms the frame stays within the operating envelope. |

### CALC-001: Support-frame clearance check

#### Result

- Pass

#### Problem Statement

The support frame must remain clear of the moved object.

#### Assumptions

- `ASSUMP-001`: The frame geometry is fixed by the engineering handoff.

#### Derivation

- The clearance is computed from the declared frame envelope.

#### Worst-Case Check

- The minimum clearance remains positive at the worst-case pose.

#### Design Impact

- Keep the frame geometry unchanged.

#### Cross-References

- `engineering_plan.md#3-assembly-strategy`

## 6. Critical Constraints / Operating Envelope
- Constraint: The frame must remain within the derived limits.

## 7. Cost & Weight Budget
- Cost: 0

## 8. Risk Assessment
- Risk: Heading order drift.
"""
        await _write_workspace_file(
            client, session_id, "engineering_plan.md", shuffled_plan
        )
        submit_req = BenchmarkToolRequest(
            script_path="solution_script.py",
            reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        submit_resp = await client.post(
            f"{WORKER_HEAVY_URL}/engineering/submit",
            json=submit_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        assert submit_resp.status_code == 200, submit_resp.text
        submit_data = BenchmarkToolResponse.model_validate(submit_resp.json())
        assert not submit_data.success, submit_data.message
        assert "appear in the required order" in submit_data.message
        assert "CALC-001" in submit_data.message


async def _wait_for_episode_terminal(
    client: AsyncClient,
    episode_id: str,
    *,
    timeout_seconds: int = 240,
) -> EpisodeResponse:
    return EpisodeResponse.model_validate(
        await wait_for_episode_terminal(
            client,
            episode_id,
            timeout_s=timeout_seconds,
            terminal_statuses={
                EpisodeStatus.COMPLETED,
                EpisodeStatus.FAILED,
                EpisodeStatus.CANCELLED,
            },
        )
    )


async def _reject_episode(client: AsyncClient, episode_id: str) -> EpisodeResponse:
    validation_results_text = await _read_episode_asset_text(
        client, episode_id, "validation_results.json"
    )
    validation_results = ValidationResultRecord.model_validate_json(
        validation_results_text
    )
    verification_result = validation_results.verification_result
    assert verification_result is not None, "validation_results.json is missing"

    review_content = "---\n"
    review_content += yaml.safe_dump(
        {
            "decision": "rejected",
            "comments": ["Retry lineage test rejection"],
            "evidence": {
                "files_checked": ["engineering_plan.md"],
                "stability_summary": {
                    "batchWidth": verification_result.num_scenes,
                    "successCount": verification_result.success_count,
                    "successRate": verification_result.success_rate,
                    "isConsistent": verification_result.is_consistent,
                    "sceneBuildCount": verification_result.scene_build_count,
                    "backendRunCount": verification_result.backend_run_count,
                    "batchedExecution": verification_result.batched_execution,
                    "sceneSummaries": [
                        {
                            "sceneIndex": idx + 1,
                            "success": scene.success,
                            "summary": (
                                f"Scene {idx + 1}: pass"
                                if scene.success
                                else f"Scene {idx + 1}: {scene.fail_reason}"
                            ),
                            "failReason": scene.fail_reason,
                            "failureMode": (
                                scene.fail_mode.value if scene.fail_mode else None
                            ),
                        }
                        for idx, scene in enumerate(
                            verification_result.individual_results
                        )
                    ],
                },
                "stability_summary_source": "validation_results.json",
            },
        },
        sort_keys=False,
    ).strip()
    review_content += "\n---\nRejecting the episode for deterministic retry coverage.\n"
    response = await client.post(
        f"/api/episodes/{episode_id}/review",
        json={"review_content": review_content},
    )
    assert response.status_code == 200, response.text
    status_response = await client.get(f"/api/episodes/{episode_id}")
    assert status_response.status_code == 200, status_response.text
    episode = EpisodeResponse.model_validate(status_response.json())
    assert episode.status == EpisodeStatus.FAILED
    return episode


async def _read_episode_asset_text(
    client: AsyncClient, episode_id: str, asset_path: str
) -> str:
    resp = await client.get(f"/api/episodes/{episode_id}/assets/{asset_path}")
    assert resp.status_code == 200, resp.text
    return resp.text
