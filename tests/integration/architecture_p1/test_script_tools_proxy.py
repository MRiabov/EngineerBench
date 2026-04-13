import asyncio
import base64
import json
import uuid
from pathlib import Path

import httpx
import pytest
import yaml
from websockets.asyncio.client import connect as websocket_connect

from controller.api.schemas import AgentRunRequest, EpisodeCreateResponse
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName
from shared.models.schemas import (
    AssemblyConstraints,
    AssemblyDefinition,
    BenchmarkDefinition,
    BoundingBox,
    Constraints,
    CostTotals,
    DraftingCallout,
    DraftingDimension,
    DraftingSheet,
    DraftingView,
    MovedObject,
    ObjectivesSection,
)
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.schema import (
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    ExecuteRequest,
    ExecuteResponse,
    ListFilesRequest,
    PreviewDesignResponse,
    ReadFileRequest,
    ReadFilesRequest,
    RenderManifest,
    WriteFileRequest,
)

CONTROLLER_URL = "http://127.0.0.1:18000"
WORKER_LIGHT_URL = "http://127.0.0.1:18001"
WORKER_HEAVY_URL = "http://127.0.0.1:18002"
ENGINEER_PLANNER_FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "mock_responses"
    / "INT-033"
    / "engineer_planner"
    / "entry_01"
)

pytestmark = pytest.mark.xdist_group(name="physics_sims")

_BUSY_SLEEP_SECONDS = 8


def _benchmark_definition() -> BenchmarkDefinition:
    return BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone=BoundingBox(min=(-2.0, -2.0, 0.0), max=(2.0, 2.0, 10.0)),
            forbid_zones=[],
            build_zone=BoundingBox(min=(-20.0, -20.0, 0.0), max=(20.0, 20.0, 30.0)),
        ),
        benchmark_parts=[
            {
                "part_id": "environment_fixture",
                "label": "environment_fixture",
                "metadata": {
                    "fixed": True,
                    "material_id": "aluminum_6061",
                },
            }
        ],
        simulation_bounds=BoundingBox(
            min=(-50.0, -50.0, -10.0), max=(50.0, 50.0, 50.0)
        ),
        payload=MovedObject(
            label="target_box",
            shape="sphere",
            material_id="aluminum_6061",
            start_position=(0.0, 0.0, 4.0),
            runtime_jitter=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
    )


def _benchmark_assembly_definition() -> AssemblyDefinition:
    return AssemblyDefinition(
        constraints=AssemblyConstraints(
            benchmark_max_unit_cost_usd=100.0,
            benchmark_max_weight_g=1000.0,
            planner_target_max_unit_cost_usd=90.0,
            planner_target_max_weight_g=900.0,
        ),
        totals=CostTotals(
            estimated_unit_cost_usd=10.0,
            estimated_weight_g=100.0,
            estimate_confidence="high",
        ),
    )


def _plan_markdown() -> str:
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

- `plan.md#3-assembly-strategy`

## 6. Critical Constraints / Operating Envelope
- Constraint: The mechanism must remain inside the derived operating limits.

## 7. Cost & Weight Budget
- Cost: $10
- Weight: 100g

## 8. Risk Assessment
- Risk: Low
"""


def _todo_markdown() -> str:
    return "- [x] Step 1\n- [-] Step 2\n"


def _sleeping_script() -> str:
    return """
from build123d import Location, Sphere
from shared.models.schemas import PartMetadata


def build():
    part = Sphere(1.0).move(Location((0, 0, 4)))
    part.label = "target_box"
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=False)
    return part
"""


def _preview_solution_script() -> str:
    return """
from build123d import Align, Box
from shared.models.schemas import PartMetadata


def build():
    part = Box(2.0, 2.0, 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part.label = "preview_helper_box"
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=False)
    return part


result = build()
"""


def _preview_probe_script() -> str:
    return """
from solution_script import result
from utils import preview


