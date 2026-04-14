import hashlib
import os
import uuid
from pathlib import Path

import httpx
import pytest
import yaml

from shared.enums import AgentName
from shared.git_utils import repo_revision
from shared.workers.schema import (
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    ListFilesRequest,
    ReadFileRequest,
    ReadFileResponse,
    RenderArtifactMetadata,
    RenderManifest,
    RenderSiblingPaths,
    WriteFileRequest,
)

pytestmark = pytest.mark.xdist_group(name="physics_sims")

WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
WORKER_HEAVY_URL = os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002")


def _default_benchmark_parts():
    return [
        {
            "part_id": "environment_fixture",
            "label": "environment_fixture",
            "metadata": {
                "fixed": True,
                "material_id": "aluminum_6061",
            },
        }
    ]


def _objective_validation_artifacts():
    valid_plan = """## 1. Learning Objective

Move the projectile into the goal zone.

## 2. Geometry

- Ground plane
- Guide rails

## 3. Objectives

- Reach the goal zone
"""
    valid_todo = "# TODO\n\n- [x] Planner handoff seeded\n"
    valid_cost = """version: "1.0"
manufactured_parts: []
cots_parts: []
final_assembly: []
constraints:
  benchmark_max_unit_cost_usd: 50.0
  benchmark_max_weight_g: 1200.0
  planner_target_max_unit_cost_usd: 45.0
  planner_target_max_weight_g: 1000.0
totals:
  estimated_unit_cost_usd: 10.0
  estimated_weight_g: 100.0
  estimate_confidence: high
"""
    minimal_script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    p = Box(10, 10, 10)
    p = p.move(Location((0, 0, 5)))
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
    goal_zone_min: list[float],
    goal_zone_max: list[float],
    build_zone_min: list[float],
    build_zone_max: list[float],
    start_position: list[float],
    runtime_jitter: list[float],
    radius: list[float],
    forbid_zones: list[dict] | None = None,
    simulation_bounds_min: list[float] | None = None,
    simulation_bounds_max: list[float] | None = None,
) -> dict:
    return {
        "objectives": {
            "goal_zone": {"min": goal_zone_min, "max": goal_zone_max},
            "forbid_zones": forbid_zones or [],
            "build_zone": {"min": build_zone_min, "max": build_zone_max},
        },
        "physics": {"backend": "GENESIS"},
        "simulation_bounds": {
            "min": simulation_bounds_min or [-30.0, -30.0, -10.0],
            "max": simulation_bounds_max or [30.0, 30.0, 30.0],
        },
        "payload": {
            "label": "projectile_ball",
            "shape": "sphere",
            "material_id": "abs",
            "static_randomization": {"radius": radius},
            "start_position": start_position,
            "runtime_jitter": runtime_jitter,
        },
        "constraints": {"max_unit_cost": 50.0, "max_weight_g": 1200.0},
        "benchmark_parts": _default_benchmark_parts(),
        "randomization": {
            "static_variation_id": "v1.0",
            "runtime_jitter_enabled": True,
        },
    }


async def _write_workspace_file(
    client: httpx.AsyncClient, headers: dict[str, str], path: str, content: str | dict
) -> None:
    payload = content if isinstance(content, str) else yaml.dump(content)
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


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
async def test_int_008_objectives_semantic_validation_rejects_goal_forbid_overlap():
    """
    INT-008: benchmark_definition.yaml validation must fail closed on semantic contradictions,
    not only schema errors, before benchmark submission proceeds.
    """
    session_id = f"INT-008-OBJ-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan = """## 1. Learning Objective

Move the projectile into the goal zone.

## 2. Geometry

- Ground plane
- Guide rails

## 3. Objectives

- Reach the goal zone
"""
    valid_todo = "# TODO\n\n- [x] Planner handoff seeded\n"
    valid_cost = """version: "1.0"
manufactured_parts: []
cots_parts: []
final_assembly: []
totals:
  estimated_unit_cost_usd: 10.0
  estimated_weight_g: 100.0
