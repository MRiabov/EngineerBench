import math
import os
import uuid

import httpx
import pytest

from shared.agents.config import load_agents_config
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName
from shared.models.schemas import (
    AssemblyConstraints,
    AssemblyDefinition,
    BenchmarkDefinition,
    BenchmarkPartDefinition,
    BenchmarkPartMetadata,
    BoundingBox,
    Constraints,
    CostTotals,
    ForbidZone,
    ObjectivesSection,
    Payload,
    PhysicsConfig,
    RandomizationMeta,
    StaticRandomization,
)
from shared.models.serialization import dump_yaml_content
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.schema import (
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    WriteFileRequest,
)

pytestmark = pytest.mark.xdist_group(name="physics_sims")

WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
WORKER_HEAVY_URL = os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002")


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


def _objective_validation_artifacts():
    valid_plan = """## 1. Solution Overview

Move the projectile into the goal zone using a simple passive setup.

## 2. Parts List

- Ground plane
- Guide rails

## 3. Assembly Strategy

1. Place the guide rails on the base.
2. Verify the projectile starts clear of the fixtures.

## 4. Assumption Register

- ASSUMP-001: The launcher remains passive.

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| --- | --- | --- | --- |
| CALC-001 | Clearance envelope check | Pass | Confirms the seed geometry is valid |

### CALC-001: Clearance envelope check

#### Problem Statement
Confirm the projectile starts outside the fixed geometry envelope.

#### Assumptions
- The passive fixtures stay within their declared bounds.

#### Derivation
- The start position stays clear of the fixture volume.

#### Worst-Case Check
- The minimum clearance remains positive.

#### Result
- The start pose is valid.

#### Design Impact
- No extra motion constraints are required.

#### Cross-References
- `benchmark_definition.yaml`

## 6. Critical Constraints / Operating Envelope

- Respect the declared build zone and simulation bounds.

## 7. Cost & Weight Budget

- The fixture stays well within budget.

## 8. Risk Assessment

- Minor geometry drift is the primary risk.
"""
    valid_todo = "# TODO\n\n- [x] Planner handoff seeded\n"
    valid_cost = AssemblyDefinition(
        version="1.0",
        constraints=AssemblyConstraints(
            benchmark_max_unit_cost_usd=50.0,
            benchmark_max_weight_g=1200.0,
            planner_target_max_unit_cost_usd=45.0,
            planner_target_max_weight_g=1000.0,
        ),
        manufactured_parts=[],
        final_assembly=[],
        totals=CostTotals(
            estimated_unit_cost_usd=0.0,
            estimated_weight_g=0.0,
            estimate_confidence="high",
        ),
    )
    minimal_script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    p = Box(10, 10, 10)
    p = p.move(Location((-20, 0, 5)))
    p.label = "test_part"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum-6061",
    )
    return p