response = preview(
    result,
    orbit_pitch=-35.0,
    orbit_yaw=45.0,
    rendering_type="depth",
)
print(f"PREVIEW_SUCCESS={response.success}")
print(f"PREVIEW_STATUS={response.status_text}")
print(f"PREVIEW_MESSAGE={response.message}")
print(f"PREVIEW_RENDERING_TYPE={response.rendering_type.value}")
print(f"PREVIEW_ARTIFACT_PATH={response.artifact_path}")
print(f"PREVIEW_MANIFEST_PATH={response.manifest_path}")
print(f"PREVIEW_PITCH={response.pitch}")
print(f"PREVIEW_YAW={response.yaw}")
"""


def _manifest_path_for_artifact(artifact_path: str) -> str:
    return str(Path(artifact_path).parent / "render_manifest.json")


def _engineer_planner_goal_overlap_benchmark_definition_yaml() -> str:
    data = yaml.safe_load(
        (ENGINEER_PLANNER_FIXTURE_DIR / "04__benchmark_definition.yaml").read_text()
    )
    data["objectives"]["goal_zone"] = {
        "min": [-2.0, -2.0, 0.0],
        "max": [2.0, 2.0, 4.0],
    }
    data["payload"]["start_position"] = [8.0, 8.0, 8.0]
    return yaml.safe_dump(data, sort_keys=False)


def _engineer_planner_assembly_definition_yaml(*, allow_goal_zone_overlap: bool) -> str:
    data = yaml.safe_load(
        (ENGINEER_PLANNER_FIXTURE_DIR / "03__assembly_definition.yaml").read_text()
    )
    drafting = data.setdefault("drafting", {})
    if allow_goal_zone_overlap:
        drafting["goal_zone_overlap_intents"] = [
            {"zone_name": "goal_zone", "target": "solution_plan_evidence"}
        ]
        data["final_assembly"] = [
            {"name": "solution_plan_evidence", "config": {"dofs": []}}
        ]
    else:
        drafting.pop("goal_zone_overlap_intents", None)
    return yaml.safe_dump(data, sort_keys=False)


async def _write_engineer_planner_drafting_workspace(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    allow_goal_zone_overlap: bool = False,
) -> None:
    headers = {"X-Session-ID": session_id}

    workspace_files = {
        ".manifests/current_role.json": current_role_manifest_json(
            AgentName.ENGINEER_PLANNER
        ),
        "plan.md": (ENGINEER_PLANNER_FIXTURE_DIR / "01__plan.md").read_text(),
        "todo.md": (ENGINEER_PLANNER_FIXTURE_DIR / "02__todo.md").read_text(),
        "assembly_definition.yaml": _engineer_planner_assembly_definition_yaml(
            allow_goal_zone_overlap=allow_goal_zone_overlap
        ),
        "benchmark_definition.yaml": _engineer_planner_goal_overlap_benchmark_definition_yaml(),
        "solution_plan_evidence_script.py": (
            ENGINEER_PLANNER_FIXTURE_DIR / "05__solution_plan_evidence_script.py"
        ).read_text(),
        "solution_plan_technical_drawing_script.py": (
            ENGINEER_PLANNER_FIXTURE_DIR
            / "06__solution_plan_technical_drawing_script.py"
        ).read_text(),
    }

    for path, content in workspace_files.items():
        resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path=path,
                content=content,
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text


def _multi_view_preview_probe_script() -> str:
    return """
from solution_script import result
from utils import preview


valid = preview(
    result,
    orbit_pitch=[-35.0, -15.0],
    orbit_yaw=[45.0, 60.0],
    rendering_type="depth",
)
print(f"MULTI_SUCCESS={valid.success}")
print(f"MULTI_VIEW_COUNT={valid.view_count}")
print(f"MULTI_VIEW_SPECS={len(valid.view_specs)}")
print(f"MULTI_ARTIFACT_PATH={valid.artifact_path}")