"""
    minimal_script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    p = Box(10, 10, 10)
    p = p.move(Location((0, 0, 5)))
    p.label = "test_part"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum-6061",
    )
    return p
"""
    overlapping_objectives = {
        "objectives": {
            "goal_zone": {"min": [1.0, -1.0, 0.0], "max": [2.0, 1.0, 1.0]},
            "forbid_zones": [
                {
                    "name": "out_of_bounds",
                    "min": [0.0, -2.0, 0.0],
                    "max": [3.0, 2.0, 2.0],
                }
            ],
            "build_zone": {"min": [-5.0, -5.0, 0.0], "max": [5.0, 5.0, 15.0]},
        },
        "physics": {"backend": "GENESIS"},
        "simulation_bounds": {
            "min": [-30.0, -30.0, -10.0],
            "max": [30.0, 30.0, 30.0],
        },
        "payload": {
            "label": "projectile_ball",
            "shape": "sphere",
            "material_id": "abs",
            "static_randomization": {"radius": [0.25, 0.25]},
            "start_position": [-4.0, 0.0, 0.5],
            "runtime_jitter": [0.1, 0.1, 0.1],
        },
        "constraints": {"max_unit_cost": 50.0, "max_weight_g": 1200.0},
        "benchmark_parts": _default_benchmark_parts(),
        "randomization": {
            "static_variation_id": "v1.0",
            "runtime_jitter_enabled": True,
        },
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
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
        assert "goal_zone overlaps forbid zone" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
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
        goal_zone_min=[1.0, -1.0, 0.0],
        goal_zone_max=[2.0, 1.0, 1.0],
        build_zone_min=[-5.0, -5.0, 0.0],
        build_zone_max=[5.0, 5.0, 15.0],
        start_position=[0.0, 0.0, 5.0],
        runtime_jitter=[0.25, 0.25, 0.25],
        radius=[0.1, 0.1],
        forbid_zones=[
            {
                "name": "clearance_window",
                "min": [-0.25, -0.25, 4.5],
                "max": [0.25, 0.25, 5.5],
            }
        ],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
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
        goal_zone_min=[20.0, 20.0, 0.0],
        goal_zone_max=[25.0, 25.0, 5.0],
        build_zone_min=[-5.0, -5.0, 0.0],
        build_zone_max=[5.0, 5.0, 15.0],
        start_position=[0.0, 0.0, 5.0],
        runtime_jitter=[0.25, 0.25, 0.25],
        radius=[0.1, 0.1],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
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
        assert "goal_zone does not overlap build_zone" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
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
        goal_zone_min=[1.0, -1.0, 0.0],
        goal_zone_max=[2.0, 1.0, 1.0],
        build_zone_min=[-5.0, -5.0, 0.0],
        build_zone_max=[13.0, 5.0, 10.0],
        start_position=[0.0, 0.0, 5.0],
        runtime_jitter=[0.25, 0.25, 0.25],
        radius=[0.1, 0.1],
        simulation_bounds_min=[-12.0, -12.0, -1.0],
        simulation_bounds_max=[12.0, 12.0, 12.0],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
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
        assert "build_zone exceeds simulation_bounds" in data.message
        assert "axis x" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
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
        goal_zone_min=[1.0, -1.0, 0.0],
        goal_zone_max=[2.0, 1.0, 1.0],
        build_zone_min=[0.0, 0.0, 0.0],
        build_zone_max=[10.0, 10.0, 10.0],
        start_position=[9.6, 5.0, 5.0],
        runtime_jitter=[0.6, 0.1, 0.1],
        radius=[0.2, 0.2],
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
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
        assert "build_zone" in data.message
        assert "axis x" in data.message


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
        ("negative_jitter", [-0.1, 0.1, 0.1], [0.25, 0.25], "runtime_jitter"),
        ("negative_radius", [0.1, 0.1, 0.1], [-0.25, 0.25], "radius"),
    ],
)
@pytest.mark.asyncio
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
        goal_zone_min=[1.0, -1.0, 0.0],
        goal_zone_max=[2.0, 1.0, 1.0],
        build_zone_min=[-5.0, -5.0, 0.0],
        build_zone_max=[5.0, 5.0, 15.0],
        start_position=[0.0, 0.0, 5.0],
        runtime_jitter=runtime_jitter,
        radius=radius,
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
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
async def test_int_008_attachment_policy_rejects_legacy_attachment_method():
    """
    INT-008: benchmark_definition.yaml attachment policy must reject legacy
    attachment method values outside the typed fastener/none contract.
    """
    session_id = f"INT-008-ATT-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan = """## 1. Learning Objective

Move the projectile into the goal zone.

## 2. Geometry

- Ground plane
- Guide rails

## 3. Objectives

- Reach the goal zone
"""
    valid_todo = "# TODO\n\n- [x] Planner handoff seeded\n"
    valid_cost = """version: "1.0"
manufactured_parts: []
cots_parts: []
final_assembly: []
totals:
  estimated_unit_cost_usd: 10.0
  estimated_weight_g: 100.0
