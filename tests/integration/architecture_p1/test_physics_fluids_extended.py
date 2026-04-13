import base64
import os
import uuid
from io import BytesIO

import httpx
import pandas as pd
import pytest
import yaml

from shared.models.schemas import (
    BenchmarkDefinition,
    BoundingBox,
    Constraints,
    MovedObject,
    ObjectivesSection,
    PhysicsConfig,
)
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.schema import (
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    FsFileEntry,
    ListFilesRequest,
    SimulationArtifacts,
    WriteFileRequest,
)
from tests.integration.agent.helpers import seed_benchmark_assembly_definition
from tests.integration.backend_utils import selected_backend, skip_unless_genesis

# Constants
WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
WORKER_HEAVY_URL = os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002")
CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")

pytestmark = pytest.mark.xdist_group(name="physics_sims")


def _frame_history_benchmark_parts() -> list[dict[str, object]]:
    return [
        {
            "part_id": "environment_fixture",
            "label": "environment_fixture",
            "metadata": {"fixed": True, "material_id": "aluminum_6061"},
        }
    ]


async def _bundle_base64(client: httpx.AsyncClient, session_id: str) -> str:
    resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/bundle",
        headers={"X-Session-ID": session_id},
        timeout=120.0,
    )
    assert resp.status_code == 200, resp.text
    import base64

    return base64.b64encode(resp.content).decode("utf-8")


@pytest.mark.integration_p1
@pytest.mark.int_id("INT-221")
@pytest.mark.asyncio
async def test_int_221_frame_indexed_object_pose_capture_history():
    """INT-221: Verify sampled object poses carry frame indices across captures."""
    if selected_backend() != SimulatorBackendType.MUJOCO:
        pytest.skip(
            "INT-221 uses the MuJoCo simulation pass for capture-history coverage."
        )

    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"INT-221-{uuid.uuid4().hex[:8]}"

        benchmark_definition = BenchmarkDefinition(
            physics=PhysicsConfig(backend=SimulatorBackendType.MUJOCO),
            objectives=ObjectivesSection(
                goal_zone=BoundingBox(min=(0, 0, 40), max=(10, 10, 45)),
                build_zone=BoundingBox(min=(-50, -50, -50), max=(50, 50, 50)),
            ),
            simulation_bounds=BoundingBox(min=(-50, -50, -50), max=(50, 50, 50)),
            payload=MovedObject(
                label="frame_history_box",
                shape="box",
                material_id="aluminum_6061",
                start_position=(0.0, 0.0, 10.0),
                runtime_jitter=(0.0, 0.0, 0.0),
            ),
            constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
            benchmark_parts=_frame_history_benchmark_parts(),
        )

        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_definition.yaml",
                content=yaml.safe_dump(
                    benchmark_definition.model_dump(mode="json"),
                    sort_keys=False,
                ),
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        await seed_benchmark_assembly_definition(client, session_id)

        script_content = """from build123d import Align, Box
from shared.models.schemas import PartMetadata

def build():
    part = Box(1, 1, 1, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part.label = "frame_history_box"
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=False)
    return part
"""
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="script.py",
                content=script_content,
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json=BenchmarkToolRequest(
                script_path="script.py",
                backend=SimulatorBackendType.MUJOCO,
                smoke_test_mode=False,
                bundle_base64=await _bundle_base64(client, session_id),
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=1200.0,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.artifacts is not None

        parquet_path = next(
            (
                path
                for path in data.artifacts.render_blobs_base64
                if path.endswith("objects.parquet")
            ),
            None,
        )
        assert parquet_path is not None, data.artifacts.render_blobs_base64.keys()

        parquet_bytes = base64.b64decode(
            data.artifacts.render_blobs_base64[parquet_path]
        )
        pose_table = pd.read_parquet(BytesIO(parquet_bytes))
        pose_rows = pose_table[
            pose_table["label"].fillna("").str.contains("frame_history_box")
        ]
        frame_indices = sorted(
            {
                int(frame_index)
                for frame_index in pose_rows["frame_index"].dropna().tolist()
            }
        )
        assert len(frame_indices) > 1, pose_rows
        assert frame_indices[0] == 0, frame_indices

        z_positions = [
            position[2] for position in pose_rows["position"].dropna().tolist()
        ]
        assert max(z_positions) > min(z_positions), z_positions

        sample_frame_indices = [
            frame_indices[int((len(frame_indices) - 1) * fraction)]
            for fraction in (0.0, 0.25, 0.5, 0.75, 1.0)
        ]
        expected_lines = [
            f"Payload frame count: {len(frame_indices)}",
            "Payload label: frame_history_box",
            "Payload positions:",
        ]
        for sample_name, frame_index in zip(
            ("first", "25%", "50%", "75%", "final"), sample_frame_indices
        ):
            row = pose_rows[pose_rows["frame_index"] == frame_index].iloc[0]
            position = row["position"]
            expected_lines.append(
                f"- {sample_name} frame (frame_index={frame_index}): "
                f"[{position[0]:.3f}, {position[1]:.3f}, {position[2]:.3f}]"
            )

        assert data.message is not None
        for line in expected_lines:
            assert line in data.message, data.message
