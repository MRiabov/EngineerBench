import os
import uuid

import httpx
import pytest
import yaml

from controller.clients.worker import WorkerClient
from controller.middleware.remote_fs import RemoteFilesystemMiddleware
from controller.persistence.db import get_sessionmaker
from controller.persistence.models import Episode
from controller.utils import get_episode_id
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName, EpisodeStatus
from shared.models.schemas import (
    BenchmarkDefinition,
    BenchmarkPartDefinition,
    BenchmarkPartMetadata,
    BoundingBox,
    Constraints,
    ObjectivesSection,
    Payload,
    StaticRandomization,
)
from shared.workers.schema import ExecuteRequest, ExecuteResponse, WriteFileRequest

WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")


def _default_benchmark_parts():
    return [
        {
            "part_id": "environment_fixture",
            "label": "environment_fixture",
            "metadata": {
                "is_fixed": True,
                "material_id": "aluminum_6061",
            },
        }
    ]


def _runtime_validate_command() -> str:
    return "python benchmark_script.py"


async def _seed_current_role_manifest(
    client: httpx.AsyncClient,
    *,
    session_id: str,
    agent_name: AgentName = AgentName.BENCHMARK_CODER,
) -> None:
    resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path=".manifests/current_role.json",
            content=current_role_manifest_json(agent_name),
            overwrite=True,
            bypass_agent_permissions=True,
        ).model_dump(mode="json"),
        headers={
            "X-Session-ID": session_id,
            "X-System-FS-Bypass": "1",
        },
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-024")
async def test_int_024_execute_command_uses_agent_policy_timeout_by_default():
    """
    INT-024: controller execute_command must inherit the agent execution
    timeout policy instead of silently falling back to a stale 30s default.
    """
    session_id = f"INT-024-TIMEOUT-{uuid.uuid4().hex[:8]}"
    episode_id = get_episode_id(session_id)
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        db.add(
            Episode(
                id=episode_id,
                task="integration-timeout-check",
                status=EpisodeStatus.RUNNING,
                metadata_vars={},
            )
        )
        await db.commit()

    fs = RemoteFilesystemMiddleware(
        client=WorkerClient(
            base_url=WORKER_LIGHT_URL,
            session_id=session_id,
            heavy_url=os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002"),
        ),
        agent_role=AgentName.BENCHMARK_CODER,
    )

    benchmark_coder_policy = fs.policy.get_execution_policy(AgentName.BENCHMARK_CODER)
    engineer_execution_reviewer_policy = fs.policy.get_execution_policy(
        AgentName.ENGINEER_EXECUTION_REVIEWER
    )

    assert benchmark_coder_policy.timeout_seconds == 450
    assert engineer_execution_reviewer_policy.timeout_seconds == 90

    result = await fs.run_command("sleep 1; printf 'LONG_COMMAND_OK\\n'")

    assert result.timed_out is False
    assert result.exit_code == 0
    assert "LONG_COMMAND_OK" in result.stdout


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-024")
async def test_int_024_runtime_execute_masks_host_session_root_as_workspace():
    """
    INT-024: shell execution must expose the canonical `/workspace` alias
    rather than leaking the host session directory into model-visible output.
    """
    session_id = f"INT-024-PWD-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    async with httpx.AsyncClient(timeout=120.0) as client:
        exec_resp = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code="pwd",
                timeout=30,
            ).model_dump(mode="json"),
            headers=headers,
            timeout=60.0,
        )
        assert exec_resp.status_code == 200, exec_resp.text
        data = ExecuteResponse.model_validate(exec_resp.json())
        assert data.exit_code == 0
        assert data.stdout.strip() == "/workspace"
        assert "/tmp/pb-sessions" not in data.stdout


@pytest.mark.integration_p0
@pytest.mark.xdist_group(name="physics_sims")
@pytest.mark.asyncio
@pytest.mark.int_id("INT-024")
async def test_int_024_runtime_execute_reaches_benchmark_validate_toolchain():
    """
    INT-024: benchmark validation remains reachable from the light-worker
    runtime via direct utils.submission.validate_benchmark() calls inside the authored
    script during execute_command-equivalent execution, without
    host-resolution failures.
    """
    session_id = f"INT-024-RT-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    script = """
