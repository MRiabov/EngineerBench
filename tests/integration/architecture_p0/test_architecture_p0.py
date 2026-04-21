import asyncio
import base64
import os
import tempfile
import time
import uuid
from pathlib import Path

import boto3
import cv2
import httpx
import numpy as np
import pyarrow.parquet as pq
import pytest
import trimesh
import vtk
import yaml
from build123d import Align, Box, Compound, Location

from controller.api.schemas import AgentRunRequest, AgentRunResponse, EpisodeResponse
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName, EpisodeStatus
from shared.models.schemas import (
    AssemblyConstraints,
    AssemblyDefinition,
    BenchmarkDefinition,
    BenchmarkPartDefinition,
    BenchmarkPartMetadata,
    BoundingBox,
    CompoundMetadata,
    Constraints,
    CostTotals,
    ForbidZone,
    ObjectivesSection,
    PartMetadata,
    Payload,
    PhysicsConfig,
)
from shared.rendering import export_preview_scene_bundle
from shared.simulation.scene_builder import PreviewScene
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.bundling import extract_bundle_base64
from shared.workers.schema import (
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    ExecuteRequest,
    ExecuteResponse,
    PointCloudRenderBackend,
    PointCloudRenderRequest,
    ReadFileRequest,
    VerificationRequest,
    WriteFileRequest,
)
from tests.integration.agent.helpers import (
    dump_yaml_model,
    seed_benchmark_assembly_definition,
    seed_execution_reviewer_handover,
)
from tests.integration.backend_utils import selected_backend
from tests.integration.contracts import HealthResponse

pytestmark = pytest.mark.xdist_group(name="physics_sims")

# Constants
WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
WORKER_HEAVY_URL = os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002")
WORKER_RENDERER_URL = os.getenv("WORKER_RENDERER_URL", "http://127.0.0.1:18003")
CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")
AGENTS_CONFIG_PATH = Path("config/agents_config.yaml")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://127.0.0.1:19000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
ASSET_BUCKET = os.getenv("ASSET_S3_BUCKET", "problemologist")


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


def _video_resolution() -> tuple[int, int]:
    render_cfg = yaml.safe_load(AGENTS_CONFIG_PATH.read_text(encoding="utf-8"))[
        "render"
    ]
    video_cfg = render_cfg["video_resolution"]
    return video_cfg["width"], video_cfg["height"]


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name="us-east-1",
    )


def _read_first_video_frame(video_bytes: bytes) -> np.ndarray:
    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
        tmp.write(video_bytes)
        tmp.flush()
        capture = cv2.VideoCapture(tmp.name)
        ok, frame_bgr = capture.read()
        capture.release()
    assert ok and frame_bgr is not None, "Failed to decode first frame from video"
    return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)


async def get_bundle(client: httpx.AsyncClient, session_id: str) -> str:
    """Fetch gzipped workspace from light worker and return base64 string."""
    await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path=".manifests/current_role.json",
            content=current_role_manifest_json(AgentName.BENCHMARK_CODER),
            overwrite=True,
            bypass_agent_permissions=True,
        ).model_dump(mode="json"),
        headers={
            "X-Session-ID": session_id,
            "X-System-FS-Bypass": "1",
        },
    )
    resp = await client.post(
        f"{WORKER_LIGHT_URL}/fs/bundle",
        headers={"X-Session-ID": session_id},
        timeout=120.0,
    )
    assert resp.status_code == 200, f"Failed to get bundle: {resp.text}"
    import base64

    return base64.b64encode(resp.content).decode("utf-8")


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-001")
async def test_int_001_compose_boot_health_contract():
    """INT-001: Verify services are up and healthy."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # Worker Light health
        resp = await client.get(f"{WORKER_LIGHT_URL}/health", timeout=5.0)
        assert resp.status_code == 200
        light_health = HealthResponse.model_validate(resp.json())
        assert light_health.status.value == "HEALTHY"

        # Worker Heavy health
        resp = await client.get(f"{WORKER_HEAVY_URL}/health", timeout=5.0)
        assert resp.status_code == 200
        heavy_health = HealthResponse.model_validate(resp.json())
        assert heavy_health.status.value == "HEALTHY"

        # Worker Renderer health
        resp = await client.get(f"{WORKER_RENDERER_URL}/health", timeout=5.0)
        assert resp.status_code == 200
        renderer_health = HealthResponse.model_validate(resp.json())
        assert renderer_health.status.value == "HEALTHY"

        # Controller health
        resp = await client.get(f"{CONTROLLER_URL}/api/health", timeout=5.0)
        assert resp.status_code == 200
        controller_health = HealthResponse.model_validate(resp.json())
        assert controller_health.status.value == "HEALTHY"


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-217")
async def test_int_217_static_preview_prefers_benchmark_bucket_when_workspace_also_contains_assembly_definition():
    """
    INT-217 regression: benchmark static-preview routing must not flip to the
    engineer bucket just because assembly_definition.yaml is also present.
    """
    session_id = f"INT-217-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(timeout=300.0) as client:
        benchmark_definition = BenchmarkDefinition(
            objectives=ObjectivesSection(
                goal_zone_mm=BoundingBox(
                    min_mm=(0.5, 0.5, 0.0), max_mm=(1.5, 1.5, 1.5)
                ),
                forbid_zones=[],
                build_zone_mm=BoundingBox(
                    min_mm=(-2.0, -2.0, -2.0), max_mm=(2.0, 2.0, 2.0)
                ),
            ),
            benchmark_parts=_default_benchmark_parts(),
            simulation_bounds_mm=BoundingBox(
                min_mm=(-5.0, -5.0, -5.0),
                max_mm=(5.0, 5.0, 5.0),
            ),
            payload=Payload(
                label="delegate_preview_box",
                shape="box",
                material_id="aluminum_6061",
                start_position_mm=(0.0, 0.0, 0.0),
                runtime_jitter_mm=(0.0, 0.0, 0.0),
            ),
            constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
            physics=PhysicsConfig(backend=SimulatorBackendType.MUJOCO),
        )

        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="script.py",
                content="""
