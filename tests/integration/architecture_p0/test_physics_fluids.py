import os
import time

import httpx
import pytest
import yaml

from shared.enums import FluidEvalAt, FluidShapeType
from shared.models.schemas import (
    BenchmarkDefinition,
    BoundingBox,
    Constraints,
    FlowRateObjective,
    FluidContainmentObjective,
    FluidDefinition,
    FluidProperties,
    FluidVolume,
    MovedObject,
    ObjectivesSection,
    PhysicsConfig,
)
from shared.observability.schemas import SimulationBackendSelectedEvent
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.schema import (
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    WriteFileRequest,
)
from tests.integration.backend_utils import skip_unless_genesis

# Constants
WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
WORKER_HEAVY_URL = os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002")
CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")
pytestmark = pytest.mark.xdist_group(name="physics_sims")


def _default_benchmark_parts():
    return [
        {
            "part_id": "environment_fixture",
            "label": "environment_fixture",
            "metadata": {"fixed": True, "material_id": "aluminum_6061"},
        }
    ]


def _event_get(event, key: str, default=None):
    if isinstance(event, dict):
        return event.get(key, default)
    if hasattr(event, "get"):
        return event.get(key, default)
    return getattr(event, key, default)


def _event_as_dict(event):
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")
    return {"event_type": _event_get(event, "event_type")}