"""
    minimal_script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    p = Box(10, 10, 10)
    p = p.move(Location((0, 0, 5)))
    p.label = "test_part"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum-6061",
    )
    return p
"""
    invalid_attachment_policy = {
        "objectives": {
            "goal_zone": {"min": [1.0, -1.0, 0.0], "max": [2.0, 1.0, 1.0]},
            "forbid_zones": [],
            "build_zone": {"min": [-5.0, -5.0, 0.0], "max": [5.0, 5.0, 15.0]},
        },
        "benchmark_parts": [
            {
                "part_id": "environment_fixture",
                "label": "environment_fixture",
                "metadata": {
                    "fixed": True,
                    "material_id": "aluminum_6061",
                    "attachment_policy": {
                        "attachment_methods": ["clamp"],
                        "notes": "Legacy invalid method",
                    },
                },
            }
        ],
        "physics": {"backend": "GENESIS"},
        "simulation_bounds": {
            "min": [-30.0, -30.0, -10.0],
            "max": [30.0, 30.0, 30.0],
        },
        "payload": {
            "label": "projectile_ball",
            "shape": "sphere",
            "material_id": "abs",
            "static_randomization": {"radius": [0.25, 0.25]},
            "start_position": [-4.0, 0.0, 0.5],
            "runtime_jitter": [0.1, 0.1, 0.1],
        },
        "constraints": {"max_unit_cost": 50.0, "max_weight_g": 1200.0},
        "randomization": {
            "static_variation_id": "v1.0",
            "runtime_jitter_enabled": True,
        },
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(client, headers, "solution.py", minimal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", invalid_attachment_policy
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
        assert "attachment_methods" in data.message
        assert "fastener" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
async def test_int_008_requires_non_empty_benchmark_parts():
    """
    INT-008: benchmark_definition.yaml must fail closed when benchmark_parts is
    omitted because benchmark-owned fixtures are a required source contract.
    """
    session_id = f"INT-008-PARTS-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan = """## 1. Learning Objective

Move the projectile into the goal zone.

## 2. Geometry

- Ground plane
- Guide rails

## 3. Objectives

- Reach the goal zone
"""
    valid_todo = "# TODO\n\n- [x] Planner handoff seeded\n"
    valid_cost = """version: "1.0"
manufactured_parts: []
cots_parts: []
final_assembly: []
totals:
  estimated_unit_cost_usd: 10.0
  estimated_weight_g: 100.0
"""
    minimal_script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    p = Box(10, 10, 10)
    p = p.move(Location((0, 0, 5)))
    p.label = "test_part"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum-6061",
    )
    return p
"""
    missing_benchmark_parts = {
        "objectives": {
            "goal_zone": {"min": [1.0, -1.0, 0.0], "max": [2.0, 1.0, 1.0]},
            "forbid_zones": [],
            "build_zone": {"min": [-5.0, -5.0, 0.0], "max": [5.0, 5.0, 15.0]},
        },
        "physics": {"backend": "GENESIS"},
        "simulation_bounds": {
            "min": [-30.0, -30.0, -10.0],
            "max": [30.0, 30.0, 30.0],
        },
        "payload": {
            "label": "projectile_ball",
            "shape": "sphere",
            "material_id": "abs",
            "static_randomization": {"radius": [0.25, 0.25]},
            "start_position": [-4.0, 0.0, 0.5],
            "runtime_jitter": [0.1, 0.1, 0.1],
        },
        "constraints": {"max_unit_cost": 50.0, "max_weight_g": 1200.0},
        "randomization": {
            "static_variation_id": "v1.0",
            "runtime_jitter_enabled": True,
        },
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
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
async def test_int_008_submit_requires_explicit_reviewer_stage():
    """/benchmark/submit must fail closed when reviewer_stage is omitted."""
    session_id = f"INT-008-STAGE-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan = """## 1. Learning Objective

Move the projectile into the goal zone.

## 2. Geometry

- Ground plane
- Guide rails

## 3. Objectives

- Reach the goal zone
"""
    valid_todo = "# TODO\n\n- [x] Planner handoff seeded\n"
    valid_cost = """version: "1.0"
manufactured_parts: []
cots_parts: []
final_assembly: []
totals:
  estimated_unit_cost_usd: 10.0
  estimated_weight_g: 100.0
"""
    minimal_script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    p = Box(10, 10, 10)
    p = p.move(Location((0, 0, 5)))
    p.label = "test_part"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum-6061",
    )
    return p
"""
    valid_objectives = {
        "objectives": {
            "goal_zone": {"min": [1.0, -1.0, 0.0], "max": [2.0, 1.0, 1.0]},
            "forbid_zones": [],
            "build_zone": {"min": [-5.0, -5.0, 0.0], "max": [5.0, 5.0, 15.0]},
        },
        "benchmark_parts": _default_benchmark_parts(),
        "physics": {"backend": "GENESIS"},
        "simulation_bounds": {
            "min": [-30.0, -30.0, -10.0],
            "max": [30.0, 30.0, 30.0],
        },
        "payload": {
            "label": "projectile_ball",
            "shape": "sphere",
            "material_id": "abs",
            "static_randomization": {"radius": [0.25, 0.25]},
            "start_position": [-4.0, 0.0, 0.5],
            "runtime_jitter": [0.1, 0.1, 0.1],
        },
        "constraints": {"max_unit_cost": 50.0, "max_weight_g": 1200.0},
        "randomization": {
            "static_variation_id": "v1.0",
            "runtime_jitter_enabled": True,
        },
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
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
        "environment_attachment_contract_invalid",
    ]
)
@pytest.mark.asyncio
async def test_int_008_interactable_benchmark_fixture_round_trips_permission():
    """
    INT-008: explicit interaction permission must survive YAML serialization and
    benchmark handoff validation.
    """
    session_id = f"INT-008-RT-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan = """## 1. Learning Objective

Move the projectile into the goal zone.

## 2. Geometry

- Ground plane
- Guide rails

## 3. Objectives

- Reach the goal zone
"""
    valid_todo = "# TODO\n\n- [x] Planner handoff seeded\n"
    valid_cost = """version: "1.0"
manufactured_parts: []
cots_parts: []
final_assembly: []
environment_drill_operations:
  - target_part_id: environment_fixture
    hole_id: mount_left
    diameter_mm: 4.0
    depth_mm: 8.0
    quantity: 1
totals:
  estimated_unit_cost_usd: 10.0
  estimated_weight_g: 100.0
"""
    benchmark_assembly_definition = """version: "1.0"
units:
  length: "mm"
  volume: "mm3"
  mass: "g"
  currency: "USD"
constraints:
  benchmark_max_unit_cost_usd: 50.0
  benchmark_max_weight_g: 1200.0
  planner_target_max_unit_cost_usd: 45.0
  planner_target_max_weight_g: 1000.0
manufactured_parts: []
cots_parts: []
environment_drill_operations:
  - target_part_id: environment_fixture
    hole_id: mount_left
    diameter_mm: 4.0
    depth_mm: 8.0
    quantity: 1
final_assembly: []
totals:
  estimated_unit_cost_usd: 1.5
  estimated_weight_g: 100.0
  estimate_confidence: "medium"
dfm_suggestions: []
"""
    goal_script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    p = Box(10, 10, 10)
    p = p.move(Location((0, 0, 5)))
    p.label = "test_part"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum-6061",
    )
    return p
"""
    interactable_objectives = {
        "objectives": {
            "goal_zone": {"min": [1.0, -1.0, 0.0], "max": [2.0, 1.0, 1.0]},
            "forbid_zones": [],
            "build_zone": {"min": [-5.0, -5.0, 0.0], "max": [5.0, 5.0, 15.0]},
        },
        "benchmark_parts": [
            {
                "part_id": "environment_fixture",
                "label": "environment_fixture",
                "metadata": {
                    "fixed": True,
                    "allows_engineer_interaction": True,
                    "material_id": "aluminum_6061",
                    "attachment_policy": {
                        "attachment_methods": ["fastener"],
                        "drill_policy": {
                            "allowed": True,
                            "max_hole_count": 1,
                            "diameter_range_mm": [3.0, 5.0],
                            "max_depth_mm": 10.0,
                        },
                    },
                },
            }
        ],
        "physics": {"backend": "GENESIS"},
        "simulation_bounds": {
            "min": [-30.0, -30.0, -10.0],
            "max": [30.0, 30.0, 30.0],
        },
        "payload": {
            "label": "projectile_ball",
            "shape": "sphere",
            "material_id": "abs",
            "static_randomization": {"radius": [0.25, 0.25]},
            "start_position": [-4.0, 0.0, 0.5],
            "runtime_jitter": [0.1, 0.1, 0.1],
        },
        "constraints": {"max_unit_cost": 50.0, "max_weight_g": 1200.0},
        "randomization": {
            "static_variation_id": "v1.0",
            "runtime_jitter_enabled": True,
        },
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(
            client,
            headers,
            "benchmark_assembly_definition.yaml",
            benchmark_assembly_definition,
        )
        await _write_workspace_file(client, headers, "benchmark_script.py", goal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", interactable_objectives
        )

        read_resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/read",
            json=ReadFileRequest(path="benchmark_definition.yaml").model_dump(
                mode="json"
            ),
            headers=headers,
        )
        assert read_resp.status_code == 200, read_resp.text
        benchmark_definition = yaml.safe_load(
            ReadFileResponse.model_validate(read_resp.json()).content
        )
        assert (
            benchmark_definition["benchmark_parts"][0]["metadata"][
                "allows_engineer_interaction"
            ]
            is True
        )

        benchmark_request = BenchmarkToolRequest(
            script_path="benchmark_script.py",
            reviewer_stage=AgentName.BENCHMARK_REVIEWER,
        )
        validate_resp = await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=benchmark_request.model_dump(mode="json"),
            headers=headers,
        )
        assert validate_resp.status_code == 200, validate_resp.text
        validate_data = BenchmarkToolResponse.model_validate(validate_resp.json())
        assert validate_data.success, validate_data.message

        simulate_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json=benchmark_request.model_dump(mode="json"),
            headers=headers,
        )
        assert simulate_resp.status_code == 200, simulate_resp.text
        simulate_data = BenchmarkToolResponse.model_validate(simulate_resp.json())
        assert simulate_data.success, simulate_data.message

        submit_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=benchmark_request.model_dump(mode="json"),
            headers=headers,
        )
        assert submit_resp.status_code == 200, submit_resp.text
        submit_data = BenchmarkToolResponse.model_validate(submit_resp.json())
        assert submit_data.success, submit_data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "environment_attachment_contract_invalid",
    ]
)
@pytest.mark.asyncio
async def test_int_008_missing_interaction_permission_fails_closed_at_handoff():
    """
    INT-008: a benchmark-owned fixture that is used for engineer-facing
    interaction must fail closed when the explicit permission marker is absent.
    """
    session_id = f"INT-008-MISS-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan = """## 1. Learning Objective