from build123d import Box, Location
from utils.metadata import PartMetadata
from utils.submission import validate_benchmark

def build():
    p = Box(4, 4, 4).move(Location((0, 0, 4)))
    p.label = "target_box"
    p.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return p

result = build()
success, message = validate_benchmark(result)
print(f"VALIDATE_SUCCESS={success}")
print(f"VALIDATE_MESSAGE={message}")
"""

    invalid_objectives = BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(min_mm=(0.0, 0.0, 0.0), max_mm=(10.0, 10.0, 10.0)),
            forbid_zones=[
                {
                    "name": "goal_overlap",
                    "min_mm": (5.0, 5.0, 5.0),
                    "max_mm": (12.0, 12.0, 12.0),
                }
            ],
            build_zone_mm=BoundingBox(
                min_mm=(-20.0, -20.0, 0.0), max_mm=(20.0, 20.0, 30.0)
            ),
        ),
        benchmark_parts=_default_benchmark_parts(),
        simulation_bounds_mm=BoundingBox(
            min_mm=(-50.0, -50.0, -10.0), max_mm=(50.0, 50.0, 50.0)
        ),
        payload=Payload(
            label="target_box",
            shape="sphere",
            material_id="aluminum_6061",
            start_position_mm=(0.0, 0.0, 4.0),
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
    )

    valid_objectives = BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(min_mm=(8.0, 8.0, 0.0), max_mm=(12.0, 12.0, 8.0)),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-20.0, -20.0, 0.0), max_mm=(20.0, 20.0, 30.0)
            ),
        ),
        benchmark_parts=_default_benchmark_parts(),
        simulation_bounds_mm=BoundingBox(
            min_mm=(-50.0, -50.0, -10.0), max_mm=(50.0, 50.0, 50.0)
        ),
        payload=Payload(
            label="target_box",
            shape="sphere",
            material_id="aluminum_6061",
            start_position_mm=(0.0, 0.0, 4.0),
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _seed_current_role_manifest(client, session_id=session_id)
        write_script = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_script.py",
                content=script,
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_script.status_code == 200, write_script.text

        write_invalid = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_definition.yaml",
                content=yaml.dump(invalid_objectives.model_dump(mode="json")),
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_invalid.status_code == 200, write_invalid.text

        invalid_exec = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code=_runtime_validate_command(),
                timeout=120,
            ).model_dump(mode="json"),
            headers=headers,
            timeout=180.0,
        )
        assert invalid_exec.status_code == 200, invalid_exec.text
        invalid_data = ExecuteResponse.model_validate(invalid_exec.json())
        assert invalid_data.exit_code == 0
        assert "VALIDATE_SUCCESS=False" in invalid_data.stdout
        assert "goal_zone_mm overlaps forbid zone" in invalid_data.stdout
        assert "Temporary failure in name resolution" not in invalid_data.stdout

        write_valid = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_definition.yaml",
                content=yaml.dump(valid_objectives.model_dump(mode="json")),
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_valid.status_code == 200, write_valid.text

        valid_exec = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code=_runtime_validate_command(),
                timeout=120,
            ).model_dump(mode="json"),
            headers=headers,
            timeout=180.0,
        )
        assert valid_exec.status_code == 200, valid_exec.text
        valid_data = ExecuteResponse.model_validate(valid_exec.json())
        assert valid_data.exit_code == 0
        assert "VALIDATE_SUCCESS=True" in valid_data.stdout
        assert "Temporary failure in name resolution" not in valid_data.stdout


@pytest.mark.integration_p0
@pytest.mark.xdist_group(name="physics_sims")
@pytest.mark.asyncio
@pytest.mark.int_id("INT-024")
async def test_int_024_runtime_execute_rejects_startup_overlap_with_spawned_payload():
    """
    INT-024: benchmark validation must fail closed when a benchmark fixture
    overlaps the runtime-spawned payload at startup.
    """
    session_id = f"INT-024-OVR-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    overlap_script = """
from build123d import Box, Location
from utils.submission import validate_benchmark

def build():
    p = Box(12, 12, 12)
    p = p.move(Location((0, 0, 5)))
    p.label = "startup_fixture"
    return p

