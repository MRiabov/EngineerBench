import os
import uuid
from pathlib import Path

import httpx
import pytest
import yaml
from build123d import Location, Plane

from controller.agent.node_entry_validation import (
    validate_seeded_workspace_handoff_artifacts,
)
from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    BenchmarkConfirmResponse,
    BenchmarkGenerateRequest,
    BenchmarkGenerateResponse,
    ConfirmRequest,
    EpisodeCreateResponse,
    EpisodeResponse,
)
from controller.clients.worker import WorkerClient
from shared.agents.config import AgentsConfig, DraftingMode
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName, EntryFailureDisposition, EpisodeStatus, TraceType
from shared.models.schemas import (
    AssemblyConstraints,
    AssemblyDefinition,
    AssemblyPartConfig,
    BenchmarkDefinition,
    BoundingBox,
    Constraints,
    CostTotals,
    DraftingCallout,
    DraftingDimension,
    DraftingLayout,
    DraftingLayoutView,
    DraftingSheet,
    DraftingView,
    EntryValidationContext,
    MotionForecast,
    MotionForecastAnchor,
    MotionForecastContact,
    MovedObject,
    ObjectivesSection,
    PartConfig,
    PayloadTrajectoryDefinition,
    PayloadTrajectoryPose,
    PhysicsConfig,
)
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.schema import ReviewManifest
from tests.integration.agent.helpers import (
    seed_benchmark_assembly_definition,
    wait_for_benchmark_state,
    wait_for_episode_terminal,
)
from worker_heavy.utils.dfm import load_planner_manufacturing_config_from_text
from worker_heavy.utils.file_validation import validate_node_output

WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
AGENTS_CONFIG_PATH = Path("config/agents_config.yaml")

CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")
REPO_MANUFACTURING_CONFIG = Path(
    "worker_heavy/workbenches/manufacturing_config.yaml"
).read_text(encoding="utf-8")
pytestmark = pytest.mark.xdist_group(name="physics_sims")


def _default_benchmark_parts() -> list[dict[str, object]]:
    return [
        {
            "part_id": "environment_fixture",
            "label": "environment_fixture",
            "metadata": {"fixed": True, "material_id": "aluminum_6061"},
        }
    ]


async def _poll_engineer_episode(
    client: httpx.AsyncClient,
    episode_id: str,
    *,
    terminal_statuses: set[EpisodeStatus],
    max_attempts: int = 90,
) -> EpisodeResponse:
    return EpisodeResponse.model_validate(
        await wait_for_episode_terminal(
            client,
            episode_id,
            timeout_s=float(max_attempts),
            terminal_statuses=terminal_statuses,
        )
    )


async def _poll_benchmark_session(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    terminal_statuses: set[EpisodeStatus],
    max_attempts: int = 90,
) -> EpisodeResponse:
    return EpisodeResponse.model_validate(
        await wait_for_benchmark_state(
            client,
            session_id,
            timeout_s=float(max_attempts),
            terminal_statuses=terminal_statuses,
        )
    )


def _entry_validation_from_episode(episode: EpisodeResponse) -> EntryValidationContext:
    assert episode.metadata_vars is not None
    additional_info = episode.metadata_vars.additional_info or {}
    raw = additional_info.get("entry_validation")
    assert isinstance(raw, dict), "Missing metadata.additional_info.entry_validation"
    return EntryValidationContext.model_validate(raw)


def _node_start_traces(episode: EpisodeResponse, node_name: str) -> list[str]:
    return [
        trace.content or ""
        for trace in (episode.traces or [])
        if trace.trace_type == TraceType.LOG
        and trace.name == node_name
        and "Starting task phase" in (trace.content or "")
    ]


