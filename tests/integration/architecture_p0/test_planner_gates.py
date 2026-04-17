import asyncio
import hashlib
import json
import os
import re
import uuid
from contextlib import suppress
from pathlib import Path

import httpx
import pytest
import yaml

from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    BenchmarkGenerateRequest,
    BenchmarkGenerateResponse,
    ConfirmRequest,
    EpisodeResponse,
)
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName, EpisodeStatus, ManufacturingMethod, TraceType
from shared.models.schemas import (
    AssemblyConstraints,
    AssemblyDefinition,
    BenchmarkDefinition,
    BenchmarkPartDefinition,
    BenchmarkPartMetadata,
    BoundingBox,
    Constraints,
    CostTotals,
    ManufacturedPartEstimate,
    ObjectivesSection,
    PartConfig,
    Payload,
    PayloadTrajectoryAnchor,
    PayloadTrajectoryDefinition,
    PayloadTrajectoryPose,
    PayloadTrajectoryTerminalEvent,
)
from shared.models.serialization import dump_yaml_content
from shared.models.simulation import SimulationResult
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.schema import (
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    DeleteFileRequest,
    ExecuteRequest,
    ExecuteResponse,
    PlanReviewManifest,
    WriteFileRequest,
)
from tests.integration.agent.helpers import dump_yaml_model, wait_for_benchmark_state
from tests.integration.backend_utils import selected_backend

# Constants
WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
WORKER_HEAVY_URL = os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002")
CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")
REPO_MANUFACTURING_CONFIG = Path(
    "worker_heavy/workbenches/manufacturing_config.yaml"
).read_text(encoding="utf-8")
pytestmark = pytest.mark.xdist_group(name="physics_sims")


def _asset_path(asset_path: str | Path) -> Path:
    return Path(str(asset_path).lstrip("/"))


def _default_benchmark_parts():
    return [
        BenchmarkPartDefinition(
            part_id="environment_fixture",
            label="environment_fixture",
            metadata=BenchmarkPartMetadata(
                is_fixed=True,
                material_id="aluminum_6061",
            ),
        )
    ]


@pytest.fixture
def session_id(request):
    match = re.search(r"test_int_(\d{3})", request.node.name, re.IGNORECASE)
    prefix = f"INT-{match.group(1)}" if match else "test-gates"
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def base_headers(session_id):
    return {"X-Session-ID": session_id}


@pytest.fixture
def valid_plan():
    return """## 1. Solution Overview
A valid solution overview.

## 2. Parts List
| Part | Qty |
|------|-----|
| Box  | 1   |

## 3. Assembly Strategy
1. Step one.

## 4. Assumption Register
- Assumption: The planner relies on source-backed inputs that must be traceable.

## 5. Detailed Calculations
| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Minimum slope needed to move cube under worst-case friction | `21.7deg` | Ramp angle must be updated or assumptions must change. |

### CALC-001: Minimum slope needed to move cube

#### Problem Statement

The cube must slide reliably under the declared surface/friction assumptions.

#### Assumptions

- `ASSUMP-001`: The surface friction coefficient is taken from the benchmark definition.

#### Derivation

- The minimum slope is computed from the worst-case static friction threshold.

#### Worst-Case Check

- The threshold remains satisfied only when the slope is at least `21.7deg`.

#### Result

- The cube slides.

#### Design Impact

- The ramp angle must be updated or the assumptions must change.

#### Cross-References

- `benchmark_plan.md#3-assembly-strategy`

## 6. Critical Constraints / Operating Envelope
- Constraint: The mechanism must remain inside the derived operating limits.

## 7. Cost & Weight Budget
- Cost: $10
- Weight: 100g

## 8. Risk Assessment
- Risk: Low
"""


@pytest.fixture
def valid_todo():
    return "- [x] Step 1\n- [-] Step 2"


@pytest.fixture
def valid_objectives():
    return BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(
                min_mm=(10.0, 10.0, 10.0), max_mm=(20.0, 20.0, 20.0)
            ),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-50.0, -50.0, 0.0), max_mm=(50.0, 50.0, 90.0)
            ),
        ),
        benchmark_parts=_default_benchmark_parts(),
        simulation_bounds_mm=BoundingBox(
            min_mm=(-100.0, -100.0, 0.0), max_mm=(100.0, 100.0, 100.0)
        ),
        payload=Payload(
            label="ball",
            shape="sphere",
            material_id="aluminum_6061",
            start_position_mm=(0.0, 0.0, 50.0),
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=50.0, max_weight_g=1000.0),
    )


@pytest.fixture
def valid_cost():
    return AssemblyDefinition(
        version="1.0",
        constraints=AssemblyConstraints(
            benchmark_max_unit_cost_usd=50.0,
            benchmark_max_weight_g=1000.0,
            planner_target_max_unit_cost_usd=45.0,
            planner_target_max_weight_g=900.0,
        ),
        totals=CostTotals(
            estimated_unit_cost_usd=30.0,
            estimated_weight_g=500.0,
            estimate_confidence="high",
        ),
    )


@pytest.fixture
def minimal_script():
    return """
from build123d import *
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod
def build():
    # Box 10x10x10 centered at (0,0,5) -> Z from 0 to 10.
    # Build zone is [0, 100] in objectives.
    p = Box(10, 10, 10)
    p = p.move(Location((0, 0, 5)))
    p.label = "test_part"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC, material_id="aluminum-6061"
    )
    return p
"""


async def setup_workspace(client, headers, files):
    """Utility to setup a workspace. Overwrites if exists."""
    if ".manifests/current_role.json" not in files:
        files = {
            **files,
            ".manifests/current_role.json": current_role_manifest_json(
                AgentName.BENCHMARK_CODER
            ),
        }
    for path, content in files.items():
        content_str = dump_yaml_content(content)

        write_req = WriteFileRequest(
            path=path,
            content=content_str,
            overwrite=True,
        )
        resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_req.model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, f"Failed to write {path}: {resp.text}"


async def _validate_solution_script(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    script_path: str,
    *,
    reviewer_stage: AgentName = AgentName.BENCHMARK_REVIEWER,
) -> BenchmarkToolResponse:
    resp = await client.post(
        f"{WORKER_LIGHT_URL}/benchmark/validate",
        json=BenchmarkToolRequest(
            script_path=script_path, reviewer_stage=reviewer_stage
        ).model_dump(mode="json"),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return BenchmarkToolResponse.model_validate(resp.json())


async def _seed_successful_simulation_result(
    client: httpx.AsyncClient, headers: dict[str, str], script_path: str
) -> SimulationResult:
    simulation_result = SimulationResult(
        success=True,
        summary="Goal achieved in green zone.",
        render_paths=[],
        confidence="high",
    )
    resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path="simulation_result.json",
            content=simulation_result.model_dump_json(indent=2),
            overwrite=True,
        ).model_dump(mode="json"),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    heavy_resp = await client.post(
        f"{WORKER_HEAVY_URL}/fs/write",
        json=WriteFileRequest(
            path="simulation_result.json",
            content=simulation_result.model_dump_json(indent=2),
            overwrite=True,
        ).model_dump(mode="json"),
        headers=headers,
    )
    assert heavy_resp.status_code == 200, heavy_resp.text
    return simulation_result