"""
    return valid_plan, valid_todo, valid_cost, minimal_script


def _objective_validation_payload(
    *,
    goal_zone_min_mm: list[float],
    goal_zone_max_mm: list[float],
    build_zone_min_mm: list[float],
    build_zone_max_mm: list[float],
    start_position_mm: list[float],
    runtime_jitter_mm: list[float],
    radius_mm: list[float],
    forbid_zones: list[ForbidZone] | None = None,
    simulation_bounds_min_mm: list[float] | None = None,
    simulation_bounds_max_mm: list[float] | None = None,
) -> BenchmarkDefinition:
    return BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(
                min_mm=tuple(goal_zone_min_mm),
                max_mm=tuple(goal_zone_max_mm),
            ),
            forbid_zones=forbid_zones or [],
            build_zone_mm=BoundingBox(
                min_mm=tuple(build_zone_min_mm),
                max_mm=tuple(build_zone_max_mm),
            ),
        ),
        physics=PhysicsConfig(backend=SimulatorBackendType.GENESIS),
        simulation_bounds_mm=BoundingBox(
            min_mm=tuple(simulation_bounds_min_mm or [-30.0, -30.0, -10.0]),
            max_mm=tuple(simulation_bounds_max_mm or [30.0, 30.0, 30.0]),
        ),
        payload=Payload(
            label="projectile_ball",
            shape="sphere",
            material_id="abs",
            static_randomization=StaticRandomization(radius_mm=tuple(radius_mm)),
            start_position_mm=tuple(start_position_mm),
            runtime_jitter_mm=tuple(runtime_jitter_mm),
        ),
        constraints=Constraints(max_unit_cost=50.0, max_weight_g=1200.0),
        benchmark_parts=_default_benchmark_parts(),
        randomization=RandomizationMeta(
            static_variation_id="v1.0",
            runtime_jitter_enabled=True,
        ),
    )


async def _write_workspace_file(
    client: httpx.AsyncClient, headers: dict[str, str], path: str, content: str | dict
) -> None:
    payload = dump_yaml_content(content)
    resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path=path,
            content=payload,
            overwrite=True,
        ).model_dump(mode="json"),
        headers=headers,
    )
    assert resp.status_code == 200, f"Failed to write {path}: {resp.text}"

    if path == "solution.py":
        await _write_workspace_file(
            client,
            headers,
            ".manifests/current_role.json",
            current_role_manifest_json(AgentName.ENGINEER_CODER),
        )
    elif path == "benchmark_script.py":
        await _write_workspace_file(
            client,
            headers,
            ".manifests/current_role.json",
            current_role_manifest_json(AgentName.BENCHMARK_CODER),
        )


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_objectives_semantic_validation_rejects_goal_forbid_overlap():
    """
    INT-008: benchmark_definition.yaml validation must fail closed on semantic contradictions,
    not only schema errors, before benchmark submission proceeds.
    """
    session_id = f"INT-008-OBJ-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan, valid_todo, valid_cost, minimal_script = (
        _objective_validation_artifacts()
    )
    overlapping_objectives = _objective_validation_payload(
        goal_zone_min_mm=[1.0, -1.0, 0.0],
        goal_zone_max_mm=[2.0, 1.0, 1.0],
        build_zone_min_mm=[-5.0, -5.0, 0.0],
        build_zone_max_mm=[5.0, 5.0, 15.0],
        start_position_mm=[0.0, 0.0, 12.0],
        runtime_jitter_mm=[0.1, 0.1, 0.1],
        radius_mm=[0.25, 0.25],
        forbid_zones=[
            ForbidZone(
                name="out_of_bounds",
                min_mm=(0.0, -2.0, 0.0),
                max_mm=(3.0, 2.0, 2.0),
            )
        ],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "engineering_plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", overlapping_objectives
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert "goal_zone_mm overlaps forbid zone" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_objectives_semantic_validation_rejects_runtime_envelope_forbid_zone_collision():
    """
    INT-008: benchmark_definition.yaml validation must fail closed when the
    payload runtime envelope intersects a forbid zone.
    """
    session_id = f"INT-008-OBJ-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}
    valid_plan, valid_todo, valid_cost, minimal_script = (
        _objective_validation_artifacts()
    )
    collision_objectives = _objective_validation_payload(
        goal_zone_min_mm=[1.0, -1.0, 0.0],
        goal_zone_max_mm=[2.0, 1.0, 1.0],
        build_zone_min_mm=[-5.0, -5.0, 0.0],
        build_zone_max_mm=[5.0, 5.0, 15.0],
        start_position_mm=[0.0, 0.0, 5.0],
        runtime_jitter_mm=[0.25, 0.25, 0.25],
        radius_mm=[0.1, 0.1],
        forbid_zones=[
            ForbidZone(
                name="clearance_window",
                min_mm=(-0.25, -0.25, 4.5),
                max_mm=(0.25, 0.25, 5.5),
            )
        ],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "engineering_plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", collision_objectives
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.success is False
        assert "CONTRADICTORY_CONSTRAINTS" in data.message
        assert "clearance_window" in data.message
        assert "runtime envelope intersects forbid zone" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_objectives_semantic_validation_rejects_goal_zone_outside_build_zone():
    """
    INT-008: benchmark_definition.yaml validation must fail closed when the
    goal zone does not overlap the build zone.
    """
    session_id = f"INT-008-OBJ-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}
    valid_plan, valid_todo, valid_cost, minimal_script = (
        _objective_validation_artifacts()
    )
    obstructed_objectives = _objective_validation_payload(
        goal_zone_min_mm=[20.0, 20.0, 0.0],
        goal_zone_max_mm=[25.0, 25.0, 5.0],
        build_zone_min_mm=[-5.0, -5.0, 0.0],
        build_zone_max_mm=[5.0, 5.0, 15.0],
        start_position_mm=[0.0, 0.0, 5.0],
        runtime_jitter_mm=[0.25, 0.25, 0.25],
        radius_mm=[0.1, 0.1],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "engineering_plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", obstructed_objectives
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.success is False
        assert "UNSOLVABLE_SCENARIO" in data.message
        assert "goal_zone_mm does not overlap build_zone_mm" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_objectives_semantic_validation_rejects_build_zone_outside_simulation_bounds():
    """
    INT-008: benchmark_definition.yaml validation must fail closed when the
    build zone exceeds the declared simulation bounds.
    """
    session_id = f"INT-008-OBJ-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}
    valid_plan, valid_todo, valid_cost, minimal_script = (
        _objective_validation_artifacts()
    )
    out_of_bounds_objectives = _objective_validation_payload(
        goal_zone_min_mm=[1.0, -1.0, 0.0],
        goal_zone_max_mm=[2.0, 1.0, 1.0],
        build_zone_min_mm=[-5.0, -5.0, 0.0],
        build_zone_max_mm=[13.0, 5.0, 10.0],
        start_position_mm=[0.0, 0.0, 5.0],
        runtime_jitter_mm=[0.25, 0.25, 0.25],
        radius_mm=[0.1, 0.1],
        simulation_bounds_min_mm=[-12.0, -12.0, -1.0],
        simulation_bounds_max_mm=[12.0, 12.0, 12.0],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "engineering_plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", out_of_bounds_objectives
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.success is False
        assert "UNSOLVABLE_SCENARIO" in data.message
        assert "build_zone_mm exceeds simulation_bounds_mm" in data.message
        assert "axis x" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_objectives_semantic_validation_rejects_runtime_envelope_exceeding_build_zone():
    """
    INT-008: benchmark_definition.yaml validation must fail closed when the
    payload runtime envelope exceeds the declared build zone.
    """
    session_id = f"INT-008-OBJ-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}
    valid_plan, valid_todo, valid_cost, minimal_script = (
        _objective_validation_artifacts()
    )
    build_zone_objectives = _objective_validation_payload(
        goal_zone_min_mm=[1.0, -1.0, 0.0],
        goal_zone_max_mm=[2.0, 1.0, 1.0],
        build_zone_min_mm=[0.0, 0.0, 0.0],
        build_zone_max_mm=[10.0, 10.0, 10.0],
        start_position_mm=[9.6, 5.0, 5.0],
        runtime_jitter_mm=[0.6, 0.1, 0.1],
        radius_mm=[0.2, 0.2],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "engineering_plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", build_zone_objectives
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.success is False
        assert "UNSOLVABLE_SCENARIO" in data.message
        assert "build_zone_mm" in data.message
        assert "axis x" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_objectives_semantic_validation_rejects_payload_goal_angle_below_threshold():
    """
    INT-008: benchmark_definition.yaml validation must fail closed when the
    payload-to-goal line is too shallow for gravity-driven motion.
    """
    session_id = f"INT-008-OBJ-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}
    valid_plan, valid_todo, valid_cost, minimal_script = (
        _objective_validation_artifacts()
    )
    threshold_deg = (
        load_agents_config().benchmark_solvability.minimum_payload_to_goal_angle_deg
    )
    shallow_objectives = _objective_validation_payload(
        goal_zone_min_mm=[9.0, -1.0, 0.0],
        goal_zone_max_mm=[11.0, 1.0, 1.0],
        build_zone_min_mm=[-20.0, -20.0, 0.0],
        build_zone_max_mm=[20.0, 20.0, 20.0],
        start_position_mm=[0.0, 0.0, -1.0],
        runtime_jitter_mm=[0.1, 0.1, 0.1],
        radius_mm=[0.25, 0.25],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "engineering_plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", shallow_objectives
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.success is False
        assert "UNSOLVABLE_SCENARIO" in data.message
        assert "payload start position is too shallow" in data.message
        assert f"{threshold_deg:.2f}deg" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_objectives_semantic_validation_allows_payload_goal_angle_at_threshold():
    """
    INT-008: benchmark_definition.yaml validation must accept geometry that is
    exactly on the configured threshold, not just above it.
    """
    session_id = f"INT-008-OBJ-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}
    valid_plan, valid_todo, valid_cost, minimal_script = (
        _objective_validation_artifacts()
    )
    threshold_deg = (
        load_agents_config().benchmark_solvability.minimum_payload_to_goal_angle_deg
    )
    horizontal_distance_mm = 10.0
    start_height_mm = math.tan(math.radians(threshold_deg)) * horizontal_distance_mm
    threshold_objectives = _objective_validation_payload(
        goal_zone_min_mm=[9.0, -1.0, 0.0],
        goal_zone_max_mm=[11.0, 1.0, 1.0],
        build_zone_min_mm=[-20.0, -20.0, 0.0],
        build_zone_max_mm=[20.0, 20.0, 20.0],
        start_position_mm=[0.0, 0.0, start_height_mm],
        runtime_jitter_mm=[0.1, 0.1, 0.1],
        radius_mm=[0.25, 0.25],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "engineering_plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", threshold_objectives
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.success is True, data.message
        assert "UNSOLVABLE_SCENARIO" not in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.parametrize(
    ("case_name", "runtime_jitter", "radius", "expected_phrase"),
    [
        (
            "negative_jitter",
            [-0.1, 0.1, 0.1],
            [0.25, 0.25],
            "runtime_jitter_mm",
        ),
        ("negative_radius", [0.1, 0.1, 0.1], [-0.25, 0.25], "radius_mm"),
    ],
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_objectives_semantic_validation_rejects_negative_runtime_jitter_and_radius(
    case_name: str,
    runtime_jitter: list[float],
    radius: list[float],
    expected_phrase: str,
):
    """
    INT-008: benchmark_definition.yaml validation must fail closed for negative
    runtime ranges instead of auto-correcting them.
    """
    session_id = f"INT-008-OBJ-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}
    valid_plan, valid_todo, valid_cost, minimal_script = (
        _objective_validation_artifacts()
    )
    negative_objectives = _objective_validation_payload(
        goal_zone_min_mm=[1.0, -1.0, 0.0],
        goal_zone_max_mm=[2.0, 1.0, 1.0],
        build_zone_min_mm=[-5.0, -5.0, 0.0],
        build_zone_max_mm=[5.0, 5.0, 15.0],
        start_position_mm=[0.0, 0.0, 5.0],
        runtime_jitter_mm=runtime_jitter,
        radius_mm=radius,
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "engineering_plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", negative_objectives
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.success is False
        assert "INVALID_OBJECTIVES" in data.message
        assert expected_phrase in data.message, f"{case_name}: {data.message}"
        assert "must be non-negative" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_requires_non_empty_benchmark_parts():
    """
    INT-008: benchmark_definition.yaml must fail closed when benchmark_parts is
    omitted because benchmark-owned fixtures are a required source contract.
    """
    session_id = f"INT-008-PARTS-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan, valid_todo, valid_cost, minimal_script = (
        _objective_validation_artifacts()
    )
    missing_benchmark_parts = _objective_validation_payload(
        goal_zone_min_mm=[1.0, -1.0, 0.0],
        goal_zone_max_mm=[2.0, 1.0, 1.0],
        build_zone_min_mm=[-5.0, -5.0, 0.0],
        build_zone_max_mm=[5.0, 5.0, 15.0],
        start_position_mm=[-4.0, 0.0, 0.5],
        runtime_jitter_mm=[0.1, 0.1, 0.1],
        radius_mm=[0.25, 0.25],
    ).model_dump(mode="json")
    missing_benchmark_parts.pop("benchmark_parts", None)

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "engineering_plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", missing_benchmark_parts
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.success is False
        assert "benchmark_parts" in data.message


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_submit_requires_explicit_reviewer_stage():
    """/benchmark/submit must fail closed when reviewer_stage is omitted."""
    session_id = f"INT-008-STAGE-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan, valid_todo, valid_cost, minimal_script = (
        _objective_validation_artifacts()
    )
    valid_objectives = _objective_validation_payload(
        goal_zone_min_mm=[1.0, -1.0, 0.0],
        goal_zone_max_mm=[2.0, 1.0, 1.0],
        build_zone_min_mm=[-5.0, -5.0, 0.0],
        build_zone_max_mm=[5.0, 5.0, 15.0],
        start_position_mm=[-4.0, 0.0, 0.5],
        runtime_jitter_mm=[0.1, 0.1, 0.1],
        radius_mm=[0.25, 0.25],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "engineering_plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", valid_objectives
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(script_path="solution.py").model_dump(
                mode="json"
            ),
            headers=headers,
        )
        assert resp.status_code == 400, resp.text
        assert "reviewer_stage is required" in resp.text


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_objectives_semantic_validation_rejects_runtime_envelope_forbid_collision():
    """
    INT-008: benchmark_definition.yaml validation must fail closed when the
    payload's runtime envelope intersects a forbid zone.
    """
    session_id = f"INT-008-FORBID-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan, valid_todo, valid_cost, minimal_script = (
        _objective_validation_artifacts()
    )

    forbid_collision_objectives = _objective_validation_payload(
        goal_zone_min_mm=[3.0, 3.0, 3.0],
        goal_zone_max_mm=[4.0, 4.0, 4.0],
        build_zone_min_mm=[-5.0, -5.0, 0.0],
        build_zone_max_mm=[5.0, 5.0, 10.0],
        start_position_mm=[0.0, 0.0, 1.0],
        runtime_jitter_mm=[0.5, 0.5, 0.5],
        radius_mm=[0.25, 0.25],
        forbid_zones=[
            ForbidZone(
                name="center_block",
                min_mm=(-1.0, -1.0, 0.0),
                max_mm=(1.0, 1.0, 2.0),
            )
        ],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "engineering_plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", forbid_collision_objectives
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                reviewer_stage=AgentName.BENCHMARK_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert not data.success
        assert "CONTRADICTORY_CONSTRAINTS" in data.message
        assert "runtime envelope intersects forbid zone" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-008")
async def test_int_008_objectives_semantic_validation_rejects_negative_runtime_ranges():
    """
    INT-008: benchmark_definition.yaml validation must fail closed on negative
    runtime jitter and static randomization radius values.
    """
    session_id = f"INT-008-RANGE-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan, valid_todo, valid_cost, minimal_script = (
        _objective_validation_artifacts()
    )

    base_objectives = _objective_validation_payload(
        goal_zone_min_mm=[3.0, 3.0, 3.0],
        goal_zone_max_mm=[4.0, 4.0, 4.0],
        build_zone_min_mm=[-5.0, -5.0, 0.0],
        build_zone_max_mm=[5.0, 5.0, 10.0],
        start_position_mm=[0.0, 0.0, 1.0],
        runtime_jitter_mm=[0.5, 0.5, 0.5],
        radius_mm=[0.25, 0.25],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        # 1. Negative runtime jitter must fail closed.
        negative_jitter = base_objectives.model_dump(mode="json")
        negative_jitter["payload"]["runtime_jitter_mm"] = [-0.5, 0.5, 0.5]
        await _write_workspace_file(client, headers, "engineering_plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", negative_jitter
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                reviewer_stage=AgentName.BENCHMARK_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert not data.success
        assert "INVALID_OBJECTIVES" in data.message
        assert "runtime_jitter_mm" in data.message

        # 2. Negative static randomization radius must also fail closed.
        negative_radius = base_objectives.model_dump(mode="json")
        negative_radius["payload"]["static_randomization"]["radius_mm"] = [
            -0.25,
            0.25,
        ]
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", negative_radius
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="solution.py",
                reviewer_stage=AgentName.BENCHMARK_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert not data.success
        assert "INVALID_OBJECTIVES" in data.message
        assert "static_randomization.radius_mm" in data.message