def _agents_config_with_technical_drawing_modes(
    *,
    engineer_mode: DraftingMode = DraftingMode.OFF,
    benchmark_mode: DraftingMode = DraftingMode.OFF,
) -> AgentsConfig:
    data = yaml.safe_load(AGENTS_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    agents = data.setdefault("agents", {})
    engineer_agent = agents.setdefault("engineer_planner", {})
    engineer_agent["technical_drawing_mode"] = engineer_mode
    benchmark_agent = agents.setdefault("benchmark_planner", {})
    benchmark_agent["technical_drawing_mode"] = benchmark_mode
    return AgentsConfig.model_validate(data)


def _drafting_validation_payloads(
    *,
    assembly_part_name: str,
    drafting_target: str,
) -> tuple[dict[str, object], dict[str, object]]:
    benchmark_definition = BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone=BoundingBox(min=(12.0, 12.0, 0.0), max=(16.0, 16.0, 6.0)),
            forbid_zones=[],
            build_zone=BoundingBox(min=(-20.0, -20.0, 0.0), max=(20.0, 20.0, 30.0)),
        ),
        physics=PhysicsConfig(backend=SimulatorBackendType.GENESIS),
        simulation_bounds=BoundingBox(
            min=(-50.0, -50.0, -10.0), max=(50.0, 50.0, 50.0)
        ),
        payload=MovedObject(
            label="target_box",
            shape="sphere",
            material_id="aluminum_6061",
            start_position=(0.0, 0.0, 10.0),
            runtime_jitter=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
        benchmark_parts=_default_benchmark_parts(),
    )
    assembly_definition = AssemblyDefinition(
        version="1.0",
        constraints=AssemblyConstraints(
            planner_target_max_unit_cost_usd=90.0,
            planner_target_max_weight_g=900.0,
        ),
        manufactured_parts=[],
        cots_parts=[],
        final_assembly=[
            PartConfig(name=assembly_part_name, config=AssemblyPartConfig())
        ],
        totals=CostTotals(
            estimated_unit_cost_usd=0.0,
            estimated_weight_g=0.0,
            estimate_confidence="high",
        ),
        drafting=DraftingSheet(
            sheet_id="sheet-1",
            title="Broken Drafting",
            views=[
                DraftingView(
                    view_id="front",
                    target=drafting_target,
                    projection="front",
                    datums=["A"],
                    dimensions=[
                        DraftingDimension(
                            dimension_id="width",
                            kind="linear",
                            target=drafting_target,
                            value=10.0,
                            binding=True,
                        )
                    ],
                    callouts=[
                        DraftingCallout(
                            callout_id="1",
                            label="Drafting target",
                            target=drafting_target,
                        )
                    ],
                )
            ],
            layout=DraftingLayout(
                mode="orthographic_trio",
                views=[
                    DraftingLayoutView(view_id="front"),
                ],
            ),
        ),
    )
    return (
        benchmark_definition.model_dump(mode="json", by_alias=True, exclude_none=True),
        assembly_definition.model_dump(mode="json", by_alias=True, exclude_none=True),
    )


def _motion_forecast_validation_payloads(
    *,
    first_anchor_pos: tuple[float, float, float],
    terminal_anchor_pos: tuple[float, float, float],
    first_anchor_rot_deg: tuple[float, float, float] = (0.0, 0.0, 0.0),
    terminal_anchor_rot_deg: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> tuple[dict[str, object], dict[str, object]]:
    benchmark_definition = BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone=BoundingBox(min=(10.0, 10.0, 0.0), max=(20.0, 20.0, 10.0)),
            forbid_zones=[],
            build_zone=BoundingBox(min=(-20.0, -20.0, 0.0), max=(20.0, 20.0, 20.0)),
        ),
        physics=PhysicsConfig(backend=SimulatorBackendType.GENESIS),
        simulation_bounds=BoundingBox(
            min=(-50.0, -50.0, -10.0), max=(50.0, 50.0, 50.0)
        ),
        payload=MovedObject(
            label="target_box",
            shape="sphere",
            material_id="aluminum_6061",
            start_position=(0.0, 0.0, 5.0),
            runtime_jitter=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
        benchmark_parts=_default_benchmark_parts(),
    )
    motion_forecast = MotionForecast(
        moving_part_names=["moving_bracket"],
        sample_stride_s=0.3,
        anchors=[
            MotionForecastAnchor(
                t_s=0.0,
                reference_point="build_zone_start",
                pos_mm=first_anchor_pos,
                rot_deg=first_anchor_rot_deg,
                position_tolerance_mm=(0.6, 0.6, 0.6),
                rotation_tolerance_deg=(0.1, 0.1, 2.0),
                first_contacts=[
                    MotionForecastContact(
                        order=1,
                        surface="fixture_top",
                        first_touch_window_s=(0.2, 0.4),
                    )
                ],
                build_zone_valid=True,
            ),
            MotionForecastAnchor(
                t_s=1.5,
                reference_point="goal_zone_contact",
                pos_mm=terminal_anchor_pos,
                rot_deg=terminal_anchor_rot_deg,
                position_tolerance_mm=(0.6, 0.6, 0.6),
                rotation_tolerance_deg=(0.1, 0.1, 2.0),
                goal_zone_contact=True,
            ),
        ],
    )
    assembly_definition = AssemblyDefinition(
        version="1.0",
        constraints=AssemblyConstraints(
            planner_target_max_unit_cost_usd=90.0,
            planner_target_max_weight_g=900.0,
        ),
        manufactured_parts=[],
        cots_parts=[],
        final_assembly=[
            PartConfig(
                name="moving_bracket",
                config=AssemblyPartConfig(dofs=["slide_z"]),
            )
        ],
        motion_forecast=motion_forecast,
        totals=CostTotals(
            estimated_unit_cost_usd=0.0,
            estimated_weight_g=0.0,
            estimate_confidence="high",
        ),
    )
    return (
        benchmark_definition.model_dump(mode="json", by_alias=True, exclude_none=True),
        assembly_definition.model_dump(mode="json", by_alias=True, exclude_none=True),
    )