async def _require_service(client: httpx.AsyncClient, name: str, url: str):
    try:
        resp = await client.get(f"{url}/health", timeout=5.0)
        resp.raise_for_status()
    except Exception:
        pytest.skip(f"{name} is not reachable at {url}")


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_101_physics_backend_selection():
    """INT-101: Verify physics backend selection and event emission."""
    skip_unless_genesis("INT-101 requires Genesis FEM/backend metadata.")
    async with httpx.AsyncClient(timeout=300.0) as client:
        await _require_service(client, "worker-light", WORKER_LIGHT_URL)
        await _require_service(client, "worker-heavy", WORKER_HEAVY_URL)
        session_id = f"test-int-101-{int(time.time())}"

        # 1. Setup benchmark_definition.yaml with Genesis backend
        objectives = BenchmarkDefinition(
            physics=PhysicsConfig(
                backend=SimulatorBackendType.GENESIS,
                fem_enabled=True,
                compute_target="cpu",
            ),
            objectives=ObjectivesSection(
                goal_zone=BoundingBox(min=(5, 5, 5), max=(7, 7, 7)),
                build_zone=BoundingBox(min=(-10, -10, -10), max=(10, 10, 10)),
            ),
            simulation_bounds=BoundingBox(min=(-10, -10, -10), max=(10, 10, 10)),
            payload=MovedObject(
                label="test_obj",
                shape="sphere",
                material_id="aluminum_6061",
                start_position=(0, 0, 5),
                runtime_jitter=(0, 0, 0),
            ),
            constraints=Constraints(max_unit_cost=100.0, max_weight_g=10.0),
            benchmark_parts=_default_benchmark_parts(),
        )
        write_obj_req = WriteFileRequest(
            path="benchmark_definition.yaml",
            content=yaml.dump(objectives.model_dump(mode="json")),
            overwrite=True,
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_obj_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        # 2. Simple box script
        script = """
from build123d import *
from shared.models.schemas import PartMetadata
def build():
    p = Box(1, 1, 1)
    p.label = "test_part"
    p.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return p
"""
        write_script_req = WriteFileRequest(
            path="script.py", content=script, overwrite=True
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_script_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        # 3. Simulate
        sim_req = BenchmarkToolRequest(script_path="script.py", smoke_test_mode=True)
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json=sim_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=900.0,
        )
        assert resp.status_code == 200
        data = BenchmarkToolResponse.model_validate(resp.json())
        events = data.events

        # Verify event emission
        event_dict = next(
            (
                _event_as_dict(e)
                for e in events
                if _event_get(e, "event_type") == "simulation_backend_selected"
            ),
            None,
        )
        assert event_dict is not None, "Missing simulation_backend_selected event"

        event = SimulationBackendSelectedEvent.model_validate(event_dict)
        assert event.backend.lower() == "genesis"
        assert event.fem_enabled is True
        assert event.compute_target == "cpu"


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_101b_explicit_genesis_backend_is_respected_without_fem():
    """INT-101B: Explicit GENESIS backend must not be overwritten by heuristics."""
    skip_unless_genesis("INT-101B requires Genesis backend availability.")
    async with httpx.AsyncClient(timeout=300.0) as client:
        await _require_service(client, "worker-light", WORKER_LIGHT_URL)
        await _require_service(client, "worker-heavy", WORKER_HEAVY_URL)
        session_id = f"test-int-101b-{int(time.time())}"

        objectives = BenchmarkDefinition(
            physics=PhysicsConfig(backend=SimulatorBackendType.GENESIS),
            objectives=ObjectivesSection(
                goal_zone=BoundingBox(min=(5, 5, 5), max=(7, 7, 7)),
                build_zone=BoundingBox(min=(-10, -10, -10), max=(10, 10, 10)),
            ),
            simulation_bounds=BoundingBox(min=(-10, -10, -10), max=(10, 10, 10)),
            payload=MovedObject(
                label="test_obj",
                shape="sphere",
                material_id="aluminum_6061",
                start_position=(0, 0, 5),
                runtime_jitter=(0, 0, 0),
            ),
            constraints=Constraints(max_unit_cost=100.0, max_weight_g=10.0),
            benchmark_parts=_default_benchmark_parts(),
        )
        write_obj_req = WriteFileRequest(
            path="benchmark_definition.yaml",
            content=yaml.dump(objectives.model_dump(mode="json")),
            overwrite=True,
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_obj_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        script = """
from build123d import *
from shared.models.schemas import PartMetadata
def build():
    p = Box(1, 1, 1)
    p.label = "test_part"
    p.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return p
"""
        write_script_req = WriteFileRequest(
            path="script.py", content=script, overwrite=True
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_script_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        sim_req = BenchmarkToolRequest(script_path="script.py", smoke_test_mode=True)
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json=sim_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=900.0,
        )
        assert resp.status_code == 200
        data = BenchmarkToolResponse.model_validate(resp.json())
        event_dict = next(
            (
                _event_as_dict(e)
                for e in data.events
                if _event_get(e, "event_type") == "simulation_backend_selected"
            ),
            None,
        )
        assert event_dict is not None, "Missing simulation_backend_selected event"
        event = SimulationBackendSelectedEvent.model_validate(event_dict)
        assert event.backend.lower() == "genesis"
        assert event.fem_enabled is False


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_112_mujoco_backward_compat():
    """INT-112: Verify MuJoCo ignores fluid/FEM config."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"test-int-112-{int(time.time())}"

        # Setup objectives with MuJoCo but include fluid objectives
        objectives = BenchmarkDefinition(
            physics=PhysicsConfig(
                backend=SimulatorBackendType.GENESIS
            ),  # Genesis but we check MuJoCo behavior if we toggle it
            objectives=ObjectivesSection(
                goal_zone=BoundingBox(min=(5, 5, 5), max=(7, 7, 7)),
                build_zone=BoundingBox(min=(-10, -10, -10), max=(10, 10, 10)),
                fluid_objectives=[
                    FluidContainmentObjective(
                        fluid_id="water",
                        containment_zone=BoundingBox(min=(-1, -1, -1), max=(1, 1, 1)),
                        threshold=0.9,
                    )
                ],
            ),
            simulation_bounds=BoundingBox(min=(-10, -10, -10), max=(10, 10, 10)),
            payload=MovedObject(
                label="obj",
                shape="sphere",
                material_id="aluminum_6061",
                start_position=(0, 0, 0),
                runtime_jitter=(0, 0, 0),
            ),
            constraints=Constraints(max_unit_cost=100.0, max_weight_g=10.0),
            benchmark_parts=_default_benchmark_parts(),
        )
        req_write_obj = WriteFileRequest(
            path="benchmark_definition.yaml",
            content=yaml.dump(objectives.model_dump(mode="json")),
            overwrite=True,
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=req_write_obj.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        req_write_script = WriteFileRequest(
            path="script.py",
            content="""
from build123d import *
from shared.models.schemas import PartMetadata
def build():
    p = Box(1, 1, 1)
    p.label = "test_part"
    p.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return p
""",
            overwrite=True,
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=req_write_script.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        sim_req = BenchmarkToolRequest(
            script_path="script.py",
            smoke_test_mode=True,
            backend=SimulatorBackendType.MUJOCO,
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json=sim_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=900.0,
        )
        assert resp.status_code == 200
        data = BenchmarkToolResponse.model_validate(resp.json())

        # Should succeed despite fluid config (as it's ignored)
        fluid_metrics = data.artifacts.fluid_metrics
        assert len(fluid_metrics) == 0, "Fluid metrics should be empty for MuJoCo"