def _parse_submit_observation_node_type(observation: str | None) -> str | None:
    if not observation:
        return None
    with suppress(Exception):
        parsed = json.loads(observation)
        if isinstance(parsed, dict):
            node_type = parsed.get("node_type")
            return str(node_type) if node_type else None
    with suppress(Exception):
        import ast

        parsed = ast.literal_eval(observation)
        if isinstance(parsed, dict):
            node_type = parsed.get("node_type")
            return str(node_type) if node_type else None
    return None


def _submit_plan_node_types_from_episode_traces(
    traces, *, submit_tool_name: str
) -> set[str]:
    node_types: set[str] = set()
    for trace in traces or []:
        if trace.trace_type != TraceType.TOOL_START or trace.name != submit_tool_name:
            continue
        metadata = trace.metadata_vars
        if metadata is None:
            continue
        parsed_node_type = _parse_submit_observation_node_type(metadata.observation)
        if parsed_node_type:
            node_types.add(parsed_node_type)
    return node_types


async def _wait_for_submit_plan_node_types(
    client: httpx.AsyncClient,
    episode_id: str,
    required_node_type: str,
    *,
    submit_tool_name: str,
) -> tuple[EpisodeStatus | None, set[str]]:
    target_statuses = {EpisodeStatus.COMPLETED, EpisodeStatus.FAILED}
    status: EpisodeStatus | None = None
    submit_node_types: set[str] = set()
    for _ in range(90):
        ep_resp = await client.get(f"{CONTROLLER_URL}/api/episodes/{episode_id}")
        assert ep_resp.status_code == 200, ep_resp.text
        episode = EpisodeResponse.model_validate(ep_resp.json())
        status = episode.status
        submit_node_types = _submit_plan_node_types_from_episode_traces(
            episode.traces or [], submit_tool_name=submit_tool_name
        )
        if required_node_type in submit_node_types:
            break
        if status in target_statuses:
            break
        await asyncio.sleep(1)
    return status, submit_node_types


async def _wait_for_planned_after_submit_plan(
    client: httpx.AsyncClient, episode_id: str
) -> EpisodeStatus | None:
    status: EpisodeStatus | None = None
    for _ in range(90):
        ep_resp = await client.get(f"{CONTROLLER_URL}/api/episodes/{episode_id}")
        assert ep_resp.status_code == 200, ep_resp.text
        episode = EpisodeResponse.model_validate(ep_resp.json())
        status = episode.status
        if status in {EpisodeStatus.PLANNED, EpisodeStatus.FAILED}:
            break
        await asyncio.sleep(1)
    return status


async def _wait_for_submit_plan_node_types_benchmark(
    client: httpx.AsyncClient,
    session_id: str,
    required_node_type: str,
    *,
    submit_tool_name: str,
) -> tuple[EpisodeStatus | None, set[str]]:
    episode = EpisodeResponse.model_validate(
        await wait_for_benchmark_state(
            client,
            session_id,
            timeout_s=90.0,
            terminal_statuses={
                EpisodeStatus.PLANNED,
                EpisodeStatus.COMPLETED,
                EpisodeStatus.FAILED,
            },
            predicate=lambda candidate: (
                required_node_type
                in _submit_plan_node_types_from_episode_traces(
                    candidate.traces or [], submit_tool_name=submit_tool_name
                )
            ),
        )
    )
    return (
        episode.status,
        _submit_plan_node_types_from_episode_traces(
            episode.traces or [], submit_tool_name=submit_tool_name
        ),
    )


async def _wait_for_planned_after_submit_plan_benchmark(
    client: httpx.AsyncClient, session_id: str
) -> EpisodeStatus | None:
    episode = EpisodeResponse.model_validate(
        await wait_for_benchmark_state(
            client,
            session_id,
            timeout_s=90.0,
            terminal_statuses={EpisodeStatus.PLANNED, EpisodeStatus.FAILED},
        )
    )
    return episode.status


async def _wait_for_benchmark_asset(
    client: httpx.AsyncClient, session_id: str, suffix: str
) -> list[str]:
    suffix_path = Path(suffix)
    episode = EpisodeResponse.model_validate(
        await wait_for_benchmark_state(
            client,
            session_id,
            timeout_s=90.0,
            terminal_statuses={EpisodeStatus.FAILED},
            predicate=lambda candidate: any(
                _asset_path(asset.s3_path).name == suffix_path.name
                for asset in (candidate.assets or [])
            ),
        )
    )
    return [
        str(_asset_path(asset.s3_path))
        for asset in (episode.assets or [])
        if _asset_path(asset.s3_path).name == suffix_path.name
    ]


async def _generate_ready_benchmark_session(
    client: httpx.AsyncClient, *, prompt: str
) -> str:
    req = BenchmarkGenerateRequest(prompt=prompt, backend=SimulatorBackendType.GENESIS)
    resp = await client.post(
        f"{CONTROLLER_URL}/api/benchmark/generate", json=req.model_dump(mode="json")
    )
    assert resp.status_code in {200, 202}, resp.text
    run_resp = BenchmarkGenerateResponse.model_validate(resp.json())
    benchmark_session_id = str(run_resp.session_id)

    planned_session = EpisodeResponse.model_validate(
        await wait_for_benchmark_state(
            client,
            benchmark_session_id,
            timeout_s=150.0,
            terminal_statuses={
                EpisodeStatus.PLANNED,
                EpisodeStatus.COMPLETED,
                EpisodeStatus.FAILED,
            },
        )
    )
    if planned_session.status == EpisodeStatus.FAILED:
        pytest.fail(
            "Benchmark generation failed during setup "
            f"(session_id={benchmark_session_id})."
        )

    if planned_session.status == EpisodeStatus.PLANNED:
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="manufacturing_config.yaml",
                content=REPO_MANUFACTURING_CONFIG,
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": benchmark_session_id},
        )
        await client.post(
            f"{CONTROLLER_URL}/api/benchmark/{benchmark_session_id}/confirm",
            json=ConfirmRequest(comment="Proceed").model_dump(),
        )
        final_session = EpisodeResponse.model_validate(
            await wait_for_benchmark_state(
                client,
                benchmark_session_id,
                timeout_s=150.0,
                terminal_statuses={EpisodeStatus.COMPLETED, EpisodeStatus.FAILED},
            )
        )
        if final_session.status == EpisodeStatus.FAILED:
            pytest.fail(
                "Benchmark generation failed during setup "
                f"(session_id={benchmark_session_id})."
            )

    return str(run_resp.episode_id)


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "plan_md_missing",
        "todo_md_missing",
        "benchmark_assembly_definition_yaml_missing",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-005")