from build123d import Align, Box
from shared.models.schemas import PartMetadata

def build():
    part = Box(1, 1, 1, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part.label = "delegate_preview_box"
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=False)
    return part
""",
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_definition.yaml",
                content=dump_yaml_model(benchmark_definition),
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_assembly_definition.yaml",
                content=dump_yaml_model(
                    AssemblyDefinition(
                        version="1.0",
                        constraints=AssemblyConstraints(
                            benchmark_max_unit_cost_usd=100.0,
                            benchmark_max_weight_g=1000.0,
                            planner_target_max_unit_cost_usd=90.0,
                            planner_target_max_weight_g=900.0,
                        ),
                        manufactured_parts=[],
                        final_assembly=[],
                        totals=CostTotals(
                            estimated_unit_cost_usd=10.0,
                            estimated_weight_g=100.0,
                            estimate_confidence="high",
                        ),
                    )
                ),
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_plan.md",
                content="Benchmark plan.\n",
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="todo.md",
                content="- [ ] benchmark task\n",
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="assembly_definition.yaml",
                content=dump_yaml_model(
                    AssemblyDefinition(
                        version="1.0",
                        constraints=AssemblyConstraints(
                            benchmark_max_unit_cost_usd=100.0,
                            benchmark_max_weight_g=1000.0,
                            planner_target_max_unit_cost_usd=90.0,
                            planner_target_max_weight_g=900.0,
                        ),
                        manufactured_parts=[],
                        final_assembly=[],
                        totals=CostTotals(
                            estimated_unit_cost_usd=10.0,
                            estimated_weight_g=100.0,
                            estimate_confidence="high",
                        ),
                    )
                ),
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        bundle64 = await get_bundle(client, session_id)

        static_preview_resp = await client.post(
            f"{WORKER_RENDERER_URL}/benchmark/static-preview",
            json=BenchmarkToolRequest(
                script_path="script.py",
                bundle_base64=bundle64,
                smoke_test_mode=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=300.0,
        )
        assert static_preview_resp.status_code == 200, static_preview_resp.text
        static_preview_data = BenchmarkToolResponse.model_validate(
            static_preview_resp.json()
        )
        assert static_preview_data.success, static_preview_data.message
        assert static_preview_data.artifacts is not None
        assert static_preview_data.artifacts.render_paths, static_preview_data
        assert all(
            path.startswith("renders/benchmark_renders/")
            for path in static_preview_data.artifacts.render_paths
        ), static_preview_data.artifacts.render_paths


def _point_cloud_preview_bundle_base64() -> str:
    from build123d import Align, Box, Compound

    from shared.models.schemas import PartMetadata
    from shared.rendering import export_preview_scene_bundle

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_root = Path(tmpdir)
        box = Box(
            1.0,
            1.0,
            1.0,
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
        box.label = "point_cloud_box"
        box.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=False)
        scene = Compound(children=[box], label="point_cloud_scene")
        return export_preview_scene_bundle(
            scene,
            objectives=None,
            workspace_root=workspace_root,
            smoke_test_mode=True,
        )


def _point_cloud_boundary_preview_bundle(
    tmp_path: Path,
    *,
    probe_center_x_mm: float,
) -> tuple[PreviewScene, Path, str]:
    workspace_root = tmp_path / f"point_cloud_boundary_{uuid.uuid4().hex[:8]}"
    workspace_root.mkdir(parents=True, exist_ok=True)

    scene_box = Box(
        100.0,
        100.0,
        100.0,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    scene_box.label = "scene_box"
    scene_box.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)

    probe_box = Box(
        24.0,
        24.0,
        24.0,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    ).move(Location((probe_center_x_mm, 0.0, 0.0)))
    probe_box.label = "probe_box"
    probe_box.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=False)

    boundary_scene = Compound(children=[scene_box, probe_box], label="boundary_scene")
    boundary_scene.metadata = CompoundMetadata(is_fixed=True)

    bundle_base64 = export_preview_scene_bundle(
        boundary_scene,
        objectives=None,
        workspace_root=workspace_root,
        smoke_test_mode=True,
    )

    bundle_root = tmp_path / f"point_cloud_boundary_bundle_{uuid.uuid4().hex[:8]}"
    bundle_root.mkdir(parents=True, exist_ok=True)
    extract_bundle_base64(bundle_base64, bundle_root)
    scene = PreviewScene.model_validate_json(
        (bundle_root / "preview_scene.json").read_text(encoding="utf-8")
    )
    return scene, bundle_root, bundle_base64


def _point_cloud_entity_bounds(
    scene: PreviewScene,
    *,
    bundle_root: Path,
    label: str,
) -> tuple[np.ndarray, np.ndarray]:
    entity = next(entity for entity in scene.entities if entity.label == label)
    if entity.mesh_paths:
        mesh = trimesh.load(bundle_root / entity.mesh_paths[0], force="mesh")
        mesh = mesh.copy()
        transform = vtk.vtkTransform()
        transform.PostMultiply()
        transform.Translate(*[float(value) for value in entity.pos_mm])
        transform.RotateX(float(entity.euler_deg[0]))
        transform.RotateY(float(entity.euler_deg[1]))
        transform.RotateZ(float(entity.euler_deg[2]))
        vtk_matrix = transform.GetMatrix()
        mesh.apply_transform(
            np.asarray(
                [
                    [vtk_matrix.GetElement(row, col) for col in range(4)]
                    for row in range(4)
                ],
                dtype=float,
            )
        )
        bounds = np.asarray(mesh.bounds, dtype=float)
        return bounds[0], bounds[1]

    if entity.box_size_mm is not None:
        center = np.asarray(entity.pos_mm, dtype=float)
        half_size = np.asarray(entity.box_size_mm, dtype=float)
        return center - half_size, center + half_size

    raise AssertionError(f"exported entity {label!r} has no surface-bearing geometry")


def _points_within_bounds(
    points: np.ndarray,
    *,
    bounds_min: tuple[float, float, float],
    bounds_max: tuple[float, float, float],
    tolerance_mm: float = 1e-6,
) -> bool:
    bounds_min_array = np.asarray(bounds_min, dtype=float)
    bounds_max_array = np.asarray(bounds_max, dtype=float)
    return bool(
        np.all(points >= bounds_min_array - tolerance_mm)
        and np.all(points <= bounds_max_array + tolerance_mm)
    )


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-223")
async def test_int_223_point_cloud_debug_render():
    """INT-223: renderer debug endpoint renders a static point cloud."""
    session_id = f"INT-223-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(timeout=300.0) as client:
        bundle64 = _point_cloud_preview_bundle_base64()

        for render_backend, output_name in (
            (PointCloudRenderBackend.VTK, "point_cloud_vtk.png"),
            (PointCloudRenderBackend.MATPLOTLIB, "point_cloud_matplotlib.png"),
        ):
            resp = await client.post(
                f"{WORKER_RENDERER_URL}/debug/render_point_cloud",
                json=PointCloudRenderRequest(
                    bundle_base64=bundle64,
                    sample_limit=32,
                    point_size_px=6,
                    render_backend=render_backend,
                    output_name=output_name,
                ).model_dump(mode="json"),
                headers={"X-Session-ID": session_id},
                timeout=300.0,
            )
            assert resp.status_code == 200, resp.text
            data = BenchmarkToolResponse.model_validate(resp.json())
            assert data.success, data.message
            assert data.artifacts is not None
            assert any(
                path.startswith("renders/debug_point_cloud/")
                and path.endswith(output_name)
                for path in data.artifacts.render_paths
            ), data.artifacts.render_paths
            assert any(
                path.endswith("preview_scene.json")
                for path in (
                    list(data.artifacts.render_blobs_base64)
                    + list(data.artifacts.object_store_keys)
                )
            ), data.artifacts
            assert "sampled surface points" in data.message


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-292")
async def test_int_292_point_cloud_export_bounds_follow_exported_preview_scene(
    tmp_path: Path,
):
    """INT-292: preview-scene point clouds respect exported preview bounds."""
    session_id = f"INT-292-{uuid.uuid4().hex[:8]}"

    scene, bundle_root, bundle64 = _point_cloud_boundary_preview_bundle(
        tmp_path,
        probe_center_x_mm=37.8,
    )
    scene_bounds_min, scene_bounds_max = _point_cloud_entity_bounds(
        scene, bundle_root=bundle_root, label="scene_box"
    )
    probe_bounds_min, probe_bounds_max = _point_cloud_entity_bounds(
        scene, bundle_root=bundle_root, label="probe_box"
    )
    assert _points_within_bounds(
        np.stack([probe_bounds_min, probe_bounds_max], axis=0),
        bounds_min=scene_bounds_min,
        bounds_max=scene_bounds_max,
        tolerance_mm=1e-3,
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"{WORKER_RENDERER_URL}/debug/render_point_cloud",
            json=PointCloudRenderRequest(
                bundle_base64=bundle64,
                sample_limit=96,
                point_size_px=6,
                render_backend=PointCloudRenderBackend.VTK,
                output_name="boundary_point_cloud_vtk.png",
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=300.0,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.success, data.message
        sampled_points_path = next(
            path
            for path in data.artifacts.object_store_keys
            if path.endswith("sampled_points.parquet")
        )
        local_sampled_points_path = bundle_root / "sampled_points.parquet"
        _s3_client().download_file(
            ASSET_BUCKET,
            data.artifacts.object_store_keys[sampled_points_path],
            str(local_sampled_points_path),
        )
        table = pq.read_table(local_sampled_points_path)
        points = np.column_stack(
            [
                np.asarray(table.column("x_mm").to_numpy(zero_copy_only=False)),
                np.asarray(table.column("y_mm").to_numpy(zero_copy_only=False)),
                np.asarray(table.column("z_mm").to_numpy(zero_copy_only=False)),
            ]
        )
        assert np.isfinite(points).all()
        assert _points_within_bounds(
            points,
            bounds_min=scene_bounds_min,
            bounds_max=scene_bounds_max,
            tolerance_mm=1e-3,
        ), table.schema


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-NEG-292")
async def test_int_neg_292_point_cloud_export_bounds_fail_when_probe_is_outside(
    tmp_path: Path,
):
    """INT-NEG-292: preview-scene point clouds fail closed outside exported bounds."""
    session_id = f"INT-NEG-292-{uuid.uuid4().hex[:8]}"

    scene, bundle_root, bundle64 = _point_cloud_boundary_preview_bundle(
        tmp_path,
        probe_center_x_mm=38.2,
    )
    scene_bounds_min, scene_bounds_max = _point_cloud_entity_bounds(
        scene, bundle_root=bundle_root, label="scene_box"
    )
    probe_bounds_min, probe_bounds_max = _point_cloud_entity_bounds(
        scene, bundle_root=bundle_root, label="probe_box"
    )
    assert not _points_within_bounds(
        np.stack([probe_bounds_min, probe_bounds_max], axis=0),
        bounds_min=scene_bounds_min,
        bounds_max=scene_bounds_max,
        tolerance_mm=1e-3,
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"{WORKER_RENDERER_URL}/debug/render_point_cloud",
            json=PointCloudRenderRequest(
                bundle_base64=bundle64,
                sample_limit=96,
                point_size_px=6,
                render_backend=PointCloudRenderBackend.MATPLOTLIB,
                output_name="boundary_point_cloud_matplotlib.png",
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=300.0,
        )
        assert resp.status_code == 200, resp.text
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.success, data.message
        sampled_points_path = next(
            path
            for path in data.artifacts.object_store_keys
            if path.endswith("sampled_points.parquet")
        )
        local_sampled_points_path = bundle_root / "sampled_points.parquet"
        _s3_client().download_file(
            ASSET_BUCKET,
            data.artifacts.object_store_keys[sampled_points_path],
            str(local_sampled_points_path),
        )
        table = pq.read_table(local_sampled_points_path)
        points = np.column_stack(
            [
                np.asarray(table.column("x_mm").to_numpy(zero_copy_only=False)),
                np.asarray(table.column("y_mm").to_numpy(zero_copy_only=False)),
                np.asarray(table.column("z_mm").to_numpy(zero_copy_only=False)),
            ]
        )
        assert np.isfinite(points).all()
        with pytest.raises(AssertionError):
            assert _points_within_bounds(
                points,
                bounds_min=scene_bounds_min,
                bounds_max=scene_bounds_max,
                tolerance_mm=1e-3,
            )


def _simulation_video_smoke_script() -> str:
    return """