mismatch = preview(
    result,
    orbit_pitch=[-35.0, -15.0],
    orbit_yaw=[45.0, 60.0, 75.0],
    rendering_type="depth",
)
print(f"MISMATCH_SUCCESS={mismatch.success}")
print(f"MISMATCH_MESSAGE={mismatch.message}")

over_cap = preview(
    result,
    orbit_pitch=list(range(65)),
    orbit_yaw=list(range(65)),
    rendering_type="depth",
)
print(f"CAP_SUCCESS={over_cap.success}")
print(f"CAP_MESSAGE={over_cap.message}")
"""


def _benchmark_drafting_script() -> str:
    return """
from build123d import Align, Box
from shared.models.schemas import PartMetadata


def build():
    part = Box(2.0, 2.0, 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part.label = "benchmark_preview_box"
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=False)
    return part


result = build()
"""


def _benchmark_drafting_probe_script() -> str:
    return """
from benchmark_plan_technical_drawing_script import result
from utils import render_technical_drawing


response = render_technical_drawing(
    result,
    orbit_pitch=-35.0,
    orbit_yaw=45.0,
)
print(f"PREVIEW_DRAWING_SUCCESS={response.success}")
print(f"PREVIEW_DRAWING_STATUS={response.status_text}")
print(f"PREVIEW_DRAWING_MESSAGE={response.message}")
print(f"PREVIEW_DRAWING_RENDERING_TYPE={response.rendering_type.value}")
print(f"PREVIEW_DRAWING_DRAFTING={response.drafting}")
print(f"PREVIEW_DRAWING_ARTIFACT_PATH={response.artifact_path}")
print(f"PREVIEW_DRAWING_MANIFEST_PATH={response.manifest_path}")
"""


async def _write_session_workspace(
    client: httpx.AsyncClient, session_id: str, script_path: str
) -> None:
    headers = {"X-Session-ID": session_id}
    script_resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path=script_path,
            content=_sleeping_script(),
            overwrite=True,
        ).model_dump(mode="json"),
        headers=headers,
    )
    assert script_resp.status_code == 200, script_resp.text

    objectives_resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path="benchmark_definition.yaml",
            content=yaml.safe_dump(
                _benchmark_definition().model_dump(mode="json"), sort_keys=False
            ),
            overwrite=True,
        ).model_dump(mode="json"),
        headers=headers,
    )
    assert objectives_resp.status_code == 200, objectives_resp.text

    plan_resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path="plan.md",
            content=_plan_markdown(),
            overwrite=True,
        ).model_dump(mode="json"),
        headers=headers,
    )
    assert plan_resp.status_code == 200, plan_resp.text

    todo_resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path="todo.md",
            content=_todo_markdown(),
            overwrite=True,
        ).model_dump(mode="json"),
        headers=headers,
    )
    assert todo_resp.status_code == 200, todo_resp.text

    assembly_resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path="benchmark_assembly_definition.yaml",
            content=yaml.safe_dump(
                _benchmark_assembly_definition().model_dump(mode="json"),
                sort_keys=False,
            ),
            overwrite=True,
        ).model_dump(mode="json"),
        headers=headers,
    )
    assert assembly_resp.status_code == 200, assembly_resp.text


async def _write_preview_workspace(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    include_assembly_definition: bool = True,
) -> None:
    headers = {"X-Session-ID": session_id}

    current_role_resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path=".manifests/current_role.json",
            content=current_role_manifest_json(AgentName.ENGINEER_CODER),
            overwrite=True,
        ).model_dump(mode="json"),
        headers=headers,
    )
    assert current_role_resp.status_code == 200, current_role_resp.text

    solution_resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path="solution_script.py",
            content=_preview_solution_script(),
            overwrite=True,
        ).model_dump(mode="json"),
        headers=headers,
    )
    assert solution_resp.status_code == 200, solution_resp.text

    if include_assembly_definition:
        assembly_resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="assembly_definition.yaml",
                content="preview: true\n",
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert assembly_resp.status_code == 200, assembly_resp.text

    probe_resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path="preview_probe.py",
            content=_preview_probe_script(),
            overwrite=True,
        ).model_dump(mode="json"),
        headers=headers,
    )
    assert probe_resp.status_code == 200, probe_resp.text


async def _write_benchmark_drafting_workspace(
    client: httpx.AsyncClient, session_id: str
) -> None:
    headers = {"X-Session-ID": session_id}

    workspace_files = {
        ".manifests/current_role.json": current_role_manifest_json(
            AgentName.BENCHMARK_PLANNER
        ),
        "benchmark_plan.md": "Benchmark plan.\n",
        "benchmark_assembly_definition.yaml": yaml.safe_dump(
            AssemblyDefinition(
                constraints=AssemblyConstraints(
                    planner_target_max_unit_cost_usd=100.0,
                    planner_target_max_weight_g=1000.0,
                ),
                totals=CostTotals(
                    estimated_unit_cost_usd=1.0,
                    estimated_weight_g=1.0,
                    estimate_confidence="high",
                ),
                drafting=DraftingSheet(
                    sheet_id="sheet-1",
                    title="Benchmark Preview Drawing",
                    views=[
                        DraftingView(
                            view_id="front",
                            target="benchmark_preview_box",
                            projection="front",
                            scale=1.0,
                            datums=["A"],
                            dimensions=[
                                DraftingDimension(
                                    dimension_id="width",
                                    kind="linear",
                                    target="benchmark_preview_box",
                                    value=2.0,
                                    binding=True,
                                )
                            ],
                            callouts=[
                                DraftingCallout(
                                    callout_id="1",
                                    label="Benchmark preview box",
                                    target="benchmark_preview_box",
                                )
                            ],
                        )
                    ],
                ),
            ).model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=False,
        ),
        "benchmark_plan_technical_drawing_script.py": _benchmark_drafting_script(),
        "benchmark_preview_drawing_probe.py": _benchmark_drafting_probe_script(),
    }

    for path, content in workspace_files.items():
        resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path=path,
                content=content,
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text


async def _collect_preview_status_phases(
    websocket, *, required_phases: set[str], timeout_s: float = 60.0
) -> list[str]:
    phases: list[str] = []
    deadline = asyncio.get_running_loop().time() + timeout_s

    while asyncio.get_running_loop().time() < deadline:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            raw_message = await asyncio.wait_for(
                websocket.recv(), timeout=min(remaining, 5.0)
            )
        except TimeoutError:
            if required_phases.issubset(set(phases)):
                break
            continue
        payload = (
            json.loads(raw_message) if isinstance(raw_message, str) else raw_message
        )
        if not isinstance(payload, dict):
            continue
        if payload.get("type") != "status_update":
            continue
        metadata_vars = payload.get("metadata_vars") or {}
        phase = metadata_vars.get("preview_phase")
        if isinstance(phase, str):
            phases.append(phase)
            if required_phases.issubset(set(phases)):
                break

    return phases


async def _collect_simulation_frames(
    websocket, *, required_count: int = 1, timeout_s: float = 120.0
) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    deadline = asyncio.get_running_loop().time() + timeout_s

    while asyncio.get_running_loop().time() < deadline:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            raw_message = await asyncio.wait_for(
                websocket.recv(), timeout=min(remaining, 5.0)
            )
        except TimeoutError:
            if len(frames) >= required_count:
                break
            continue
        payload = (
            json.loads(raw_message) if isinstance(raw_message, str) else raw_message
        )
        if not isinstance(payload, dict):
            continue
        if payload.get("type") != "simulation_frame":
            continue
        frames.append(payload)
        if len(frames) >= required_count:
            break

    return frames


@pytest.mark.integration_p1
@pytest.mark.asyncio
@pytest.mark.int_id("INT-224")
async def test_int_224_controller_script_tools_validate_accepts_yaml_goal_zone_overlap():
    """
    INT-224: controller script-tools validate must accept planner drafting
    geometry when the YAML drafting contract declares the goal-zone overlap.
    """
    session_id = f"INT-224-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(timeout=1000.0) as client:
        await _write_engineer_planner_drafting_workspace(
            client,
            session_id,
            allow_goal_zone_overlap=True,
        )

        create_episode_resp = await client.post(
            f"{CONTROLLER_URL}/api/test/episodes",
            json=AgentRunRequest(
                task="INT-224 controller planner drafting overlap acceptance",
                session_id=session_id,
                agent_name=AgentName.ENGINEER_PLANNER,
            ).model_dump(mode="json"),
            timeout=120.0,
        )
        assert create_episode_resp.status_code == 201, create_episode_resp.text
        EpisodeCreateResponse.model_validate(create_episode_resp.json())

        validate_resp = await client.post(
            f"{CONTROLLER_URL}/api/script-tools/validate",
            json={
                "script_path": "solution_plan_evidence_script.py",
                "agent_role": AgentName.ENGINEER_PLANNER.value,
            },
            headers={"X-Session-ID": session_id},
            timeout=1000.0,
        )

        assert validate_resp.status_code == 200, validate_resp.text
        validate_data = BenchmarkToolResponse.model_validate(validate_resp.json())
        assert validate_data.success, validate_data.message
        assert validate_data.artifacts is not None


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_int_193_controller_script_tools_verify_waits_through_temporal_queue():
    """
    INT-193: controller script-tools verify must wait through the Temporal-backed
    heavy path instead of leaking a raw worker-heavy busy response.
    """
    busy_session_id = f"INT-193-BUSY-{uuid.uuid4().hex[:8]}"
    tool_session_id = f"INT-193-TOOLS-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(timeout=1000.0) as client:
        await _write_session_workspace(client, busy_session_id, "busy_script.py")
        await _write_session_workspace(client, tool_session_id, "sample_script.py")

        create_episode_resp = await client.post(
            f"{CONTROLLER_URL}/api/test/episodes",
            json=AgentRunRequest(
                task="INT-193 controller script-tools verify proxy",
                session_id=tool_session_id,
                agent_name=AgentName.BENCHMARK_CODER,
            ).model_dump(mode="json"),
            timeout=120.0,
        )
        assert create_episode_resp.status_code == 201, create_episode_resp.text
        EpisodeCreateResponse.model_validate(create_episode_resp.json())

        tool_validation_results = json.dumps(
            {
                "success": True,
                "message": "seeded",
                "timestamp": 0.0,
                "script_path": "sample_script.py",
                "script_sha256": "1" * 64,
                "verification_result": None,
            }
        )
        tool_validation_resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="validation_results.json",
                content=tool_validation_results,
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": tool_session_id},
            timeout=1000.0,
        )
        assert tool_validation_resp.status_code == 200, tool_validation_resp.text

        busy_validation_results = json.dumps(
            {
                "success": True,
                "message": "seeded",
                "timestamp": 0.0,
                "script_path": "busy_script.py",
                "script_sha256": "0" * 64,
                "verification_result": None,
            }
        )
        busy_validation_resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="validation_results.json",
                content=busy_validation_results,
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": busy_session_id},
            timeout=1000.0,
        )
        assert busy_validation_resp.status_code == 200, busy_validation_resp.text

        busy_task = asyncio.create_task(
            client.post(
                f"{WORKER_HEAVY_URL}/benchmark/verify",
                json={
                    "script_path": "busy_script.py",
                    "backend": SimulatorBackendType.MUJOCO.value,
                    "smoke_test_mode": True,
                    "num_scenes": 5,
                    "duration": 10.0,
                    "jitter_range": [0.0, 0.0, 0.0],
                    "seed": 42,
                },
                headers={"X-Session-ID": busy_session_id},
                timeout=1000.0,
            )
        )

        worker_busy = False
        for _ in range(80):
            ready_resp = await client.get(f"{WORKER_HEAVY_URL}/ready", timeout=5.0)
            if ready_resp.status_code != 200:
                worker_busy = True
                break
            await asyncio.sleep(0.2)

        assert worker_busy, "worker-heavy never reported busy during the control run"

        verify_resp = await client.post(
            f"{CONTROLLER_URL}/api/script-tools/verify",
            json={
                "script_path": "sample_script.py",
                "agent_role": AgentName.BENCHMARK_CODER.value,
                "backend": SimulatorBackendType.MUJOCO.value,
                "smoke_test_mode": True,
                "jitter_range": [0.0, 0.0, 0.0],
                "seed": 42,
            },
            headers={"X-Session-ID": tool_session_id},
            timeout=1000.0,
        )

        assert verify_resp.status_code == 200, verify_resp.text
        verify_data = BenchmarkToolResponse.model_validate(verify_resp.json())
        assert verify_data.success, verify_data.message
        assert verify_data.artifacts is not None
        assert verify_data.artifacts.verification_result is not None
        assert verify_data.artifacts.verification_result.num_scenes == 1
        assert verify_data.artifacts.verification_result.backend_run_count == 1
        assert "WORKER_BUSY" not in verify_resp.text

        busy_resp = await busy_task
        assert busy_resp.status_code == 200, busy_resp.text
        busy_data = BenchmarkToolResponse.model_validate(busy_resp.json())
        assert busy_data.success, busy_data.message


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_int_193b_worker_heavy_smoke_verification_uses_smoke_defaults(
    tmp_path, monkeypatch
):
    """INT-193B: smoke-mode verification should shrink omitted batch settings."""
    from shared.models.simulation import MultiRunResult
    from shared.workers.schema import ValidationResultRecord, VerificationRequest
    from worker_heavy.utils import verification as verification_mod

    root = tmp_path / "session"
    root.mkdir()
    (root / "scene.xml").write_text("<xml />\n", encoding="utf-8")
    (root / "validation_results.json").write_text(
        ValidationResultRecord(
            success=True,
            message="seeded",
            timestamp=0.0,
            script_path="sample_script.py",
            script_sha256="0" * 64,
            verification_result=None,
        ).model_dump_json(),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    class DummyBuilder:
        def build_from_assembly(self, component, objectives, smoke_test_mode):
            return root / "scene.xml"

    def fake_verify_with_jitter(**kwargs):
        captured.update(kwargs)
        return MultiRunResult(
            num_scenes=kwargs["num_scenes"],
            success_count=kwargs["num_scenes"],
            success_rate=1.0,
            is_consistent=True,
            individual_results=[],
            fail_reasons=[],
        )

    monkeypatch.setattr(
        verification_mod, "_load_workspace_benchmark_definition", lambda *_, **__: None
    )
    monkeypatch.setattr(
        verification_mod, "load_component_from_script", lambda *_, **__: object()
    )
    monkeypatch.setattr(
        verification_mod, "get_simulation_builder", lambda *_, **__: DummyBuilder()
    )
    monkeypatch.setattr(verification_mod, "verify_with_jitter", fake_verify_with_jitter)
    monkeypatch.setattr(
        verification_mod, "collect_and_cleanup_events", lambda *_, **__: []
    )
    monkeypatch.setattr(
        verification_mod, "record_validation_result", lambda *_, **__: None
    )

    response = await verification_mod.run_verification_job(
        root=root,
        request=VerificationRequest(
            script_path="sample_script.py",
            backend=SimulatorBackendType.MUJOCO,
            smoke_test_mode=True,
            jitter_range=[0.0, 0.0, 0.0],
            seed=42,
        ),
        session_id="INT-193B",
    )

    assert response.success is True
    assert response.artifacts is not None
    assert response.artifacts.verification_result is not None
    assert response.artifacts.verification_result.num_scenes == 1
    assert response.artifacts.verification_result.backend_run_count == 1
    assert captured["num_scenes"] == 1
    assert captured["duration"] == 1.0
    assert captured["smoke_test_mode"] is True