Move the projectile into the goal zone.

## 2. Geometry

- Ground plane
- Guide rails

## 3. Objectives

- Reach the goal zone
"""
    valid_todo = "# TODO\n\n- [x] Planner handoff seeded\n"
    valid_cost = """version: "1.0"
manufactured_parts: []
cots_parts: []
final_assembly: []
environment_drill_operations:
  - target_part_id: environment_fixture
    hole_id: mount_left
    diameter_mm: 4.0
    depth_mm: 8.0
    quantity: 1
totals:
  estimated_unit_cost_usd: 10.0
  estimated_weight_g: 100.0
"""
    benchmark_assembly_definition = """version: "1.0"
units:
  length: "mm"
  volume: "mm3"
  mass: "g"
  currency: "USD"
constraints:
  benchmark_max_unit_cost_usd: 50.0
  benchmark_max_weight_g: 1200.0
  planner_target_max_unit_cost_usd: 45.0
  planner_target_max_weight_g: 1000.0
manufactured_parts: []
cots_parts: []
environment_drill_operations:
  - target_part_id: environment_fixture
    hole_id: mount_left
    diameter_mm: 4.0
    depth_mm: 8.0
    quantity: 1
final_assembly: []
totals:
  estimated_unit_cost_usd: 10.0
  estimated_weight_g: 100.0
  estimate_confidence: "medium"