from build123d import Align, Box
from shared.models.schemas import PartMetadata

def build():
    part = Box(1, 1, 1, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part.label = "simulation_video_smoke_box"
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=False)
    return part
"""


async def _assert_simulation_video_contract(
    *,
    client: httpx.AsyncClient,
    session_id: str,
    backend: SimulatorBackendType,
) -> None:
    await seed_benchmark_assembly_definition(client, session_id)
    await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path="script.py",
            content=_simulation_video_smoke_script(),
            overwrite=True,
        ).model_dump(mode="json"),
        headers={"X-Session-ID": session_id},
    )

    bundle64 = await get_bundle(client, session_id)
    resp = await client.post(
        f"{WORKER_HEAVY_URL}/benchmark/simulate",
        json=BenchmarkToolRequest(
            script_path="script.py",
            backend=backend,
            bundle_base64=bundle64,
            smoke_test_mode=True,
        ).model_dump(mode="json"),
        headers={"X-Session-ID": session_id},
        timeout=1200.0,
    )
    assert resp.status_code == 200, resp.text
    data = BenchmarkToolResponse.model_validate(resp.json())
    assert data.success, data.message
    assert data.artifacts is not None

    render_paths = list(data.artifacts.render_paths)
    assert any(path.endswith(".mp4") for path in render_paths), render_paths
    manifest_paths = [
        path
        for path in data.artifacts.render_blobs_base64
        if path.endswith("render_manifest.json")
    ]
    assert any(
        path.startswith("renders/benchmark_renders/simulation_video/")
        for path in manifest_paths
    ), manifest_paths
    assert data.artifacts.object_store_keys, data.artifacts
    mp4_keys = [
        path for path in data.artifacts.object_store_keys if path.endswith(".mp4")
    ]
    assert mp4_keys, data.artifacts.object_store_keys
    for key in mp4_keys:
        assert data.artifacts.object_store_keys[key], key
    assert not any(
        path.endswith(".mp4") for path in data.artifacts.render_blobs_base64
    ), data.artifacts.render_blobs_base64

    video_path = next(
        (path for path in render_paths if path.endswith(".mp4")),
        None,
    )
    assert video_path is not None, render_paths

    objects_path = str(Path(video_path).with_name("objects.parquet"))
    assert objects_path in data.artifacts.render_blobs_base64, (
        data.artifacts.render_blobs_base64
    )
    objects_bytes = base64.b64decode(data.artifacts.render_blobs_base64[objects_path])
    assert objects_bytes[:4] == b"PAR1", objects_bytes[:16]
    assert objects_bytes[-4:] == b"PAR1", objects_bytes[-16:]

    object_store_key = data.artifacts.object_store_keys[video_path]
    video_bytes = (
        _s3_client()
        .get_object(
            Bucket=ASSET_BUCKET,
            Key=object_store_key,
        )["Body"]
        .read()
    )
    frame_rgb = _read_first_video_frame(video_bytes)
    assert frame_rgb.shape[:2] == _video_resolution()[::-1], frame_rgb.shape


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-210")
async def test_int_210_mujoco_simulation_video_delegates_to_renderer_worker():
    """INT-210: MuJoCo simulation video is encoded by worker-renderer."""
    if selected_backend() != SimulatorBackendType.MUJOCO:
        pytest.skip("MuJoCo video smoke only runs when MuJoCo is the selected backend")

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _assert_simulation_video_contract(
            client=client,
            session_id=f"INT-210-{uuid.uuid4().hex[:8]}",
            backend=SimulatorBackendType.MUJOCO,
        )


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-211")
async def test_int_211_genesis_simulation_video_delegates_to_renderer_worker():
    """INT-211: Genesis simulation video uses the same renderer-worker contract."""
    if selected_backend() != SimulatorBackendType.GENESIS:
        pytest.skip(
            "Genesis video smoke only runs when Genesis is the selected backend"
        )

    async with httpx.AsyncClient(timeout=300.0) as client:
        await _assert_simulation_video_contract(
            client=client,
            session_id=f"INT-211-{uuid.uuid4().hex[:8]}",
            backend=SimulatorBackendType.GENESIS,
        )


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-002")
async def test_int_002_controller_execution_boundary():
    """INT-002: Verify controller execution stays on worker-side boundaries."""
    session_id = f"INT-002-{uuid.uuid4().hex[:8]}"
    task = "Build a simple box of 10x10x10mm."

    async with httpx.AsyncClient(timeout=300.0) as client:
        await seed_benchmark_assembly_definition(client, session_id)
        await seed_execution_reviewer_handover(
            client,
            session_id=session_id,
            int_id="INT-002",
        )

        # Trigger agent run
        req = AgentRunRequest(task=task, session_id=session_id)
        resp = await client.post(
            f"{CONTROLLER_URL}/api/agent/run",
            json=req.model_dump(mode="json"),
            timeout=1000.0,
        )
        assert resp.status_code == 202
        agent_run_resp = AgentRunResponse.model_validate(resp.json())
        episode_id = agent_run_resp.episode_id

        # Poll for status with increased timeout
        max_attempts = 120
        completed = False
        for _ in range(max_attempts):
            await asyncio.sleep(10.0)
            s_resp = await client.get(f"{CONTROLLER_URL}/api/episodes/{episode_id}")
            ep_data = EpisodeResponse.model_validate(s_resp.json())
            status = ep_data.status
            if status == EpisodeStatus.COMPLETED:
                completed = True
                break
            if status == EpisodeStatus.FAILED:
                pytest.fail(f"Agent failed: {ep_data.model_dump(exclude={'traces'})}")

        assert completed, "Agent did not complete in time"


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-003")
async def test_int_003_session_filesystem_isolation(worker_light_client):
    """INT-003: Verify sessions have isolated filesystems."""
    client = worker_light_client
    session_a = f"test-iso-a-{int(time.time())}"
    session_b = f"test-iso-b-{int(time.time())}"

    # Write to A
    req_write = WriteFileRequest(path="test_iso.txt", content="dummy_payload")
    await client.post(
        "/fs/write",
        json=req_write.model_dump(mode="json"),
        headers={"X-Session-ID": session_a},
    )

    # Try read from B
    req_read = ReadFileRequest(path="test_iso.txt")
    resp = await client.post(
        "/fs/read",
        json=req_read.model_dump(mode="json"),
        headers={"X-Session-ID": session_b},
    )
    assert resp.status_code == 404


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-004")
async def test_int_004_simulation_serialization():
    """INT-004: heavy worker exposes single-flight admission, busy responses, and readiness gating."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_ids = [f"test-ser-{i}-{int(time.time())}" for i in range(3)]

        script = """
from build123d import *
from shared.models.schemas import PartMetadata
def build():
    b = Box(1, 1, 1, align=(Align.CENTER, Align.CENTER, Align.MIN))
    b.label = "target_box"
    b.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return b
"""
        req_write = WriteFileRequest(path="box.py", content=script)
        await asyncio.gather(
            *[
                client.post(
                    f"{WORKER_LIGHT_URL}/fs/write",
                    json=req_write.model_dump(mode="json"),
                    headers={"X-Session-ID": sid},
                )
                for sid in session_ids
            ]
        )

        bundles = [await get_bundle(client, sid) for sid in session_ids]

        # Avoid cross-test overlap by waiting for an idle heavy worker before INT-004 starts.
        for _ in range(120):
            ready_resp = await client.get(f"{WORKER_HEAVY_URL}/ready", timeout=5.0)
            if ready_resp.status_code == 200:
                break
            await asyncio.sleep(0.5)
        else:
            pytest.fail("worker-heavy did not become ready before INT-004")

        async def _simulate(session_id: str, bundle_base64: str):
            sim_req = BenchmarkToolRequest(
                script_path="box.py",
                backend=selected_backend(),
                bundle_base64=bundle_base64,
                smoke_test_mode=True,
            )
            resp = await client.post(
                f"{WORKER_HEAVY_URL}/benchmark/simulate",
                json=sim_req.model_dump(mode="json"),
                headers={"X-Session-ID": session_id},
                timeout=1000.0,
            )
            try:
                payload = resp.json()
            except Exception:
                payload = {"raw_text": resp.text}
            return resp.status_code, payload

        first_task = asyncio.create_task(_simulate(session_ids[0], bundles[0]))
        observed_not_ready = False
        for _ in range(80):
            if first_task.done():
                break
            ready_resp = await client.get(f"{WORKER_HEAVY_URL}/ready", timeout=5.0)
            if ready_resp.status_code != 200:
                observed_not_ready = True
                break
            await asyncio.sleep(0.1)

        assert observed_not_ready, (
            "expected /ready to report not-ready while the admitted heavy job was active"
        )

        remaining_results = await asyncio.gather(
            *[
                _simulate(sid, bundle)
                for sid, bundle in zip(session_ids[1:], bundles[1:])
            ]
        )
        results = [await first_task, *remaining_results]

        admitted_responses = 0
        busy_count = 0
        unexpected: list[str] = []
        for idx, (status_code, payload) in enumerate(results):
            if status_code == 200:
                parsed = BenchmarkToolResponse.model_validate(payload)
                if parsed.success:
                    admitted_responses += 1
                else:
                    unexpected.append(
                        f"request[{idx}] returned 200 but success=false: {parsed.message}"
                    )
                continue

            if status_code == 503:
                detail = payload.get("detail") if isinstance(payload, dict) else None
                if isinstance(detail, dict) and detail.get("code") == "WORKER_BUSY":
                    busy_count += 1
                else:
                    unexpected.append(
                        f"request[{idx}] returned 503 without WORKER_BUSY: {payload}"
                    )
                continue

            unexpected.append(
                f"request[{idx}] unexpected status={status_code}: {payload}"
            )

        assert not unexpected, "\n".join(unexpected)
        assert admitted_responses == 1, (
            f"expected exactly 1 admitted request, got {admitted_responses}"
        )
        assert busy_count >= 1, "expected one or more WORKER_BUSY responses"


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-020")
async def test_int_020_simulation_failure_taxonomy():
    """INT-020: Verify simulation success/failure taxonomy."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"test-int-020-{int(time.time())}"

        # 1. Setup minimal benchmark_definition.yaml
        objectives = BenchmarkDefinition(
            objectives=ObjectivesSection(
                goal_zone_mm=BoundingBox(
                    min_mm=(10.5, 10.5, 10.5), max_mm=(12.5, 12.5, 12.5)
                ),
                forbid_zones=[
                    ForbidZone(
                        name="zone_forbid_test",
                        min_mm=(2.5, 2.5, 2.5),
                        max_mm=(4.5, 4.5, 4.5),
                    )
                ],
                build_zone_mm=BoundingBox(
                    min_mm=(0.5, 0.5, 0.5), max_mm=(20.5, 20.5, 20.5)
                ),
            ),
            benchmark_parts=_default_benchmark_parts(),
            simulation_bounds_mm=BoundingBox(
                min_mm=(-20.5, -20.5, -20.5), max_mm=(20.5, 20.5, 20.5)
            ),
            payload=Payload(
                label="target_box",
                shape="sphere",
                material_id="aluminum_6061",
                start_position_mm=(0.5, 0.5, 0.5),
                runtime_jitter_mm=(0.0, 0.0, 0.0),
            ),
            constraints=Constraints(max_unit_cost=20.5, max_weight_g=10.5),
        )

        req_write_obj = WriteFileRequest(
            path="benchmark_definition.yaml",
            content=dump_yaml_model(objectives),
            overwrite=True,
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=req_write_obj.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        script_fail = """
from build123d import *
from shared.models.schemas import PartMetadata
def build():
    with BuildPart() as p:
        Box(2, 2, 2, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    p.part.move(Location((3.5, 3.5, 3.5)))
    p.part.label = "target_box"
    p.part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=False)
    return p.part