result = build()
success, message = validate_benchmark(result)
print(f"VALIDATE_SUCCESS={success}")
print(f"VALIDATE_MESSAGE={message}")
"""

    overlap_objectives = BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(
                min_mm=(20.0, 20.0, 0.0), max_mm=(24.0, 24.0, 4.0)
            ),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-20.0, -20.0, 0.0), max_mm=(20.0, 20.0, 30.0)
            ),
        ),
        benchmark_parts=[
            BenchmarkPartDefinition(
                part_id="environment_fixture",
                label="environment_fixture",
                metadata=BenchmarkPartMetadata(
                    is_fixed=True,
                    material_id="aluminum_6061",
                ),
            )
        ],
        simulation_bounds_mm=BoundingBox(
            min_mm=(-50.0, -50.0, -10.0), max_mm=(50.0, 50.0, 50.0)
        ),
        payload=Payload(
            label="projectile_ball",
            shape="sphere",
            material_id="abs",
            static_randomization=StaticRandomization(radius_mm=(0.25, 0.25)),
            start_position_mm=(0.0, 0.0, 5.0),
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _seed_current_role_manifest(client, session_id=session_id)
        write_script = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_script.py",
                content=overlap_script,
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_script.status_code == 200, write_script.text

        write_objectives = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_definition.yaml",
                content=yaml.dump(overlap_objectives.model_dump(mode="json")),
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_objectives.status_code == 200, write_objectives.text

        exec_resp = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code=_runtime_validate_command(),
                timeout=120,
            ).model_dump(mode="json"),
            headers=headers,
            timeout=180.0,
        )
        assert exec_resp.status_code == 200, exec_resp.text
        data = ExecuteResponse.model_validate(exec_resp.json())
        assert data.exit_code == 0
        assert "VALIDATE_SUCCESS=False" in data.stdout
        assert "payload start pose intersects benchmark geometry" in data.stdout


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-024")
async def test_int_024_runtime_validate_rejects_transient_shell_state_mismatch():
    """
    INT-024: utils.submission.validate_benchmark() must fail closed when the live
    compound differs from the persisted benchmark_script.py semantic signature.
    """
    session_id = f"INT-024-SIG-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    persisted_script = """
from build123d import Box

def build():
    return Box(4, 4, 4)

result = build()
"""

    runtime_code = """python3 - <<'PY'
from build123d import Box
from utils.submission import validate_benchmark

result = Box(5, 5, 5)
success, message = validate_benchmark(result)
print(f"VALIDATE_SUCCESS={success}")
print(f"VALIDATE_MESSAGE={message}")
PY
"""

    async with httpx.AsyncClient(timeout=120.0) as client:
        await _seed_current_role_manifest(client, session_id=session_id)
        write_script = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_script.py",
                content=persisted_script,
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
            timeout=60.0,
        )
        assert write_script.status_code == 200, write_script.text

        exec_resp = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code=runtime_code,
                timeout=60,
            ).model_dump(mode="json"),
            headers=headers,
            timeout=90.0,
        )
        assert exec_resp.status_code == 200, exec_resp.text
        data = ExecuteResponse.model_validate(exec_resp.json())
        assert data.exit_code == 0
        assert "VALIDATE_SUCCESS=False" in data.stdout
        assert "persisted script semantic signature" in data.stdout


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-024")
async def test_int_024_runtime_validate_rejects_parent_only_fixed_metadata():
    """
    INT-024: benchmark validation fails closed when a parent Compound is marked
    fixed but the static child fixtures themselves are left unfixed.
    """
    session_id = f"INT-024-FIX-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    script = """
from build123d import Align, Box, BuildPart, Compound
from utils.metadata import CompoundMetadata, PartMetadata
from utils.submission import validate_benchmark