def _swept_clearance_geometry_scripts(
    *,
    obstacle_center_y: float,
) -> tuple[str, str]:
    benchmark_script = f"""from build123d import Align, Box, Compound, Location


def build():
    fixture = Box(20.0, 0.2, 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    fixture = fixture.move(Location((0.0, {obstacle_center_y}, 0.0)))
    return Compound(children=[fixture], label="fixture_block")


result = build()
"""
    solution_script = """from build123d import Align, Box, Compound


def build():
    payload = Box(8.0, 2.0, 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    return Compound(children=[payload], label="moving_bracket")


result = build()
"""
    return benchmark_script, solution_script


def _obb_world_point(
    location: Location, local_point: tuple[float, float, float]
) -> tuple[float, float, float]:
    plane = Plane(location)
    origin = tuple(float(value) for value in plane.origin)
    x_dir = tuple(float(value) for value in plane.x_dir)
    y_dir = tuple(float(value) for value in plane.y_dir)
    z_dir = tuple(float(value) for value in plane.z_dir)
    return tuple(
        origin[index]
        + local_point[0] * x_dir[index]
        + local_point[1] * y_dir[index]
        + local_point[2] * z_dir[index]
        for index in range(3)
    )


def _obb_local_coords(
    location: Location, point: tuple[float, float, float]
) -> tuple[float, float, float]:
    plane = Plane(location)
    origin = tuple(float(value) for value in plane.origin)
    x_dir = tuple(float(value) for value in plane.x_dir)
    y_dir = tuple(float(value) for value in plane.y_dir)
    z_dir = tuple(float(value) for value in plane.z_dir)
    rel = tuple(point[index] - origin[index] for index in range(3))
    return (
        sum(rel[index] * x_dir[index] for index in range(3)),
        sum(rel[index] * y_dir[index] for index in range(3)),
        sum(rel[index] * z_dir[index] for index in range(3)),
    )


def _find_wrong_only_obstacle_point(
    *,
    initial_pos_mm: tuple[float, float, float],
    initial_rot_deg: tuple[float, float, float],
    sample_pos_mm: tuple[float, float, float],
    sample_rot_deg: tuple[float, float, float],
    half_sizes: tuple[float, float, float] = (4.0, 1.0, 1.0),
) -> tuple[float, float, float]:
    initial_location = Location(initial_pos_mm, initial_rot_deg)
    sample_location = Location(sample_pos_mm, sample_rot_deg)
    wrong_rot_deg = tuple(
        sample_rot_deg[index] - initial_rot_deg[index] for index in range(3)
    )
    wrong_relative = Location(
        tuple(sample_pos_mm[index] - initial_pos_mm[index] for index in range(3)),
        wrong_rot_deg,
    )
    wrong_location = wrong_relative * initial_location
    local_candidates = [
        (
            sx * half_sizes[0] * frac[0],
            sy * half_sizes[1] * frac[1],
            sz * half_sizes[2] * frac[2],
        )
        for sx in (-1.0, 1.0)
        for sy in (-1.0, 1.0)
        for sz in (-1.0, 1.0)
        for frac in (
            (0.95, 0.95, 0.95),
            (0.95, 0.8, 0.7),
            (0.9, 0.7, 0.6),
            (0.98, 0.9, 0.4),
            (0.9, 0.95, 0.5),
        )
    ]

    for local_point in local_candidates:
        world_point = _obb_world_point(wrong_location, local_point)
        correct_local = _obb_local_coords(sample_location, world_point)
        if all(abs(local_point[i]) < half_sizes[i] - 1e-9 for i in range(3)) and any(
            abs(correct_local[i]) > half_sizes[i] - 0.05 for i in range(3)
        ):
            return world_point

    raise AssertionError("Unable to derive a wrong-only obstacle witness point")