"""

        req_write_fail = WriteFileRequest(path="fail.py", content=script_fail)
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=req_write_fail.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        # DEBUG: add manual debug step to try and export stl
        debug_stl_script = """
import os
import sys
from build123d import *
def run():
    part = Box(1,1,1)
    export_stl(part, "debug_test.stl")
    if not os.path.exists("debug_test.stl"):
        raise RuntimeError("Manual export_stl failed")
run()
"""
        req_write_debug = WriteFileRequest(
            path="debug_stl.py", content=debug_stl_script
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=req_write_debug.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        resp_exec = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code=("python - <<'PY'\nimport debug_stl\ndebug_stl.run()\nPY\n"),
                timeout=120,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=180.0,
        )
        assert resp_exec.status_code == 200
        exec_data = ExecuteResponse.model_validate(resp_exec.json())
        assert exec_data.exit_code == 0

        bundle64 = await get_bundle(client, session_id)

        sim_req = BenchmarkToolRequest(
            script_path="fail.py",
            backend=selected_backend(),
            bundle_base64=bundle64,
            smoke_test_mode=True,
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json=sim_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=1000.0,
        )

        assert resp.status_code == 200
        data = BenchmarkToolResponse.model_validate(resp.json())

        assert not data.success
        msg_lower = data.message.lower()
        assert any(
            msg in msg_lower
            for msg in [
                "forbid zone hit",
                "collision_with_forbidden_zone",
                "forbid_zone_hit",
            ]
        )

        # Success path for taxonomy: explicit goal completion signal.
        success_objectives = objectives.model_copy(deep=True)
        success_objectives.objectives.forbid_zones = []
        success_objectives.objectives.goal_zone_mm = BoundingBox(
            min_mm=(3.0, 3.0, 3.0), max_mm=(4.0, 4.0, 4.0)
        )
        req_write_success_obj = WriteFileRequest(
            path="benchmark_definition.yaml",
            content=dump_yaml_model(success_objectives),
            overwrite=True,
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=req_write_success_obj.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        success_bundle64 = await get_bundle(client, session_id)
        success_sim_req = sim_req.model_copy(update={"bundle_base64": success_bundle64})
        success_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json=success_sim_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=1000.0,
        )
        assert success_resp.status_code == 200
        success_data = BenchmarkToolResponse.model_validate(success_resp.json())
        if not success_data.success:
            pytest.fail(f"Success path failed: {success_data.message}")
        assert (
            "goal achieved" in success_data.message.lower()
            or "goal zone" in success_data.message.lower()
            or "green zone" in success_data.message.lower()
        ), success_data.message


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-021")
async def test_int_021_runtime_randomization_robustness():
    """INT-021: Verify runtime randomization robustness (multi-seed)."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"test-int-021-{int(time.time())}"

        await seed_benchmark_assembly_definition(client, session_id)

        objectives = BenchmarkDefinition(
            objectives=ObjectivesSection(
                goal_zone_mm=BoundingBox(min_mm=(-10, -10, -10), max_mm=(10, 10, 10)),
                build_zone_mm=BoundingBox(min_mm=(-20, -20, -20), max_mm=(20, 20, 20)),
            ),
            benchmark_parts=_default_benchmark_parts(),
            simulation_bounds_mm=BoundingBox(
                min_mm=(-20, -20, -20), max_mm=(20, 20, 20)
            ),
            payload=Payload(
                label="target_box",
                shape="sphere",
                material_id="aluminum_6061",
                start_position_mm=(0, 0, 0.5),
                runtime_jitter_mm=(0.1, 0.1, 0),
            ),
            constraints=Constraints(max_unit_cost=20.0, max_weight_g=10.0),
        )
        req_write_obj = WriteFileRequest(
            path="benchmark_definition.yaml",
            content=dump_yaml_model(objectives),
            overwrite=True,
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=req_write_obj.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        script_content = """
from build123d import *
from shared.models.schemas import PartMetadata
def build():
    with BuildPart() as p:
        Box(0.1, 0.1, 0.1, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    p.part.label = "target_box"
    p.part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=False)
    return p.part
"""
        req_write_script = WriteFileRequest(path="script.py", content=script_content)
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=req_write_script.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        validate_resp = await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=BenchmarkToolRequest(
                script_path="script.py",
                backend=selected_backend(),
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=300.0,
        )
        assert validate_resp.status_code == 200, validate_resp.text
        validate_data = BenchmarkToolResponse.model_validate(validate_resp.json())
        assert validate_data.success, validate_data.message
        assert validate_data.artifacts is not None
        assert validate_data.artifacts.validation_results_json is not None

        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="validation_results.json",
                content=validate_data.artifacts.validation_results_json,
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        verify_req = VerificationRequest(
            script_path="script.py",
            jitter_range=(0.002, 0.002, 0.001),
            num_scenes=3,
            duration=1.0,
            seed=42,
            backend=selected_backend(),
        )
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/verify",
            json=verify_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=300.0,
        )

        assert resp.status_code == 200
        data = BenchmarkToolResponse.model_validate(resp.json())

        if not data.success:
            pytest.fail(f"Verification failed: {data.message}")
        assert data.artifacts.verification_result is not None
        ver_result = data.artifacts.verification_result
        assert ver_result.num_scenes == 3
        assert ver_result.success_rate == 1.0
        assert ver_result.scene_build_count == 1
        assert ver_result.backend_run_count == 1
        assert ver_result.batched_execution is True


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-024")
async def test_int_024_worker_benchmark_validation_toolchain():
    """
    INT-024: /benchmark/validate fails on invalid objective setups,
    including jitter-range conflicts.
    """
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"INT-024-{uuid.uuid4().hex[:8]}"

        script = """
from build123d import *
from shared.models.schemas import PartMetadata
def build():
    p = Box(10, 10, 10).move(Location((0, 0, 5)))
    p.label = "target_box"
    p.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return p
"""
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(path="script.py", content=script).model_dump(
                mode="json"
            ),
            headers={"X-Session-ID": session_id},
        )

        overlap_objectives = BenchmarkDefinition(
            objectives=ObjectivesSection(
                goal_zone_mm=BoundingBox(
                    min_mm=(0.0, 0.0, 0.0), max_mm=(10.0, 10.0, 10.0)
                ),
                forbid_zones=[
                    ForbidZone(
                        name="goal_overlap",
                        min_mm=(5.0, 5.0, 5.0),
                        max_mm=(12.0, 12.0, 12.0),
                    )
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
                start_position_mm=(0.0, 0.0, 10.0),
                runtime_jitter_mm=(0.0, 0.0, 0.0),
            ),
            constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_definition.yaml",
                content=dump_yaml_model(overlap_objectives),
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        overlap_resp = await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=BenchmarkToolRequest(script_path="script.py").model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=180.0,
        )
        assert overlap_resp.status_code == 200
        overlap_data = BenchmarkToolResponse.model_validate(overlap_resp.json())
        assert overlap_data.success is False
        assert "goal_zone_mm overlaps forbid zone" in (overlap_data.message or "")

        jitter_conflict_objectives = overlap_objectives.model_copy(
            update={
                "objectives": ObjectivesSection(
                    goal_zone_mm=BoundingBox(
                        min_mm=(12.0, 12.0, 0.0),
                        max_mm=(16.0, 16.0, 6.0),
                    ),
                    forbid_zones=[
                        ForbidZone(
                            name="spawn_conflict",
                            min_mm=(-3.0, -3.0, 0.0),
                            max_mm=(3.0, 3.0, 6.0),
                        )
                    ],
                    build_zone_mm=BoundingBox(
                        min_mm=(-20.0, -20.0, 0.0),
                        max_mm=(20.0, 20.0, 30.0),
                    ),
                ),
                "payload": Payload(
                    label="target_box",
                    shape="sphere",
                    material_id="aluminum_6061",
                    start_position_mm=(0.0, 0.0, 3.0),
                    runtime_jitter_mm=(2.0, 2.0, 1.0),
                ),
            }
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="benchmark_definition.yaml",
                content=dump_yaml_model(jitter_conflict_objectives),
                overwrite=True,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        jitter_resp = await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json=BenchmarkToolRequest(script_path="script.py").model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=180.0,
        )
        assert jitter_resp.status_code == 200
        jitter_data = BenchmarkToolResponse.model_validate(jitter_resp.json())
        assert jitter_data.success is False
        assert "payload runtime envelope intersects forbid zone" in (
            jitter_data.message or ""
        )