async def test_int_005_mandatory_artifacts_gate(
    session_id,
    base_headers,
    valid_plan,
    valid_todo,
    valid_objectives,
    valid_cost,
    minimal_script,
):
    """INT-005: Verify rejection if mandatory artifacts are missing."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # Initial: All required files except one
        base_files = {
            "benchmark_plan.md": valid_plan,
            "todo.md": valid_todo,
            "benchmark_definition.yaml": valid_objectives,
            "benchmark_assembly_definition.yaml": valid_cost,
            "solution.py": minimal_script,
        }

        # 1. Missing benchmark_plan.md
        files = base_files.copy()
        del files["benchmark_plan.md"]
        await setup_workspace(client, base_headers, files)
        delete_req = DeleteFileRequest(path="benchmark_plan.md")
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/delete",
            json=delete_req.model_dump(mode="json"),
            headers=base_headers,
        )

        submit_req = BenchmarkToolRequest(
            script_path="solution.py", reviewer_stage=AgentName.BENCHMARK_REVIEWER
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert not data.success
        assert "Missing required plan file: benchmark_plan.md" in data.message

        # 2. Missing todo.md
        files = base_files.copy()
        del files["todo.md"]
        await setup_workspace(client, base_headers, files)
        delete_todo_req = DeleteFileRequest(path="todo.md")
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/delete",
            json=delete_todo_req.model_dump(mode="json"),
            headers=base_headers,
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert not data.success
        assert "todo.md is missing" in data.message

        # 3. Missing benchmark_assembly_definition.yaml
        files = base_files.copy()
        del files["benchmark_assembly_definition.yaml"]
        await setup_workspace(client, base_headers, files)
        delete_cost_req = DeleteFileRequest(path="benchmark_assembly_definition.yaml")
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/delete",
            json=delete_cost_req.model_dump(mode="json"),
            headers=base_headers,
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert not data.success
        assert "benchmark_assembly_definition.yaml is missing" in data.message


@pytest.mark.integration_p0
@pytest.mark.xdist_group(name="physics_sims")
@pytest.mark.asyncio
@pytest.mark.int_id("INT-005")
async def test_int_005_engineer_planner_flow_emits_submit_engineering_plan_trace():
    """INT-005: Engineer planner must emit explicit submit_engineering_plan TOOL_START before completion."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        benchmark_session_id = await _generate_ready_benchmark_session(
            client, prompt="INT-005 benchmark setup for engineer planner trace test."
        )
        session_id = f"INT-005-{uuid.uuid4().hex[:8]}"
        req = AgentRunRequest(
            task="INT-005 engineer planner submission trace contract.",
            session_id=session_id,
            agent_name=AgentName.ENGINEER_PLANNER,
            metadata_vars={"benchmark_id": benchmark_session_id},
        )
        resp = await client.post(
            f"{CONTROLLER_URL}/api/agent/run", json=req.model_dump(mode="json")
        )
        assert resp.status_code == 202, resp.text
        run_resp = AgentRunResponse.model_validate(resp.json())
        episode_id = str(run_resp.episode_id)

        status, submit_node_types = await _wait_for_submit_plan_node_types(
            client,
            episode_id,
            AgentName.ENGINEER_PLANNER.value,
            submit_tool_name="submit_engineering_plan",
        )
        assert AgentName.ENGINEER_PLANNER.value in submit_node_types, (
            "Expected submit_engineering_plan TOOL_START trace with node_type=engineer_planner "
            f"in engineer planner flow. Observed node_types={sorted(submit_node_types)}, status={status}"
        )
        post_submit_status = await _wait_for_planned_after_submit_plan(
            client, episode_id
        )
        assert post_submit_status != EpisodeStatus.FAILED, (
            "Engineer planner reached FAILED after submit_engineering_plan; expected PLANNED."
        )
        assert post_submit_status == EpisodeStatus.PLANNED, (
            f"Expected engineer planner to reach PLANNED after submit_engineering_plan, got {post_submit_status}."
        )

        manifest_resp = await client.get(
            f"{CONTROLLER_URL}/api/episodes/{episode_id}/assets/.manifests/engineering_plan_review_manifest.json"
        )
        assert manifest_resp.status_code == 200, manifest_resp.text
        manifest = PlanReviewManifest.model_validate_json(manifest_resp.text)
        assert "manufacturing_config.yaml" in manifest.artifact_hashes, manifest

        config_resp = await client.get(
            f"{CONTROLLER_URL}/api/episodes/{episode_id}/assets/manufacturing_config.yaml"
        )
        assert config_resp.status_code == 200, config_resp.text
        expected_hash = hashlib.sha256(config_resp.text.encode("utf-8")).hexdigest()
        assert manifest.artifact_hashes["manufacturing_config.yaml"] == expected_hash