def _rotated_swept_clearance_geometry_scripts(
    *,
    obstacle_center: tuple[float, float, float],
    payload_initial_pos_mm: tuple[float, float, float],
    payload_initial_rot_deg: tuple[float, float, float],
) -> tuple[str, str]:
    obstacle_x, obstacle_y, obstacle_z = obstacle_center
    pos_x, pos_y, pos_z = payload_initial_pos_mm
    rot_x, rot_y, rot_z = payload_initial_rot_deg
    benchmark_script = f"""from build123d import Align, Box, Compound, Location


def build():
    fixture = Box(0.01, 0.01, 0.01, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    fixture = fixture.move(Location(({obstacle_x}, {obstacle_y}, {obstacle_z})))
    return Compound(children=[fixture], label="fixture_block")


result = build()
"""
    solution_script = f"""from build123d import Align, Box, Compound, Location


def build():
    payload = Box(8.0, 2.0, 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    payload = payload.move(
        Location(({pos_x}, {pos_y}, {pos_z}), ({rot_x}, {rot_y}, {rot_z}))
    )
    return Compound(children=[payload], label="moving_bracket")


result = build()
"""
    return benchmark_script, solution_script


def _payload_trajectory_definition(
    *,
    first_anchor_rotation_tolerance: tuple[float, float, float] | None = None,
    initial_pose_pos: tuple[float, float, float] = (0.0, 0.0, 0.0),
    first_anchor_pos: tuple[float, float, float] = (0.0, 0.0, 0.0),
    first_anchor_rot_deg: tuple[float, float, float] = (0.0, 0.0, 0.0),
    terminal_anchor_pos: tuple[float, float, float] = (12.0, 12.0, 0.0),
    terminal_anchor_rot_deg: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> PayloadTrajectoryDefinition:
    return PayloadTrajectoryDefinition(
        backend=SimulatorBackendType.GENESIS,
        moving_part_names=["moving_bracket"],
        initial_pose=PayloadTrajectoryPose(
            reference_point="build_zone_start",
            pos_mm=initial_pose_pos,
            rot_deg=first_anchor_rot_deg,
        ),
        sample_stride_s=0.3,
        anchors=[
            MotionForecastAnchor(
                t_s=0.0,
                reference_point="build_zone_start",
                pos_mm=first_anchor_pos,
                rot_deg=first_anchor_rot_deg,
                position_tolerance_mm=(0.1, 0.1, 0.1),
                rotation_tolerance_deg=first_anchor_rotation_tolerance,
                build_zone_valid=True,
            ),
            MotionForecastAnchor(
                t_s=1.5,
                reference_point="goal_zone_contact",
                pos_mm=terminal_anchor_pos,
                rot_deg=terminal_anchor_rot_deg,
                position_tolerance_mm=(0.1, 0.1, 0.1),
                goal_zone_contact=True,
            ),
        ],
    )


async def _upload_swept_clearance_workspace(
    worker: WorkerClient,
    *,
    benchmark_definition: BenchmarkDefinition | dict[str, object],
    assembly_definition: AssemblyDefinition | dict[str, object],
    payload_definition: PayloadTrajectoryDefinition,
    obstacle_center_y: float = 1.15,
) -> None:
    await _upload_engineer_motion_seed_workspace(
        worker,
        benchmark_definition=benchmark_definition,
        assembly_definition=assembly_definition,
    )
    benchmark_script, solution_script = _swept_clearance_geometry_scripts(
        obstacle_center_y=obstacle_center_y
    )
    await worker.upload_file(
        "benchmark_script.py",
        benchmark_script.encode("utf-8"),
        bypass_agent_permissions=True,
    )
    await worker.upload_file(
        "solution_script.py",
        solution_script.encode("utf-8"),
        bypass_agent_permissions=True,
    )
    await worker.upload_file(
        "payload_trajectory_definition.yaml",
        yaml.safe_dump(
            payload_definition.model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
            sort_keys=False,
        ).encode("utf-8"),
        bypass_agent_permissions=True,
    )


def _engineering_motion_plan_md(moving_part_name: str = "moving_bracket") -> str:
    return f"""## 1. Solution Overview
- Move the approved part from the build zone into the goal zone.

## 2. Parts List
- {moving_part_name}

## 3. Assembly Strategy
1. Assemble the moving part inside the build zone.
2. Guide it toward the goal zone using the approved coarse forecast.

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
- Stay within budget.

## 8. Risk Assessment
- Minimal risk.
"""


def _engineering_motion_todo_md() -> str:
    return "- [ ] Review the motion forecast\n"


async def _upload_engineer_motion_seed_workspace(
    worker: WorkerClient,
    *,
    benchmark_definition: BenchmarkDefinition | dict[str, object],
    assembly_definition: AssemblyDefinition | dict[str, object],
) -> None:
    benchmark_payload = (
        benchmark_definition.model_dump(mode="json", by_alias=True, exclude_none=True)
        if isinstance(benchmark_definition, BenchmarkDefinition)
        else benchmark_definition
    )
    assembly_payload = (
        assembly_definition.model_dump(mode="json", by_alias=True, exclude_none=True)
        if isinstance(assembly_definition, AssemblyDefinition)
        else assembly_definition
    )
    await worker.upload_file(
        "plan.md",
        _engineering_motion_plan_md().encode("utf-8"),
        bypass_agent_permissions=True,
    )
    await worker.upload_file(
        "todo.md",
        _engineering_motion_todo_md().encode("utf-8"),
        bypass_agent_permissions=True,
    )
    await worker.upload_file(
        "benchmark_definition.yaml",
        yaml.safe_dump(benchmark_payload, sort_keys=False).encode("utf-8"),
        bypass_agent_permissions=True,
    )
    await worker.upload_file(
        "assembly_definition.yaml",
        yaml.safe_dump(assembly_payload, sort_keys=False).encode("utf-8"),
        bypass_agent_permissions=True,
    )
    await worker.upload_file(
        "benchmark_script.py",
        b"# benchmark placeholder\n",
        bypass_agent_permissions=True,
    )
    await worker.upload_file(
        "manufacturing_config.yaml",
        REPO_MANUFACTURING_CONFIG.encode("utf-8"),
        bypass_agent_permissions=True,
    )


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_current_role_manifest_wins_over_mixed_workspace_files():
    session_id = f"INT-CURRENT-ROLE-{uuid.uuid4().hex[:8]}"
    worker = WorkerClient(base_url=WORKER_LIGHT_URL, session_id=session_id)
    try:
        await worker.write_file(
            "benchmark_plan.md",
            "# Benchmark plan\n",
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "engineering_plan.md",
            "# Engineering plan\n",
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "todo.md",
            "- [ ] Mixed workspace\n",
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "benchmark_definition.yaml",
            yaml.safe_dump(
                {
                    "constraints": {"max_unit_cost": 100.0, "max_weight_g": 1000.0},
                    "objectives": {
                        "goal_zone": {"min": [0, 0, 0], "max": [1, 1, 1]},
                        "forbid_zones": [],
                        "build_zone": {"min": [0, 0, 0], "max": [1, 1, 1]},
                    },
                },
                sort_keys=False,
            ),
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "assembly_definition.yaml",
            yaml.safe_dump(
                {
                    "version": "1.0",
                    "constraints": {},
                    "manufactured_parts": [],
                    "cots_parts": [],
                    "final_assembly": [],
                    "totals": {
                        "estimated_unit_cost_usd": 0.0,
                        "estimated_weight_g": 0.0,
                        "estimate_confidence": "high",
                    },
                },
                sort_keys=False,
            ),
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "benchmark_assembly_definition.yaml",
            yaml.safe_dump(
                {
                    "version": "1.0",
                    "constraints": {},
                    "manufactured_parts": [],
                    "cots_parts": [],
                    "final_assembly": [],
                    "totals": {
                        "estimated_unit_cost_usd": 0.0,
                        "estimated_weight_g": 0.0,
                        "estimate_confidence": "high",
                    },
                },
                sort_keys=False,
            ),
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "benchmark_script.py",
            "print('benchmark script')\n",
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "solution_script.py",
            "print('solution script')\n",
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            ".manifests/current_role.json",
            current_role_manifest_json(AgentName.BENCHMARK_CODER),
            overwrite=True,
            bypass_agent_permissions=True,
        )

        errors = await validate_seeded_workspace_handoff_artifacts(
            worker_client=worker,
            target_node=AgentName.ENGINEER_CODER,
        )
    finally:
        await worker.aclose()

    assert errors, "Expected the mixed workspace to fail for the engineer node."
    assert any(
        error.artifact_path == ".manifests/current_role.json"
        and "mismatch" in error.message.lower()
        for error in errors
    ), errors