dfm_suggestions: []
"""
    goal_script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    p = Box(10, 10, 10)
    p = p.move(Location((0, 0, 5)))
    p.label = "test_part"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum-6061",
    )
    return p
"""
    missing_permission_objectives = {
        "objectives": {
            "goal_zone": {"min": [1.0, -1.0, 0.0], "max": [2.0, 1.0, 1.0]},
            "forbid_zones": [],
            "build_zone": {"min": [-5.0, -5.0, 0.0], "max": [5.0, 5.0, 15.0]},
        },
        "benchmark_parts": [
            {
                "part_id": "environment_fixture",
                "label": "environment_fixture",
                "metadata": {
                    "fixed": True,
                    "material_id": "aluminum_6061",
                    "attachment_policy": {
                        "attachment_methods": ["fastener"],
                        "drill_policy": {
                            "allowed": True,
                            "max_hole_count": 1,
                            "diameter_range_mm": [3.0, 5.0],
                            "max_depth_mm": 10.0,
                        },
                    },
                },
            }
        ],
        "physics": {"backend": "GENESIS"},
        "simulation_bounds": {
            "min": [-30.0, -30.0, -10.0],
            "max": [30.0, 30.0, 30.0],
        },
        "payload": {
            "label": "projectile_ball",
            "shape": "sphere",
            "material_id": "abs",
            "static_randomization": {"radius": [0.25, 0.25]},
            "start_position": [-4.0, 0.0, 0.5],
            "runtime_jitter": [0.1, 0.1, 0.1],
        },
        "constraints": {"max_unit_cost": 50.0, "max_weight_g": 1200.0},
        "randomization": {
            "static_variation_id": "v1.0",
            "runtime_jitter_enabled": True,
        },
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
        await _write_workspace_file(client, headers, "todo.md", valid_todo)
        await _write_workspace_file(
            client, headers, "assembly_definition.yaml", valid_cost
        )
        await _write_workspace_file(
            client,
            headers,
            "benchmark_assembly_definition.yaml",
            benchmark_assembly_definition,
        )
        await _write_workspace_file(client, headers, "benchmark_script.py", goal_script)
        await _write_workspace_file(
            client, headers, "benchmark_definition.yaml", missing_permission_objectives
        )

        benchmark_request = BenchmarkToolRequest(
            script_path="benchmark_script.py",
            reviewer_stage=AgentName.BENCHMARK_REVIEWER,
        )
        validate_resp = await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=benchmark_request.model_dump(mode="json"),
            headers=headers,
        )
        assert validate_resp.status_code == 200, validate_resp.text
        validate_data = BenchmarkToolResponse.model_validate(validate_resp.json())
        assert validate_data.success, validate_data.message

        simulate_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json=benchmark_request.model_dump(mode="json"),
            headers=headers,
        )
        assert simulate_resp.status_code == 200, simulate_resp.text
        simulate_data = BenchmarkToolResponse.model_validate(simulate_resp.json())
        assert simulate_data.success, simulate_data.message

        submit_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=benchmark_request.model_dump(mode="json"),
            headers=headers,
        )
        assert submit_resp.status_code == 200, submit_resp.text
        submit_data = BenchmarkToolResponse.model_validate(submit_resp.json())
        assert not submit_data.success
        assert "allows_engineer_interaction" in submit_data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "benchmark_definition_yaml_invalid",
        "benchmark_definition_yaml_validation_error",
    ]
)
@pytest.mark.asyncio
async def test_int_008_objectives_semantic_validation_rejects_runtime_envelope_forbid_collision():
    """
    INT-008: benchmark_definition.yaml validation must fail closed when the
    payload's runtime envelope intersects a forbid zone.
    """
    session_id = f"INT-008-FORBID-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan = """## 1. Learning Objective

Move the projectile into the goal zone.

## 2. Geometry

- Ground plane
- Guide rails

## 3. Objectives

- Reach the goal zone
"""
    valid_todo = "# TODO\n\n- [x] Planner handoff seeded\n"
    valid_cost = """version: "1.0"
manufactured_parts: []
cots_parts: []
final_assembly: []
totals:
  estimated_unit_cost_usd: 10.0
  estimated_weight_g: 100.0