@pytest.mark.integration_p0
# Benchmark planner traces can include fail-closed handover rejection signatures
# from guard contracts while the planner stage still reaches PLANNED.
@pytest.mark.allow_backend_errors(
    regexes=[
        "integrated_validation_error",
        "prior_validation_missing",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-114")
async def test_int_114_benchmark_planner_flow_emits_submit_benchmark_plan_trace():
    """INT-114: Benchmark planner must submit to plan review before reaching PLANNED."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        req = BenchmarkGenerateRequest(
            prompt="INT-114 benchmark planner submission trace contract.",
            backend=SimulatorBackendType.GENESIS,
        )
        resp = await client.post(
            f"{CONTROLLER_URL}/api/benchmark/generate", json=req.model_dump(mode="json")
        )
        assert resp.status_code in {200, 202}, resp.text
        run_resp = BenchmarkGenerateResponse.model_validate(resp.json())
        episode_id = str(run_resp.episode_id)

        status, submit_node_types = await _wait_for_submit_plan_node_types_benchmark(
            client,
            episode_id,
            AgentName.BENCHMARK_PLANNER.value,
            submit_tool_name="submit_benchmark_plan",
        )
        assert AgentName.BENCHMARK_PLANNER.value in submit_node_types, (
            "Expected submit_benchmark_plan TOOL_START trace with node_type=benchmark_planner "
            f"in benchmark planner flow. Observed node_types={sorted(submit_node_types)}, status={status}"
        )
        plan_review_manifest_paths = await _wait_for_benchmark_asset(
            client, episode_id, "benchmark_plan_review_manifest.json"
        )
        assert plan_review_manifest_paths, (
            "Expected benchmark plan review manifest after planner submit_benchmark_plan. "
            f"episode_id={episode_id}"
        )
        plan_review_paths = await _wait_for_benchmark_asset(
            client, episode_id, "benchmark-plan-review-decision-round-1.yaml"
        )
        assert plan_review_paths, (
            "Expected persisted benchmark plan review decision file before PLANNED. "
            f"episode_id={episode_id}"
        )
        plan_review_comment_paths = await _wait_for_benchmark_asset(
            client, episode_id, "benchmark-plan-review-comments-round-1.yaml"
        )
        assert plan_review_comment_paths, (
            "Expected persisted benchmark plan review comments file before PLANNED. "
            f"episode_id={episode_id}"
        )
        episode_resp = await client.get(f"{CONTROLLER_URL}/api/episodes/{episode_id}")
        assert episode_resp.status_code == 200, episode_resp.text
        episode_data = EpisodeResponse.model_validate(episode_resp.json())
        artifact_paths = [_asset_path(a.s3_path) for a in (episode_data.assets or [])]

        plan_paths = [p for p in artifact_paths if p == Path("benchmark_plan.md")]
        assert plan_paths, f"benchmark_plan.md missing. Artifacts: {artifact_paths}"
        plan_resp = await client.get(
            f"{CONTROLLER_URL}/api/episodes/{episode_id}/assets/{plan_paths[0]}"
        )
        assert plan_resp.status_code == 200, plan_resp.text
        plan_text = plan_resp.text.lower()
        assert "gravity" in plan_text
        assert "rigid-body" in plan_text

        benchmark_definition_paths = [
            p for p in artifact_paths if p == Path("benchmark_definition.yaml")
        ]
        assert benchmark_definition_paths, (
            f"benchmark_definition.yaml missing. Artifacts: {artifact_paths}"
        )
        benchmark_definition_resp = await client.get(
            f"{CONTROLLER_URL}/api/episodes/{episode_id}/assets/{benchmark_definition_paths[0]}"
        )
        assert benchmark_definition_resp.status_code == 200, (
            benchmark_definition_resp.text
        )
        benchmark_definition = BenchmarkDefinition.model_validate(
            yaml.safe_load(benchmark_definition_resp.text)
        )
        assert benchmark_definition.payload.material_id

        assembly_paths = [
            p for p in artifact_paths if p == Path("benchmark_assembly_definition.yaml")
        ]
        assert assembly_paths, (
            f"benchmark_assembly_definition.yaml missing. Artifacts: {artifact_paths}"
        )
        assembly_resp = await client.get(
            f"{CONTROLLER_URL}/api/episodes/{episode_id}/assets/{assembly_paths[0]}"
        )
        assert assembly_resp.status_code == 200, assembly_resp.text
        benchmark_assembly_definition = AssemblyDefinition.model_validate(
            yaml.safe_load(assembly_resp.text)
        )
        assert benchmark_assembly_definition.manufactured_parts == []
        assert benchmark_assembly_definition.final_assembly == []

        post_submit_status = await _wait_for_planned_after_submit_plan_benchmark(
            client, episode_id
        )
        assert post_submit_status != EpisodeStatus.FAILED, (
            "Benchmark plan-review flow reached FAILED after submit_benchmark_plan; expected PLANNED."
        )
        assert post_submit_status == EpisodeStatus.PLANNED, (
            "Expected benchmark plan-review approval to reach PLANNED, "
            f"got {post_submit_status}."
        )


@pytest.mark.integration_p0
# INT-006 intentionally exercises invalid plan structure paths; both the
# high-level gate and section-level reason signatures are expected.
@pytest.mark.allow_backend_errors(
    regexes=[
        "plan_md_invalid",
        "plan_md_missing_sections",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-006")
async def test_int_006_plan_structure_validation(
    session_id, base_headers, valid_todo, valid_objectives, valid_cost, minimal_script
):
    """INT-006: Verify engineering_plan.md structural requirements."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        matching_script = minimal_script.replace("test_part", "environment_fixture")
        benchmark_script = """
from build123d import *
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod
def build():
    p = Box(4, 4, 4)
    p = p.move(Location((-40, -40, 2)))
    p.label = "fixture_fixed"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC, material_id="aluminum-6061"
    )
    return p
"""
        solution_plan_evidence_script = """
from build123d import *
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod
def build():
    p = Box(66, 1, 1, align=(Align.MIN, Align.CENTER, Align.CENTER))
    p = p.move(Location((0, 0, 50)))
    p.label = "payload_ball"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC, material_id="aluminum-6061"
    )
    return p
"""
        payload_definition = PayloadTrajectoryDefinition(
            backend=SimulatorBackendType.GENESIS,
            payload_part_names=["payload_ball"],
            initial_pose=PayloadTrajectoryPose(
                reference_point="spawn_position",
                pos_mm=(0.0, 0.0, 50.0),
                rot_deg=(0.0, 0.0, 0.0),
            ),
            sample_stride_s=0.3,
            anchors=[
                PayloadTrajectoryAnchor(
                    t_s=0.0,
                    reference_point="spawn_position",
                    pos_mm=(0.0, 0.0, 50.0),
                    rot_deg=(0.0, 0.0, 0.0),
                    position_tolerance_mm=(0.5, 0.5, 0.5),
                    rotation_tolerance_deg=(0.1, 0.1, 1.0),
                    build_zone_valid=True,
                ),
                PayloadTrajectoryAnchor(
                    t_s=1.0,
                    reference_point="pre_goal",
                    pos_mm=(33.0, 33.0, 33.0),
                    rot_deg=(0.0, 0.0, 0.0),
                    position_tolerance_mm=(0.5, 0.5, 0.5),
                    rotation_tolerance_deg=(0.1, 0.1, 1.0),
                ),
            ],
            terminal_event=PayloadTrajectoryTerminalEvent(
                kind="goal_zone_contact",
                t_s=1.1,
                reference_point="goal_zone_contact",
                pos_mm=(15.0, 15.0, 15.0),
                contact_surfaces=["goal_zone"],
            ),
        )
        structure_cost = valid_cost.model_copy(deep=True)
        structure_cost.totals.estimated_unit_cost_usd = 0.0
        structure_cost.totals.estimated_weight_g = 0.0
        base_files = {
            ".manifests/current_role.json": current_role_manifest_json(
                AgentName.ENGINEER_CODER
            ),
            "todo.md": valid_todo,
            "benchmark_definition.yaml": valid_objectives,
            "assembly_definition.yaml": structure_cost,
            "manufacturing_config.yaml": REPO_MANUFACTURING_CONFIG,
            "benchmark_script.py": benchmark_script,
            "solution_script.py": solution_plan_evidence_script,
            "solution_plan_evidence_script.py": solution_plan_evidence_script,
            "payload_trajectory_definition.yaml": dump_yaml_model(payload_definition),
            "solution.py": matching_script,
        }

        # 1. Missing required heading
        invalid_plan = (
            "## 1. Solution Overview\nNo other headings.\nenvironment_fixture"
        )
        await setup_workspace(
            client, base_headers, {**base_files, "engineering_plan.md": invalid_plan}
        )
        await _validate_solution_script(
            client,
            base_headers,
            "solution.py",
            reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        sim_data = await _seed_successful_simulation_result(
            client, base_headers, "solution.py"
        )
        assert sim_data.success, sim_data.message
        submit_req = BenchmarkToolRequest(
            script_path="solution.py",
            reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "engineering_plan.md invalid" in data.message
        assert "Missing required section" in data.message

        # 2. Parts List missing table/bullets
        invalid_plan = """## 1. Solution Overview
Overview.
environment_fixture
## 2. Parts List
Just some text here, no list or table.
## 3. Assembly Strategy
1. Step
## 4. Assumption Register
- Assumption: The planner relies on source-backed inputs that must be traceable.

## 5. Detailed Calculations
| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Example calculation supporting the plan | `N/A` | Replace this placeholder with the actual derived limit. |

### CALC-001: Example calculation supporting the plan

#### Problem Statement

The plan needs a traceable calculation instead of a freeform claim.

#### Assumptions

- `ASSUMP-001`: The input values are taken from the benchmark or assembly definition.

#### Derivation

- Compute the binding quantity from the declared inputs.

#### Worst-Case Check

- The derived limit must hold under the worst-case allowed inputs.

#### Result

- The design remains valid only if the derived limit is respected.

#### Design Impact

- Update the design or inputs if the calculation changes.

#### Cross-References

        - `engineering_plan.md#3-assembly-strategy`

## 6. Critical Constraints / Operating Envelope
- Constraint: The mechanism must remain inside the derived operating limits.

## 7. Cost & Weight Budget
- Cost: 0
## 8. Risk Assessment
- Risk: None
"""
        await setup_workspace(
            client, base_headers, {**base_files, "engineering_plan.md": invalid_plan}
        )
        await _validate_solution_script(
            client,
            base_headers,
            "solution.py",
            reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        sim_data = await _seed_successful_simulation_result(
            client, base_headers, "solution.py"
        )
        assert sim_data.success, sim_data.message
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "Parts List must contain a bullet list or table" in data.message

        # 3. Detailed Calculations uses the wrong table schema
        invalid_plan = """## 1. Solution Overview
Overview.
environment_fixture
## 2. Parts List
| Part | Qty |
|------|-----|
| environment_fixture | 1 |
## 3. Assembly Strategy
1. Step
## 4. Assumption Register
- Assumption: The planner relies on source-backed inputs that must be traceable.

## 5. Detailed Calculations
| Check | Calculation | Result |
| -- | -- | -- |
| Capture envelope | `entry_funnel` top opening exceeds the narrow throat by 90 mm. | Pass |

### CALC-001: Capture envelope margin
#### Problem Statement
The capture opening must exceed the throat.
#### Assumptions
- `ASSUMP-001`: The throat width is fixed.
#### Derivation
- Capture margin is measured from the openings.
#### Worst-Case Check
- Minimum clearance remains positive.
#### Result
- Pass
#### Design Impact
- Ramp geometry must remain wider than the throat.
#### Cross-References
        - `engineering_plan.md#3-assembly-strategy`

## 6. Critical Constraints / Operating Envelope
- Constraint: The mechanism must remain inside the derived operating limits.

## 7. Cost & Weight Budget
- Cost: 0
## 8. Risk Assessment
- Risk: None
"""
        await setup_workspace(
            client, base_headers, {**base_files, "engineering_plan.md": invalid_plan}
        )
        await _validate_solution_script(
            client,
            base_headers,
            "solution.py",
            reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        sim_data = await _seed_successful_simulation_result(
            client, base_headers, "solution.py"
        )
        assert sim_data.success, sim_data.message
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "Detailed Calculations must use the exact summary table" in data.message

        # 4. Detailed Calculations uses the wrong subsection heading form
        invalid_plan = """## 1. Solution Overview
Overview.
environment_fixture
## 2. Parts List
| Part | Qty |
|------|-----|
| environment_fixture | 1 |
## 3. Assembly Strategy
1. Step
## 4. Assumption Register
- Assumption: The planner relies on source-backed inputs that must be traceable.

## 5. Detailed Calculations
| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Capture envelope margin | Pass | Ramp geometry must remain wider than the throat. |

### CALC-001 Capture envelope margin
#### Problem Statement
The capture opening must exceed the throat.
#### Assumptions
- `ASSUMP-001`: The throat width is fixed.
#### Derivation
- Capture margin is measured from the openings.
#### Worst-Case Check
- Minimum clearance remains positive.
#### Result
- Pass
#### Design Impact
- Ramp geometry must remain wider than the throat.
#### Cross-References
        - `engineering_plan.md#3-assembly-strategy`

## 6. Critical Constraints / Operating Envelope
- Constraint: The mechanism must remain inside the derived operating limits.

## 7. Cost & Weight Budget
- Cost: 0
## 8. Risk Assessment
- Risk: None
"""
        await setup_workspace(
            client, base_headers, {**base_files, "engineering_plan.md": invalid_plan}
        )
        await _validate_solution_script(
            client,
            base_headers,
            "solution.py",
            reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        sim_data = await _seed_successful_simulation_result(
            client, base_headers, "solution.py"
        )
        assert sim_data.success, sim_data.message
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert (
            "Detailed Calculations subsection headings must use the exact"
            in data.message
        )

        # 5. Detailed Calculations strict schema still accepts the intended shape
        valid_strict_plan = """## 1. Solution Overview
Overview.
environment_fixture
## 2. Parts List
| Part | Qty |
|------|-----|
| environment_fixture | 1 |
## 3. Assembly Strategy
1. Step
## 4. Assumption Register
- Assumption: The planner relies on source-backed inputs that must be traceable.

## 5. Detailed Calculations
| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Minimum slope needed to move cube under worst-case friction | `21.7deg` | Ramp angle must be updated or assumptions must change. |

### CALC-001: Minimum slope needed to move cube
#### Problem Statement
The cube must slide reliably under the declared surface/friction assumptions.
#### Assumptions
- `ASSUMP-001`: The surface friction coefficient is taken from the benchmark definition.
#### Derivation
- The minimum slope is computed from the worst-case static friction threshold.
#### Worst-Case Check
- The threshold remains satisfied only when the slope is at least `21.7deg`.
#### Result
- The cube slides.
#### Design Impact
- The ramp angle must be updated or the assumptions must change.
#### Cross-References
        - `engineering_plan.md#3-assembly-strategy`

## 6. Critical Constraints / Operating Envelope
- Constraint: The mechanism must remain inside the derived operating limits.

## 7. Cost & Weight Budget
- Cost: 0
## 8. Risk Assessment
- Risk: None
"""
        matching_script = minimal_script.replace("test_part", "environment_fixture")
        await setup_workspace(
            client,
            base_headers,
            {
                **base_files,
                "engineering_plan.md": valid_strict_plan,
                "solution.py": matching_script,
            },
        )
        validate_req = BenchmarkToolRequest(
            script_path="solution.py",
            reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        validate_resp = await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=validate_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(validate_resp.json())
        assert data.success is True
        sim_data = await _seed_successful_simulation_result(
            client, base_headers, "solution.py"
        )
        assert sim_data.success, sim_data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors("todo_md_invalid")
@pytest.mark.xdist_group(name="physics_sims")
@pytest.mark.asyncio
@pytest.mark.int_id("INT-007")
async def test_int_007_todo_integrity(
    session_id, base_headers, valid_plan, valid_objectives, valid_cost, minimal_script
):
    """INT-007: Verify todo.md integrity (all items completed or skipped)."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        base_files = {
            "benchmark_plan.md": valid_plan,
            "benchmark_definition.yaml": valid_objectives,
            "benchmark_assembly_definition.yaml": valid_cost,
            "solution.py": minimal_script,
        }

        # 1. Invalid checkbox format
        invalid_todo = "- [?] What is this?"
        await setup_workspace(
            client, base_headers, {**base_files, "todo.md": invalid_todo}
        )
        submit_req = BenchmarkToolRequest(
            script_path="solution.py", reviewer_stage=AgentName.BENCHMARK_REVIEWER
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "todo.md invalid" in data.message
        assert "invalid checkbox" in data.message

        # 2. Uncompleted item at submission
        uncompleted_todo = "- [ ] I forgot to finish this"
        await setup_workspace(
            client, base_headers, {**base_files, "todo.md": uncompleted_todo}
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "must be completed or skipped" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.xdist_group(name="physics_sims")
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_objectives_validation(
    session_id,
    base_headers,
    valid_plan,
    valid_todo,
    valid_cost,
    minimal_script,
    valid_objectives,
):
    """INT-008: Verify benchmark_definition.yaml schema and template detection."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        matching_script = minimal_script.replace("test_part", "environment_fixture")
        base_files = {
            "benchmark_plan.md": valid_plan,
            "todo.md": valid_todo,
            "benchmark_assembly_definition.yaml": valid_cost,
            "solution.py": matching_script,
        }

        # 1. Template placeholders present (e.g., x_min)
        template_content = dump_yaml_model(valid_objectives).replace(
            "    min_mm:\n    - 10.0\n    - 10.0\n    - 10.0",
            "    min_mm:\n    - x_min\n    - y_min\n    - z_min",
        )
        await setup_workspace(
            client,
            base_headers,
            {**base_files, "benchmark_definition.yaml": template_content},
        )
        await _validate_solution_script(
            client,
            base_headers,
            "solution.py",
            reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        submit_req = BenchmarkToolRequest(
            script_path="solution.py", reviewer_stage=AgentName.BENCHMARK_REVIEWER
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "template placeholders" in data.message

        # 2. Schema violation (wrong type)
        invalid_obj = dump_yaml_model(valid_objectives).replace(
            "    min_mm:\n    - 10.0\n    - 10.0\n    - 10.0",
            "    min_mm: not_a_list",
        )
        await setup_workspace(
            client,
            base_headers,
            {**base_files, "benchmark_definition.yaml": invalid_obj},
        )
        await _validate_solution_script(client, base_headers, "solution.py")
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "benchmark_definition.yaml invalid" in data.message

        # 3. Blank payload label must fail closed.
        blank_label_obj = valid_objectives.model_copy(deep=True)
        blank_label_obj.payload.label = ""
        await setup_workspace(
            client,
            base_headers,
            {**base_files, "benchmark_definition.yaml": blank_label_obj},
        )
        await _validate_solution_script(client, base_headers, "solution.py")
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "benchmark_definition.yaml invalid" in data.message
        assert "label must be a non-empty string" in data.message

        # 4. Authored labels must not occupy the payload namespace.
        reserved_label_script = """
from build123d import *
from shared.models.schemas import PartMetadata
def build():
    p = Box(10, 10, 10)
    p.label = "benchmark_payload__oops"
    p.metadata = PartMetadata(material_id="aluminum-6061")
    return p
"""
        await setup_workspace(
            client,
            base_headers,
            {
                **base_files,
                "benchmark_definition.yaml": valid_objectives,
                "solution.py": reserved_label_script,
            },
        )
        resp = await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                backend=selected_backend(),
            ).model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "Top-level part labels may not start with" in data.message
        assert "benchmark_payload__" in data.message

        # 5. Unknown extra fields must fail closed (top-level and nested)
        extra_obj = valid_objectives.model_dump(mode="json")
        extra_obj["unknown_top_level"] = "forbidden"
        extra_obj["objectives"]["goal_zone_mm"]["unexpected_key"] = 123
        await setup_workspace(
            client,
            base_headers,
            {**base_files, "benchmark_definition.yaml": extra_obj},
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "benchmark_definition.yaml invalid" in data.message
        assert "extra inputs are not permitted" in data.message.lower()


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_assembly_definition_yaml_invalid",
        "cost_estimation_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-009")
async def test_int_009_cost_estimation_validation(
    session_id,
    base_headers,
    valid_plan,
    valid_todo,
    valid_objectives,
    valid_cost,
    minimal_script,
):
    """INT-009: Verify benchmark_assembly_definition.yaml schema and placeholders."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        matching_script = minimal_script.replace("test_part", "environment_fixture")
        base_files = {
            "benchmark_plan.md": valid_plan,
            "todo.md": valid_todo,
            "benchmark_definition.yaml": valid_objectives,
            "manufacturing_config.yaml": REPO_MANUFACTURING_CONFIG,
            "solution.py": matching_script,
        }

        # 1. Template placeholders ([implement here])
        template_cost = "version: '1.0'\ntotals:\n  estimated_unit_cost_usd: 10.0\n  note: [implement here]"
        await setup_workspace(
            client,
            base_headers,
            {**base_files, "benchmark_assembly_definition.yaml": template_cost},
        )
        await _validate_solution_script(client, base_headers, "solution.py")
        submit_req = BenchmarkToolRequest(
            script_path="solution.py", reviewer_stage=AgentName.BENCHMARK_REVIEWER
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "template placeholders" in data.message

        # 2. Schema violation (missing required field)
        invalid_cost = valid_cost.model_dump(mode="json")
        invalid_cost["totals"] = {}
        await setup_workspace(
            client,
            base_headers,
            {**base_files, "benchmark_assembly_definition.yaml": invalid_cost},
        )
        await _validate_solution_script(client, base_headers, "solution.py")
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "benchmark_assembly_definition.yaml invalid" in data.message

        # 3. Unknown extra fields must fail closed (top-level and nested)
        extra_cost = valid_cost.model_dump(mode="json")
        extra_cost["constraints"]["unknown_constraint_key"] = True
        extra_cost["unknown_top_level"] = "forbidden"
        await setup_workspace(
            client,
            base_headers,
            {**base_files, "benchmark_assembly_definition.yaml": extra_cost},
        )
        await _validate_solution_script(client, base_headers, "solution.py")
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "benchmark_assembly_definition.yaml invalid" in data.message
        assert "extra inputs are not permitted" in data.message.lower()


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_assembly_definition_yaml_invalid",
        "cost_estimation_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-011")
async def test_int_011_planner_caps_enforcement(
    session_id, base_headers, valid_plan, valid_todo, valid_objectives, minimal_script
):
    """INT-011: Verify handoff blockage when planner caps exceed benchmark limits."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # Keep invalid payload as raw data so schema validation happens in the endpoint path.
        invalid_cost = valid_cost.model_dump(mode="json")
        invalid_cost["constraints"]["planner_target_max_unit_cost_usd"] = 60.0
        invalid_cost["totals"]["estimated_unit_cost_usd"] = 40.0
        invalid_cost["totals"]["estimated_weight_g"] = 200.0
        invalid_cost["totals"]["estimate_confidence"] = "medium"
        files = {
            "benchmark_plan.md": valid_plan,
            "todo.md": valid_todo,
            "benchmark_definition.yaml": valid_objectives,
            "benchmark_assembly_definition.yaml": invalid_cost,
            "manufacturing_config.yaml": REPO_MANUFACTURING_CONFIG,
            "solution.py": minimal_script,
        }
        await setup_workspace(client, base_headers, files)
        # Record validation
        val_req = BenchmarkToolRequest(
            script_path="solution.py", reviewer_stage=AgentName.BENCHMARK_REVIEWER
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=val_req.model_dump(mode="json"),
            headers=base_headers,
        )
        sim_data = await _seed_successful_simulation_result(
            client, base_headers, "solution.py"
        )
        assert sim_data.success, sim_data.message

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=val_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "benchmark_assembly_definition.yaml invalid" in data.message
        assert (
            "Planner target cost (60.0) must be less than or equal to benchmark max cost (50.0)"
            in data.message
        )


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=["immutability_violation", "benchmark_definition_yaml_modified"]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-015")
async def test_int_015_engineer_handover_immutability(
    session_id,
    base_headers,
    valid_plan,
    valid_todo,
    valid_objectives,
    valid_cost,
    minimal_script,
):
    """INT-015: Verify immutability of benchmark_definition.yaml during handover."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        await client.post(f"{WORKER_LIGHT_URL}/git/init", headers=base_headers)

        matching_plan = valid_plan.replace(
            "| Box  | 1   |", "| environment_fixture | 1   |"
        )
        matching_cost = valid_cost.model_copy(deep=True)
        matching_cost.totals.estimated_unit_cost_usd = 0.0
        matching_cost.totals.estimated_weight_g = 0.0
        files = {
            "benchmark_plan.md": matching_plan,
            "todo.md": valid_todo,
            "benchmark_definition.yaml": valid_objectives,
            "benchmark_assembly_definition.yaml": matching_cost,
            "solution.py": minimal_script.replace("test_part", "environment_fixture"),
        }
        await setup_workspace(client, base_headers, files)

        # Baseline commit
        from shared.workers.schema import GitCommitRequest

        commit_req = GitCommitRequest(message="Initial benchmark")
        await client.post(
            f"{WORKER_LIGHT_URL}/git/commit",
            json=commit_req.model_dump(mode="json"),
            headers=base_headers,
        )

        # Cheat: modify benchmark_definition.yaml
        modified_objectives = valid_objectives.model_copy(deep=True)
        modified_objectives.randomization.runtime_jitter_enabled = False
        await setup_workspace(
            client, base_headers, {"benchmark_definition.yaml": modified_objectives}
        )
        # Record validation
        val_req = BenchmarkToolRequest(
            script_path="solution.py", reviewer_stage=AgentName.BENCHMARK_REVIEWER
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=val_req.model_dump(mode="json"),
            headers=base_headers,
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=val_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert not data.success
        assert "benchmark_definition.yaml violation" in data.message
        assert "has been modified" in data.message


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-019")
async def test_int_019_hard_constraints_gates(
    session_id, base_headers, valid_plan, valid_todo, valid_objectives, valid_cost
):
    """INT-019: benchmark submit should not enforce engineering cost/weight caps."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # Keep geometry valid/simulatable and use very tight caps that would fail
        # engineering submit; benchmark submit must still pass.
        expensive_script = """
from build123d import *
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod
def build():
    p = Box(10, 10, 10).translate((15, 15, 15))
    p.label = "ball"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC, material_id="aluminum-6061"
    )
    return p
"""
        tight_objectives = valid_objectives.model_copy(deep=True)
        tight_objectives.constraints.max_unit_cost = 0.01
        tight_objectives.constraints.max_weight_g = 0.1
        tight_cost = valid_cost.model_copy(deep=True)
        tight_cost.constraints.benchmark_max_unit_cost_usd = 0.01
        tight_cost.constraints.benchmark_max_weight_g = 0.1
        tight_cost.constraints.planner_target_max_unit_cost_usd = 0.01
        tight_cost.constraints.planner_target_max_weight_g = 0.1
        tight_cost.totals.estimated_unit_cost_usd = 0.0
        tight_cost.totals.estimated_weight_g = 0.0
        files = {
            "benchmark_plan.md": valid_plan,
            "todo.md": valid_todo,
            "benchmark_definition.yaml": tight_objectives,
            "benchmark_assembly_definition.yaml": tight_cost,
            "manufacturing_config.yaml": REPO_MANUFACTURING_CONFIG,
            "script.py": expensive_script,
        }
        await setup_workspace(client, base_headers, files)

        val_req = BenchmarkToolRequest(
            script_path="script.py", reviewer_stage=AgentName.BENCHMARK_REVIEWER
        )
        val_resp = await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=val_req.model_dump(mode="json"),
            headers=base_headers,
        )
        assert val_resp.status_code == 200, val_resp.text
        val_data = BenchmarkToolResponse.model_validate(val_resp.json())
        assert val_data.success, val_data.message

        sim_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json=val_req.model_dump(mode="json"),
            headers=base_headers,
            timeout=1000.0,
        )
        assert sim_resp.status_code == 200, sim_resp.text
        sim_data = BenchmarkToolResponse.model_validate(sim_resp.json())
        assert sim_data.success, sim_data.message

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=val_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.success, data.message
        assert data.artifacts is not None
        benchmark_manifest = data.artifacts.review_manifests_json.get(
            ".manifests/benchmark_review_manifest.json"
        )
        assert benchmark_manifest is not None
        parsed_manifest = json.loads(benchmark_manifest)
        assert (
            parsed_manifest.get("reviewer_stage") == AgentName.BENCHMARK_REVIEWER.value
        )


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_assembly_definition_yaml_invalid",
        "cost_estimation_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-010")
async def test_int_010_planner_pricing_script_integration(
    session_id, base_headers, valid_plan, valid_todo, valid_objectives, minimal_script
):
    """INT-010: Verify validate_costing_and_price block when over caps."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # Keep the payload invalid, but derive it from the typed schema first.
        invalid_cost = AssemblyDefinition(
            version="1.0",
            constraints=AssemblyConstraints(
                benchmark_max_unit_cost_usd=50.0,
                benchmark_max_weight_g=1000.0,
                planner_target_max_unit_cost_usd=45.0,
                planner_target_max_weight_g=900.0,
            ),
            manufactured_parts=[],
            final_assembly=[],
            totals=CostTotals(
                estimated_unit_cost_usd=0.0,
                estimated_weight_g=0.0,
                estimate_confidence="high",
            ),
        ).model_dump(mode="json")
        invalid_cost["totals"]["estimated_unit_cost_usd"] = 55.0
        files = {
            "benchmark_plan.md": valid_plan,
            "todo.md": valid_todo,
            "benchmark_definition.yaml": valid_objectives,
            "benchmark_assembly_definition.yaml": invalid_cost,
            "manufacturing_config.yaml": REPO_MANUFACTURING_CONFIG,
            "solution.py": minimal_script,
        }
        await setup_workspace(client, base_headers, files)
        # Record validation
        val_req = BenchmarkToolRequest(
            script_path="solution.py", reviewer_stage=AgentName.BENCHMARK_REVIEWER
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=val_req.model_dump(mode="json"),
            headers=base_headers,
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=val_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert not data.success
        assert "benchmark_assembly_definition.yaml invalid" in data.message
        assert "exceeds target" in data.message.lower()


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "submission_cost_limit_exceeded",
        "requested quantity 1",
        "Unit cost at requested quantity",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-010")
async def test_int_010_handoff_rejects_low_quantity_that_only_passes_at_volume(
    session_id, base_headers, valid_plan, valid_todo, valid_objectives
):
    """INT-010: the handoff gate must evaluate manufacturability at the requested quantity."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        objectives = valid_objectives.model_copy(deep=True)
        objectives.constraints.target_quantity = 1
        objectives.constraints.max_unit_cost = 40.0
        objectives.constraints.max_weight_g = 1000.0

        assembly_definition = AssemblyDefinition(
            version="1.0",
            constraints=AssemblyConstraints(
                benchmark_max_unit_cost_usd=40.0,
                benchmark_max_weight_g=1000.0,
                planner_target_max_unit_cost_usd=35.0,
                planner_target_max_weight_g=900.0,
            ),
            manufactured_parts=[
                ManufacturedPartEstimate(
                    part_name="qty_probe",
                    part_id="qty_probe",
                    manufacturing_method=ManufacturingMethod.CNC,
                    material_id="aluminum_6061",
                    quantity=1,
                    part_volume_mm3=1000.0,
                    stock_bbox_mm={"x": 10.0, "y": 10.0, "z": 10.0},
                    stock_volume_mm3=1000.0,
                    removed_volume_mm3=0.0,
                    estimated_unit_cost_usd=35.0,
                )
            ],
            final_assembly=[PartConfig(name="qty_probe")],
            totals=CostTotals(
                estimated_unit_cost_usd=35.0,
                estimated_weight_g=2.7,
                estimate_confidence="high",
            ),
        )
        script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    part = Box(10, 10, 10)
    part = part.move(Location((0, 0, 5)))
    part.label = "qty_probe"
    part.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum_6061",
    )
    return part
"""

        await setup_workspace(
            client,
            base_headers,
            {
                "benchmark_plan.md": valid_plan,
                "todo.md": valid_todo,
                "benchmark_definition.yaml": objectives,
                "assembly_definition.yaml": assembly_definition,
                "manufacturing_config.yaml": REPO_MANUFACTURING_CONFIG,
                "script.py": script,
            },
        )

        exec_resp = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code=(
                    "python "
                    "/home/maksym/Work/proj/Problemologist/Problemologist-AI/"
                    ".agents/skills/manufacturing-knowledge/scripts/validate_and_price.py"
                ),
                timeout=60,
            ).model_dump(mode="json"),
            headers=base_headers,
        )
        assert exec_resp.status_code == 200, exec_resp.text
        exec_data = ExecuteResponse.model_validate(exec_resp.json())
        assert exec_data.exit_code == 0, exec_data.stderr

        submit_req = BenchmarkToolRequest(
            script_path="script.py",
            reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        validate_resp = await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        assert validate_resp.status_code == 200, validate_resp.text
        validate_data = BenchmarkToolResponse.model_validate(validate_resp.json())
        assert validate_data.success, validate_data.message

        simulate_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        assert simulate_resp.status_code == 200, simulate_resp.text
        simulate_data = BenchmarkToolResponse.model_validate(simulate_resp.json())
        assert simulate_data.success, simulate_data.message

        submit_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        assert submit_resp.status_code == 200, submit_resp.text
        submit_data = BenchmarkToolResponse.model_validate(submit_resp.json())

    assert submit_data.success is False
    assert "Unit cost at requested quantity 1" in submit_data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "prior_validation_missing",
        "prior_validation_stale_for_script",
        "prior_simulation_missing",
        "goal_not_reached_in_simulation",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-018")
async def test_int_018_validate_and_price_integration_gate(
    session_id,
    base_headers,
    valid_plan,
    valid_todo,
    valid_objectives,
    valid_cost,
    minimal_script,
):
    """INT-018: Verify submit_for_review gate requires validation + simulation on latest revision."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        relaxed_objectives = valid_objectives.model_copy(deep=True)
        relaxed_objectives.constraints.max_unit_cost = 500.0
        relaxed_objectives.constraints.max_weight_g = 10000.0
        matching_plan = valid_plan.replace(
            "| Box  | 1   |", "| environment_fixture | 1   |"
        )
        matching_cost = valid_cost.model_copy(deep=True)
        matching_cost.constraints.benchmark_max_unit_cost_usd = 500.0
        matching_cost.constraints.benchmark_max_weight_g = 10000.0
        matching_cost.totals.estimated_unit_cost_usd = 0.0
        matching_cost.totals.estimated_weight_g = 0.0

        goal_script = """
from build123d import *
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod
def build():
    p = Box(1, 1, 1).translate((15, 15, 15))
    p.label = "environment_fixture"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC, material_id="aluminum-6061"
    )
    return p
"""

        files = {
            "benchmark_plan.md": matching_plan,
            "todo.md": valid_todo,
            "benchmark_definition.yaml": relaxed_objectives,
            "benchmark_assembly_definition.yaml": matching_cost,
            "manufacturing_config.yaml": REPO_MANUFACTURING_CONFIG,
            "script.py": goal_script,
        }
        await setup_workspace(client, base_headers, files)

        # 1) Missing validation gate must fail closed.
        delete_req = DeleteFileRequest(path="validation_results.json")
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/delete",
            json=delete_req.model_dump(mode="json"),
            headers=base_headers,
        )

        submit_req = BenchmarkToolRequest(
            script_path="script.py", reviewer_stage=AgentName.BENCHMARK_REVIEWER
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert not data.success
        assert "validation" in data.message.lower()

        # 2) Validation present but simulation missing must fail closed.
        val_resp = await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        assert val_resp.status_code == 200, val_resp.text
        val_data = BenchmarkToolResponse.model_validate(val_resp.json())
        assert val_data.success, val_data.message

        delete_sim_req = DeleteFileRequest(path="simulation_result.json")
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/delete",
            json=delete_sim_req.model_dump(mode="json"),
            headers=base_headers,
        )
        missing_sim_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        missing_sim_data = BenchmarkToolResponse.model_validate(missing_sim_resp.json())
        assert not missing_sim_data.success
        assert "simulation" in missing_sim_data.message.lower()

        # 3) Latest revision enforcement must fail when script changed after gates.
        sim_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
            timeout=1000.0,
        )
        assert sim_resp.status_code == 200, sim_resp.text
        sim_data = BenchmarkToolResponse.model_validate(sim_resp.json())
        assert sim_data.success, sim_data.message

        stale_script = """
from build123d import *
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod
def build():
    p = Box(1, 1, 1).translate((0, 0, 5))
    p.label = "ball"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC, material_id="aluminum-6061"
    )
    return p
"""
        await setup_workspace(client, base_headers, {"script.py": stale_script})
        stale_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        stale_data = BenchmarkToolResponse.model_validate(stale_resp.json())
        assert not stale_data.success
        assert (
            "stale" in stale_data.message.lower()
            or "re-run validate" in stale_data.message.lower()
            or "re-run simulate" in stale_data.message.lower()
        )

        # 4) Happy path: validate + simulate + submit on latest revision succeeds.
        await setup_workspace(client, base_headers, {"script.py": goal_script})
        val_resp = await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        assert val_resp.status_code == 200, val_resp.text
        val_data = BenchmarkToolResponse.model_validate(val_resp.json())
        assert val_data.success, val_data.message

        sim_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
            timeout=1000.0,
        )
        assert sim_resp.status_code == 200, sim_resp.text
        sim_data = BenchmarkToolResponse.model_validate(sim_resp.json())
        assert sim_data.success, sim_data.message
        assert (
            "goal achieved" in sim_data.message.lower()
            or "goal zone" in sim_data.message.lower()
            or "green zone" in sim_data.message.lower()
        ), sim_data.message

        ok_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=submit_req.model_dump(mode="json"),
            headers=base_headers,
        )
        ok_data = BenchmarkToolResponse.model_validate(ok_resp.json())
        assert ok_data.success, ok_data.message