def build():
    with BuildPart() as ground_builder:
        Box(4, 4, 0.2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ground = ground_builder.part
    ground.label = "ground_plane"
    ground.metadata = PartMetadata(material_id="hdpe")

    with BuildPart() as ball_builder:
        Box(0.4, 0.4, 0.4, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ball = ball_builder.part
    ball.label = "target_box"
    ball.metadata = PartMetadata(material_id="steel_bearing", is_fixed=False)

    benchmark = Compound(children=[ground, ball])
    benchmark.label = "benchmark_assembly"
    benchmark.metadata = CompoundMetadata(is_fixed=True)
    return benchmark

result = build()
success, message = validate_benchmark(result)
print(f"VALIDATE_SUCCESS={success}")
print(f"VALIDATE_MESSAGE={message}")
"""

    objectives = BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(min_mm=(8.0, 8.0, 0.0), max_mm=(12.0, 12.0, 8.0)),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-20.0, -20.0, 0.0), max_mm=(20.0, 20.0, 30.0)
            ),
        ),
        benchmark_parts=_default_benchmark_parts(),
        simulation_bounds_mm=BoundingBox(
            min_mm=(-50.0, -50.0, -10.0), max_mm=(50.0, 50.0, 50.0)
        ),
        payload=Payload(
            label="target_box",
            shape="box",
            material_id="aluminum_6061",
            start_position_mm=(0.0, 0.0, 0.2),
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _seed_current_role_manifest(client, session_id=session_id)
        write_script = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_script.py",
                content=script,
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_script.status_code == 200, write_script.text

        write_objectives = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_definition.yaml",
                content=yaml.dump(objectives.model_dump(mode="json")),
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_objectives.status_code == 200, write_objectives.text

        exec_response = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code=_runtime_validate_command(),
                timeout=120,
            ).model_dump(mode="json"),
            headers=headers,
            timeout=180.0,
        )
        assert exec_response.status_code == 200, exec_response.text
        data = ExecuteResponse.model_validate(exec_response.json())
        assert data.exit_code == 0
        assert "VALIDATE_SUCCESS=False" in data.stdout
        assert "does not make child parts static" in data.stdout


@pytest.mark.integration_p0
@pytest.mark.xdist_group(name="physics_sims")
@pytest.mark.asyncio
@pytest.mark.int_id("INT-024")
async def test_int_024_runtime_validate_accepts_translated_top_level_parts_with_exact_solution_script():
    """
    INT-024: benchmark validation should accept the exact authored
    benchmark_script.py contract when top-level parts are placed with
    build123d.translate(), since the transform carries explicit location
    metadata in the current runtime.
    """
    session_id = f"INT-024-LOC-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    script = """
from build123d import Align, Box, BuildPart, Compound
from utils.metadata import CompoundMetadata, PartMetadata
from utils.submission import validate_benchmark

def build():
    with BuildPart() as ground_builder:
        Box(4, 4, 0.2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ground = ground_builder.part
    ground.label = "ground_plane"
    ground.metadata = PartMetadata(material_id="hdpe", is_fixed=True)

    with BuildPart() as platform_builder:
        Box(1, 1, 1, align=(Align.CENTER, Align.CENTER, Align.MIN))
    platform = platform_builder.part.translate((8, 0, 0))
    platform.label = "platform_left"
    platform.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)

    with BuildPart() as ball_builder:
        Box(0.4, 0.4, 0.4, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ball = ball_builder.part.translate((8, 0, 1.2))
    ball.label = "target_box"
    ball.metadata = PartMetadata(material_id="steel_bearing", is_fixed=False)

    benchmark = Compound(children=[ground, platform, ball])
    benchmark.label = "benchmark_assembly"
    benchmark.metadata = CompoundMetadata()
    return benchmark

result = build()
success, message = validate_benchmark(result)
print(f"VALIDATE_SUCCESS={success}")
print(f"VALIDATE_MESSAGE={message}")
"""

    objectives = BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(min_mm=(10.0, -2.0, 0.0), max_mm=(12.0, 2.0, 4.0)),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-20.0, -20.0, 0.0), max_mm=(20.0, 20.0, 30.0)
            ),
        ),
        benchmark_parts=_default_benchmark_parts(),
        simulation_bounds_mm=BoundingBox(
            min_mm=(-50.0, -50.0, -10.0), max_mm=(50.0, 50.0, 50.0)
        ),
        payload=Payload(
            label="target_box",
            shape="box",
            material_id="aluminum_6061",
            start_position_mm=(8.0, 0.0, 1.2),
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _seed_current_role_manifest(client, session_id=session_id)
        write_script = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_script.py",
                content=script,
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_script.status_code == 200, write_script.text

        write_objectives = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_definition.yaml",
                content=yaml.dump(objectives.model_dump(mode="json")),
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_objectives.status_code == 200, write_objectives.text

        exec_response = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code=_runtime_validate_command(),
                timeout=120,
            ).model_dump(mode="json"),
            headers=headers,
            timeout=180.0,
        )
        assert exec_response.status_code == 200, exec_response.text
        data = ExecuteResponse.model_validate(exec_response.json())
        assert data.exit_code == 0
        assert "VALIDATE_SUCCESS=True" in data.stdout
        assert (
            "Validation successful" in data.stdout
            or "VALIDATE_SUCCESS=True" in data.stdout
        )


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "top_level_label_blank",
        "top_level_label_missing",
        "top_level_build123d_label_missing",
    ]
)
@pytest.mark.xdist_group(name="physics_sims")
@pytest.mark.asyncio
@pytest.mark.int_id("INT-024")
async def test_int_024_runtime_validate_rejects_blank_top_level_labels():
    """
    INT-024: top-level build123d parts must not silently accept blank labels.
    """
    session_id = f"INT-024-LABEL-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    script = """
from build123d import Align, Box, Compound
from utils.metadata import CompoundMetadata, PartMetadata
from utils.submission import validate_benchmark

def build():
    part = Box(1, 1, 1, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part.label = "   "
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)

    scene = Compound(children=[part])
    scene.label = "benchmark_assembly"
    scene.metadata = CompoundMetadata()
    return scene

result = build()
success, message = validate_benchmark(result)
print(f"VALIDATE_SUCCESS={success}")
print(f"VALIDATE_MESSAGE={message}")
"""

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _seed_current_role_manifest(client, session_id=session_id)
        write_script = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_script.py",
                content=script,
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_script.status_code == 200, write_script.text

        exec_response = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code=_runtime_validate_command(),
                timeout=120,
            ).model_dump(mode="json"),
            headers=headers,
            timeout=180.0,
        )
        assert exec_response.status_code == 200, exec_response.text
        data = ExecuteResponse.model_validate(exec_response.json())
        assert data.exit_code == 0
        assert "VALIDATE_SUCCESS=False" in data.stdout
        assert "Top-level part labels must be non-empty strings" in data.stdout


@pytest.mark.integration_p0
@pytest.mark.xdist_group(name="physics_sims")
@pytest.mark.asyncio
@pytest.mark.int_id("INT-024")
async def test_int_024_runtime_validate_reports_resolved_build_zone_bounds():
    """
    INT-024: build-zone violations must report the resolved objective bounds,
    not `build_zone None`, so the agent gets actionable correction feedback.
    """
    session_id = f"INT-024-BZ-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    script = """
from build123d import Align, Box
from utils.metadata import PartMetadata
from utils.submission import validate_benchmark

def build():
    ground = Box(40, 40, 1, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ground.label = "ground_plane"
    ground.metadata = PartMetadata(material_id="hdpe", is_fixed=True)
    return ground

result = build()
success, message = validate_benchmark(result)
print(f"VALIDATE_SUCCESS={success}")
print(f"VALIDATE_MESSAGE={message}")
"""

    objectives = BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(min_mm=(-2.0, -2.0, 0.0), max_mm=(2.0, 2.0, 8.0)),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-5.0, -5.0, 0.0), max_mm=(5.0, 5.0, 10.0)
            ),
        ),
        benchmark_parts=_default_benchmark_parts(),
        simulation_bounds_mm=BoundingBox(
            min_mm=(-50.0, -50.0, -10.0), max_mm=(50.0, 50.0, 50.0)
        ),
        payload=Payload(
            label="ground_plane",
            shape="box",
            material_id="aluminum_6061",
            start_position_mm=(0.0, 0.0, 0.5),
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _seed_current_role_manifest(client, session_id=session_id)
        write_script = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_script.py",
                content=script,
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_script.status_code == 200, write_script.text

        write_objectives = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_definition.yaml",
                content=yaml.dump(objectives.model_dump(mode="json")),
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_objectives.status_code == 200, write_objectives.text

        exec_response = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code=_runtime_validate_command(),
                timeout=120,
            ).model_dump(mode="json"),
            headers=headers,
            timeout=180.0,
        )
        assert exec_response.status_code == 200, exec_response.text
        data = ExecuteResponse.model_validate(exec_response.json())
        assert data.exit_code == 0
        assert "VALIDATE_SUCCESS=False" in data.stdout
        assert "build_zone None" not in data.stdout
        assert "payload start pose intersects benchmark geometry" in data.stdout