"""
    minimal_script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    p = Box(10, 10, 10)
    p = p.move(Location((0, 0, 5)))
    p.label = "test_part"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum-6061",
    )
    return p
"""

    forbid_collision_objectives = {
        "objectives": {
            "goal_zone": {"min": [3.0, 3.0, 3.0], "max": [4.0, 4.0, 4.0]},
            "forbid_zones": [
                {
                    "name": "center_block",
                    "min": [-1.0, -1.0, 0.0],
                    "max": [1.0, 1.0, 2.0],
                }
            ],
            "build_zone": {"min": [-5.0, -5.0, 0.0], "max": [5.0, 5.0, 10.0]},
        },
        "physics": {"backend": "GENESIS"},
        "simulation_bounds": {
            "min": [-30.0, -30.0, -10.0],
            "max": [30.0, 30.0, 30.0],
        },
        "payload": {
            "label": "projectile_ball",
            "shape": "sphere",
            "material_id": "abs",
            "static_randomization": {"radius": [0.25, 0.25]},
            "start_position": [0.0, 0.0, 1.0],
            "runtime_jitter": [0.5, 0.5, 0.5],
        },
        "constraints": {"max_unit_cost": 50.0, "max_weight_g": 1200.0},
        "benchmark_parts": _default_benchmark_parts(),
        "randomization": {
            "static_variation_id": "v1.0",
            "runtime_jitter_enabled": True,
        },
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
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
async def test_int_008_objectives_semantic_validation_rejects_negative_runtime_ranges():
    """
    INT-008: benchmark_definition.yaml validation must fail closed on negative
    runtime jitter and static randomization radius values.
    """
    session_id = f"INT-008-RANGE-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    valid_plan = """## 1. Learning Objective

Move the projectile into the goal zone.

## 2. Geometry

- Ground plane
- Guide rails

## 3. Objectives

- Reach the goal zone
"""
    valid_todo = "# TODO\n\n- [x] Planner handoff seeded\n"
    valid_cost = """version: "1.0"
manufactured_parts: []
cots_parts: []
final_assembly: []
totals:
  estimated_unit_cost_usd: 10.0
  estimated_weight_g: 100.0
"""
    minimal_script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    p = Box(10, 10, 10)
    p = p.move(Location((0, 0, 5)))
    p.label = "test_part"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum-6061",
    )
    return p
"""

    base_objectives = {
        "objectives": {
            "goal_zone": {"min": [3.0, 3.0, 3.0], "max": [4.0, 4.0, 4.0]},
            "forbid_zones": [],
            "build_zone": {"min": [-5.0, -5.0, 0.0], "max": [5.0, 5.0, 10.0]},
        },
        "physics": {"backend": "GENESIS"},
        "simulation_bounds": {
            "min": [-30.0, -30.0, -10.0],
            "max": [30.0, 30.0, 30.0],
        },
        "payload": {
            "label": "projectile_ball",
            "shape": "sphere",
            "material_id": "abs",
            "static_randomization": {"radius": [0.25, 0.25]},
            "start_position": [0.0, 0.0, 1.0],
            "runtime_jitter": [0.5, 0.5, 0.5],
        },
        "constraints": {"max_unit_cost": 50.0, "max_weight_g": 1200.0},
        "benchmark_parts": _default_benchmark_parts(),
        "randomization": {
            "static_variation_id": "v1.0",
            "runtime_jitter_enabled": True,
        },
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        # 1. Negative runtime jitter must fail closed.
        negative_jitter = yaml.safe_load(yaml.safe_dump(base_objectives))
        negative_jitter["payload"]["runtime_jitter"] = [-0.5, 0.5, 0.5]
        await _write_workspace_file(client, headers, "plan.md", valid_plan)
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
        assert "runtime_jitter" in data.message

        # 2. Negative static randomization radius must also fail closed.
        negative_radius = yaml.safe_load(yaml.safe_dump(base_objectives))
        negative_radius["payload"]["static_randomization"]["radius"] = [
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
        assert "static_randomization.radius" in data.message


def _drillable_benchmark_parts(
    *,
    max_hole_count: int = 4,
    diameter_range_mm: list[float] | None = None,
    max_depth_mm: float = 10.0,
):
    """Benchmark parts with an interactable fixture that permits drilling."""
    return [
        {
            "part_id": "environment_fixture",
            "label": "environment_fixture",
            "metadata": {
                "fixed": True,
                "allows_engineer_interaction": True,
                "material_id": "aluminum_6061",
                "attachment_policy": {
                    "attachment_methods": ["fastener"],
                    "drill_policy": {
                        "allowed": True,
                        "max_hole_count": max_hole_count,
                        "diameter_range_mm": diameter_range_mm or [3.0, 6.0],
                        "max_depth_mm": max_depth_mm,
                    },
                },
            },
        }
    ]


def _drillable_benchmark_definition(benchmark_parts: list[dict]) -> dict:
    """Build a valid benchmark_definition.yaml payload with configurable parts."""
    return {
        "objectives": {
            "goal_zone": {"min": [1.0, -1.0, 0.0], "max": [2.0, 1.0, 1.0]},
            "forbid_zones": [],
            "build_zone": {"min": [-5.0, -5.0, 0.0], "max": [5.0, 5.0, 15.0]},
        },
        "benchmark_parts": benchmark_parts,
        "physics": {"backend": "GENESIS"},
        "simulation_bounds": {
            "min": [-30.0, -30.0, -10.0],
            "max": [30.0, 30.0, 30.0],
        },
        "payload": {
            "label": "projectile_ball",
            "shape": "sphere",
            "material_id": "abs",
            "static_randomization": {"radius": [0.25, 0.25]},
            "start_position": [-4.0, 0.0, 0.5],
            "runtime_jitter": [0.1, 0.1, 0.1],
        },
        "constraints": {"max_unit_cost": 50.0, "max_weight_g": 1200.0},
        "randomization": {
            "static_variation_id": "v1.0",
            "runtime_jitter_enabled": True,
        },
    }


def _assembly_with_drill_ops(drill_operations: list[dict]) -> str:
    """Assembly definition YAML with specified environment_drill_operations."""
    return yaml.dump(
        {
            "version": "1.0",
            "units": {"length": "mm", "volume": "mm3", "mass": "g", "currency": "USD"},
            "constraints": {
                "benchmark_max_unit_cost_usd": 50.0,
                "benchmark_max_weight_g": 1200.0,
                "planner_target_max_unit_cost_usd": 45.0,
                "planner_target_max_weight_g": 1000.0,
            },
            "manufactured_parts": [],
            "cots_parts": [],
            "environment_drill_operations": drill_operations,
            "final_assembly": [],
            "totals": {
                "estimated_unit_cost_usd": 10.0,
                "estimated_weight_g": 100.0,
                "estimate_confidence": "medium",
            },
            "dfm_suggestions": [],
        }
    )


_DRILL_TEST_PLAN = """## 1. Learning Objective

Move the projectile into the goal zone.

## 2. Geometry

- Ground plane
- Guide rails

## 3. Objectives

- Reach the goal zone
"""
_DRILL_TEST_TODO = "# TODO\n\n- [x] Planner handoff seeded\n"
_DRILL_TEST_SCRIPT = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    p = Box(10, 10, 10)
    p = p.move(Location((0, 0, 5)))
    p.label = "test_part"
    p.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum-6061",
    )
    return p
"""


async def _setup_drill_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    benchmark_definition: dict,
    assembly_definition_yaml: str,
) -> None:
    """Write the common workspace files for drilling contract tests."""
    await _write_workspace_file(client, headers, "plan.md", _DRILL_TEST_PLAN)
    await _write_workspace_file(client, headers, "todo.md", _DRILL_TEST_TODO)
    await _write_workspace_file(
        client, headers, "benchmark_script.py", _DRILL_TEST_SCRIPT
    )
    await _write_workspace_file(
        client, headers, "benchmark_definition.yaml", benchmark_definition
    )
    await _write_workspace_file(
        client,
        headers,
        "benchmark_assembly_definition.yaml",
        assembly_definition_yaml,
    )


async def _validate_and_simulate(
    client: httpx.AsyncClient,
    headers: dict[str, str],
) -> None:
    """Run /benchmark/validate and /benchmark/simulate so submit prerequisites pass."""
    benchmark_request = BenchmarkToolRequest(
        script_path="benchmark_script.py",
        reviewer_stage=AgentName.BENCHMARK_REVIEWER,
    )
    validate_resp = await client.post(
        f"{WORKER_LIGHT_URL}/benchmark/validate",
        json=benchmark_request.model_dump(mode="json"),
        headers=headers,
    )
    assert validate_resp.status_code == 200, validate_resp.text
    validate_data = BenchmarkToolResponse.model_validate(validate_resp.json())
    assert validate_data.success, validate_data.message

    simulate_resp = await client.post(
        f"{WORKER_HEAVY_URL}/benchmark/simulate",
        json=benchmark_request.model_dump(mode="json"),
        headers=headers,
    )
    assert simulate_resp.status_code == 200, simulate_resp.text
    simulate_data = BenchmarkToolResponse.model_validate(simulate_resp.json())
    assert simulate_data.success, simulate_data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "environment_attachment_contract_invalid",
    ]
)
@pytest.mark.asyncio
async def test_int_008_drilling_contract_rejects_exceeding_hole_count():
    """
    INT-008: drilling operations that exceed drill_policy.max_hole_count must
    fail closed at benchmark submission.
    """
    session_id = f"INT-008-HOLES-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    benchmark_def = _drillable_benchmark_definition(
        _drillable_benchmark_parts(max_hole_count=1)
    )

    # Declare 2 holes but policy allows only 1.
    assembly_yaml = _assembly_with_drill_ops(
        [
            {
                "target_part_id": "environment_fixture",
                "hole_id": "mount_left",
                "diameter_mm": 4.0,
                "depth_mm": 8.0,
                "quantity": 1,
            },
            {
                "target_part_id": "environment_fixture",
                "hole_id": "mount_right",
                "diameter_mm": 4.0,
                "depth_mm": 8.0,
                "quantity": 1,
            },
        ]
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _setup_drill_workspace(
            client,
            headers,
            benchmark_definition=benchmark_def,
            assembly_definition_yaml=assembly_yaml,
        )
        await _validate_and_simulate(client, headers)

        submit_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="benchmark_script.py",
                reviewer_stage=AgentName.BENCHMARK_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert submit_resp.status_code == 200, submit_resp.text
        data = BenchmarkToolResponse.model_validate(submit_resp.json())
        assert not data.success
        assert "max_hole_count" in data.message
        assert "environment_fixture" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "environment_attachment_contract_invalid",
    ]
)
@pytest.mark.asyncio
async def test_int_008_drilling_contract_rejects_diameter_out_of_range():
    """
    INT-008: drilling operations with diameter_mm outside the declared
    drill_policy.diameter_range_mm must fail closed at benchmark submission.
    """
    session_id = f"INT-008-DIAM-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    # Policy allows [3.0, 6.0] mm diameter.
    benchmark_def = _drillable_benchmark_definition(
        _drillable_benchmark_parts(diameter_range_mm=[3.0, 6.0])
    )

    # Declare a hole with 8.0mm diameter — outside the allowed range.
    assembly_yaml = _assembly_with_drill_ops(
        [
            {
                "target_part_id": "environment_fixture",
                "hole_id": "mount_oversize",
                "diameter_mm": 8.0,
                "depth_mm": 5.0,
                "quantity": 1,
            }
        ]
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _setup_drill_workspace(
            client,
            headers,
            benchmark_definition=benchmark_def,
            assembly_definition_yaml=assembly_yaml,
        )
        await _validate_and_simulate(client, headers)

        submit_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="benchmark_script.py",
                reviewer_stage=AgentName.BENCHMARK_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert submit_resp.status_code == 200, submit_resp.text
        data = BenchmarkToolResponse.model_validate(submit_resp.json())
        assert not data.success
        assert "diameter_mm" in data.message
        assert "mount_oversize" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "environment_attachment_contract_invalid",
    ]
)
@pytest.mark.asyncio
async def test_int_008_drilling_contract_rejects_depth_exceeding_max():
    """
    INT-008: drilling operations with depth_mm exceeding drill_policy.max_depth_mm
    must fail closed at benchmark submission.
    """
    session_id = f"INT-008-DEPTH-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    # Policy allows max 10.0mm depth.
    benchmark_def = _drillable_benchmark_definition(
        _drillable_benchmark_parts(max_depth_mm=10.0)
    )

    # Declare a hole with 15.0mm depth — exceeds the limit.
    assembly_yaml = _assembly_with_drill_ops(
        [
            {
                "target_part_id": "environment_fixture",
                "hole_id": "mount_deep",
                "diameter_mm": 4.0,
                "depth_mm": 15.0,
                "quantity": 1,
            }
        ]
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _setup_drill_workspace(
            client,
            headers,
            benchmark_definition=benchmark_def,
            assembly_definition_yaml=assembly_yaml,
        )
        await _validate_and_simulate(client, headers)

        submit_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="benchmark_script.py",
                reviewer_stage=AgentName.BENCHMARK_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert submit_resp.status_code == 200, submit_resp.text
        data = BenchmarkToolResponse.model_validate(submit_resp.json())
        assert not data.success
        assert "depth_mm" in data.message
        assert "max_depth_mm" in data.message


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "environment_attachment_contract_invalid",
    ]
)
@pytest.mark.asyncio
async def test_int_008_no_attachment_policy_defaults_to_non_drillable():
    """
    INT-008: a benchmark fixture with no attachment_policy must cause drill
    operations to fail closed with an explicit 'non-drillable by default'
    message at benchmark submission.
    """
    session_id = f"INT-008-NOATT-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    # Fixture allows interaction but has NO attachment_policy.
    benchmark_parts = [
        {
            "part_id": "environment_fixture",
            "label": "environment_fixture",
            "metadata": {
                "fixed": True,
                "allows_engineer_interaction": True,
                "material_id": "aluminum_6061",
            },
        }
    ]
    benchmark_def = _drillable_benchmark_definition(benchmark_parts)

    # Attempt to drill into the fixture that has no policy.
    assembly_yaml = _assembly_with_drill_ops(
        [
            {
                "target_part_id": "environment_fixture",
                "hole_id": "mount_attempt",
                "diameter_mm": 4.0,
                "depth_mm": 8.0,
                "quantity": 1,
            }
        ]
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _setup_drill_workspace(
            client,
            headers,
            benchmark_definition=benchmark_def,
            assembly_definition_yaml=assembly_yaml,
        )
        await _validate_and_simulate(client, headers)

        submit_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/submit",
            json=BenchmarkToolRequest(
                script_path="benchmark_script.py",
                reviewer_stage=AgentName.BENCHMARK_REVIEWER,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert submit_resp.status_code == 200, submit_resp.text
        data = BenchmarkToolResponse.model_validate(submit_resp.json())
        assert not data.success
        assert "non-drillable by default" in data.message
        assert "environment_fixture" in data.message
