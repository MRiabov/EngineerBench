from __future__ import annotations

import math
import os
import uuid
from pathlib import Path

import boto3
import httpx
import numpy as np
import pyarrow.parquet as pq
import pytest
import trimesh
from build123d import Align, Box, Compound, Location
import vtk

from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.contract import (
    payload_trajectory_dict,
)
from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.geometry import (
    box_part_specs_for_route,
)
from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.models import (
    RoutePoint,
)
from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.pipeline import (
    stage_bundle_root,
)
from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.text_templates import (
    build_evidence_script_text,
    build_solution_script_text,
)
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName, ManufacturingMethod
from shared.models.schemas import (
    AssemblyConstraints,
    AssemblyDefinition,
    BenchmarkDefinition,
    BenchmarkPartDefinition,
    BenchmarkPartMetadata,
    BoundingBox,
    Constraints,
    CostTotals,
    CompoundMetadata,
    ManufacturedPartEstimate,
    ObjectivesSection,
    PartMetadata,
    Payload,
    PhysicsConfig,
)
from shared.rendering import export_preview_scene_bundle
from shared.simulation.scene_builder import PreviewScene
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.bundling import extract_bundle_base64
from shared.workers.loader import load_component_from_script
from shared.workers.schema import (
    BenchmarkToolResponse,
    PointCloudRenderBackend,
    PointCloudRenderRequest,
)

WORKER_RENDERER_URL = os.getenv("WORKER_RENDERER_URL", "http://127.0.0.1:18003")
ASSET_BUCKET = os.getenv("ASSET_S3_BUCKET", "problemologist")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.integration_p2,
    pytest.mark.xdist_group(name="renderer_point_cloud"),
]


def _route_points() -> list[RoutePoint]:
    return [
        RoutePoint(name="build_zone_start", pos_mm=(-280.0, 0.0, 180.0), t_s=0.0),
        RoutePoint(name="left_capture_lane", pos_mm=(-240.0, 0.0, 160.0), t_s=1.5),
        RoutePoint(name="bypass_corner", pos_mm=(-240.0, 110.0, 120.0), t_s=2.4),
        RoutePoint(name="goal_lane_entry", pos_mm=(-40.0, 110.0, 70.0), t_s=3.6),
        RoutePoint(name="goal_approach", pos_mm=(240.0, 110.0, 50.0), t_s=4.8),
        RoutePoint(name="goal_zone_contact", pos_mm=(325.0, 0.0, 40.0), t_s=6.0),
    ]


def _benchmark_definition(route_points: list[RoutePoint]) -> BenchmarkDefinition:
    route_start = tuple(float(value) for value in route_points[0].pos_mm)
    route_goal = tuple(float(value) for value in route_points[-1].pos_mm)
    return BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(
                min_mm=(route_goal[0] - 30.0, route_goal[1] - 30.0, 0.0),
                max_mm=(route_goal[0] + 30.0, route_goal[1] + 30.0, 140.0),
            ),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-360.0, -160.0, 0.0),
                max_mm=(380.0, 220.0, 260.0),
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
        physics=PhysicsConfig(backend=SimulatorBackendType.MUJOCO),
        simulation_bounds_mm=BoundingBox(
            min_mm=(-420.0, -220.0, -40.0),
            max_mm=(420.0, 260.0, 320.0),
        ),
        payload=Payload(
            label="slider_ball",
            shape="sphere",
            material_id="abs",
            start_position_mm=route_start,
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
    )


def _assembly_definition() -> AssemblyDefinition:
    return AssemblyDefinition(
        version="1.0",
        constraints=AssemblyConstraints(
            benchmark_max_unit_cost_usd=100.0,
            benchmark_max_weight_g=1000.0,
            planner_target_max_unit_cost_usd=90.0,
            planner_target_max_weight_g=900.0,
        ),
        manufactured_parts=[
            ManufacturedPartEstimate(
                part_name="fixture_box",
                part_id="fixture_box",
                manufacturing_method=ManufacturingMethod.THREE_DP,
                material_id="aluminum_6061",
                quantity=1,
                part_volume_mm3=1000.0,
                stock_bbox_mm={"x": 10.0, "y": 10.0, "z": 10.0},
                stock_volume_mm3=1000.0,
                removed_volume_mm3=0.0,
                estimated_unit_cost_usd=10.0,
            )
        ],
        final_assembly=[],
        totals=CostTotals(
            estimated_unit_cost_usd=10.0,
            estimated_weight_g=100.0,
            estimate_confidence="high",
        ),
    )


def _vector3(vector: object) -> tuple[float, float, float]:
    return (float(vector.X), float(vector.Y), float(vector.Z))


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT_URL", "http://127.0.0.1:19000"),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )


def _bbox_within_bounds(
    bbox: object,
    *,
    bounds_min: tuple[float, float, float],
    bounds_max: tuple[float, float, float],
    tolerance_mm: float = 1e-6,
) -> bool:
    min_vector = _vector3(bbox.min)
    max_vector = _vector3(bbox.max)
    return all(
        (bounds_min[index] - tolerance_mm) <= min_vector[index]
        and max_vector[index] <= (bounds_max[index] + tolerance_mm)
        for index in range(3)
    )


def _point_in_bbox(
    point: tuple[float, float, float],
    bbox: object,
    *,
    tolerance_mm: float = 1e-6,
) -> bool:
    min_vector = _vector3(bbox.min)
    max_vector = _vector3(bbox.max)
    return all(
        (min_vector[index] - tolerance_mm)
        <= point[index]
        <= (max_vector[index] + tolerance_mm)
        for index in range(3)
    )


def _point_in_any_bbox(
    point: tuple[float, float, float],
    bboxes: list[object],
    *,
    tolerance_mm: float = 1e-6,
) -> bool:
    return any(
        _point_in_bbox(point, bbox, tolerance_mm=tolerance_mm) for bbox in bboxes
    )


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


def _points_within_any_bounds(
    points: np.ndarray,
    *,
    bounds_min: np.ndarray,
    bounds_max: np.ndarray,
    tolerance_mm: float = 1e-6,
) -> bool:
    expanded_points = points[:, None, :]
    inside = np.all(expanded_points >= bounds_min[None, :, :] - tolerance_mm, axis=2) & (
        np.all(expanded_points <= bounds_max[None, :, :] + tolerance_mm, axis=2)
    )
    return bool(np.all(inside.any(axis=1)))


def _preview_camera_position(scene: PreviewScene) -> tuple[float, float, float]:
    width = 1280.0
    height = 720.0
    aspect_ratio = max(width / max(height, 1.0), 1e-6)
    half_vertical_fov = math.radians(30.0 / 2.0)
    half_horizontal_fov = math.atan(math.tan(half_vertical_fov) * aspect_ratio)
    limiting_half_fov = max(min(half_vertical_fov, half_horizontal_fov), 1e-3)
    radius = max(float(scene.diagonal) * 0.5, 0.5)
    distance = max((radius / math.sin(limiting_half_fov)) * 1.25, radius + 0.5)
    rad_azim = math.radians(45.0)
    rad_elev = math.radians(-35.0)
    center = tuple(float(value) for value in scene.center_mm)
    return (
        center[0] + distance * math.cos(rad_elev) * math.sin(rad_azim),
        center[1] - distance * math.cos(rad_elev) * math.cos(rad_azim),
        center[2] - distance * math.sin(rad_elev),
    )


def _solution_script_text(
    *,
    scenario_id: str,
    route_points: list[RoutePoint],
    part_specs,
) -> str:
    return build_solution_script_text(
        scenario_id=scenario_id,
        route_points=route_points,
        part_specs=part_specs,
        payload_name="slider_ball",
        split_seed=123,
        tube_radius_mm=20.0,
        clearance_mm=10.0,
        wall_thickness_mm=3.0,
        max_segment_mm=60.0,
        material_id="aluminum_6061",
    )


def _staged_workspace(
    tmp_path: Path,
) -> tuple[Path, BenchmarkDefinition, PreviewScene, Path, object, str]:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    route_points = _route_points()
    benchmark_definition = _benchmark_definition(route_points)
    part_specs = box_part_specs_for_route(
        route_points,
        tube_radius_mm=20.0,
        clearance_mm=10.0,
        wall_thickness_mm=3.0,
        max_segment_mm=60.0,
        seed=123,
        material_id="aluminum_6061",
    )
    scenario_id = f"pc-debug-{uuid.uuid4().hex[:8]}"
    solution_script_text = _solution_script_text(
        scenario_id=scenario_id,
        route_points=route_points,
        part_specs=part_specs,
    )
    benchmark_script_text = build_evidence_script_text(
        scenario_id=scenario_id,
        route_points=route_points,
        part_specs=part_specs,
        payload_name="slider_ball",
        split_seed=123,
        tube_radius_mm=20.0,
        clearance_mm=10.0,
        wall_thickness_mm=3.0,
        max_segment_mm=60.0,
        material_id="aluminum_6061",
    )

    (workspace_root / ".manifests").mkdir(parents=True, exist_ok=True)
    (workspace_root / ".manifests" / "current_role.json").write_text(
        current_role_manifest_json(AgentName.BENCHMARK_CODER),
        encoding="utf-8",
    )
    stage_bundle_root(
        root=workspace_root,
        benchmark_definition_yaml=benchmark_definition.model_dump(mode="json"),
        benchmark_script_text=benchmark_script_text,
        benchmark_assembly_text="# Synthetic corridor benchmark assembly\n",
        assembly_definition_yaml=_assembly_definition().model_dump(mode="json"),
        evidence_script_text=benchmark_script_text,
        solution_script_text=solution_script_text,
        payload_trajectory_yaml=payload_trajectory_dict(
            payload_name="slider_ball",
            route_points=route_points,
            first_contacts=[],
            terminal_reference_point=route_points[-1].name,
            backend=SimulatorBackendType.MUJOCO,
            sample_stride_s=0.1,
        ),
        markdown_files={
            "engineering_plan.md": "# Engineering Plan\n",
            "todo.md": "# TODO\n",
            "solution_description.md": "# Solution\n",
            "journal.md": "# Journal\n",
        },
    )

    component = load_component_from_script(
        workspace_root / "solution_script.py",
        session_root=workspace_root,
    )
    preview_bundle = export_preview_scene_bundle(
        component,
        objectives=benchmark_definition,
        workspace_root=workspace_root,
        smoke_test_mode=True,
    )
    bundle_root = tmp_path / "preview_bundle"
    bundle_root.mkdir(parents=True, exist_ok=True)
    extract_bundle_base64(preview_bundle, bundle_root)
    scene = PreviewScene.model_validate_json(
        (bundle_root / "preview_scene.json").read_text(encoding="utf-8")
    )
    return workspace_root, benchmark_definition, scene, bundle_root, component, preview_bundle


def _boundary_workspace(
    tmp_path: Path,
    *,
    probe_center_x_mm: float,
) -> tuple[Path, PreviewScene, Path, str]:
    workspace_root = tmp_path / f"boundary_workspace_{uuid.uuid4().hex[:8]}"
    workspace_root.mkdir(parents=True, exist_ok=True)

    (workspace_root / ".manifests").mkdir(parents=True, exist_ok=True)
    (workspace_root / ".manifests" / "current_role.json").write_text(
        current_role_manifest_json(AgentName.BENCHMARK_CODER),
        encoding="utf-8",
    )

    scene_box = Box(
        100.0,
        100.0,
        100.0,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    scene_box.label = "scene_box"
    scene_box.metadata = PartMetadata(
        material_id="aluminum_6061",
        is_fixed=True,
    )

    probe_box = Box(
        24.0,
        24.0,
        24.0,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    ).move(Location((probe_center_x_mm, 0.0, 0.0)))
    probe_box.label = "probe_box"
    probe_box.metadata = PartMetadata(
        material_id="aluminum_6061",
        is_fixed=False,
    )

    boundary_scene = Compound(children=[scene_box, probe_box], label="boundary_scene")
    boundary_scene.metadata = CompoundMetadata(is_fixed=True)

    bundle_base64 = export_preview_scene_bundle(
        boundary_scene,
        objectives=None,
        workspace_root=workspace_root,
        smoke_test_mode=True,
    )

    bundle_root = tmp_path / f"boundary_bundle_{uuid.uuid4().hex[:8]}"
    bundle_root.mkdir(parents=True, exist_ok=True)
    extract_bundle_base64(bundle_base64, bundle_root)
    scene = PreviewScene.model_validate_json(
        (bundle_root / "preview_scene.json").read_text(encoding="utf-8")
    )
    return workspace_root, scene, bundle_root, bundle_base64


def _exported_entity_world_bounds(
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


async def _render_point_cloud(
    *,
    client: httpx.AsyncClient,
    bundle_base64: str,
    backend: PointCloudRenderBackend,
    session_id: str,
    output_name: str,
    tmp_path: Path,
) -> tuple[BenchmarkToolResponse, Path]:
    response = await client.post(
        f"{WORKER_RENDERER_URL}/debug/render_point_cloud",
        json=PointCloudRenderRequest(
            bundle_base64=bundle_base64,
            sample_limit=12000,
            point_size_px=6,
            render_backend=backend,
            output_name=output_name,
        ).model_dump(mode="json"),
        headers={"X-Session-ID": session_id},
        timeout=300.0,
    )
    assert response.status_code == 200, response.text
    data = BenchmarkToolResponse.model_validate(response.json())
    assert data.success, data.message
    assert data.artifacts is not None, data
    assert data.artifacts.render_paths, data.artifacts
    assert any(path.endswith(output_name) for path in data.artifacts.render_paths), (
        data.artifacts.render_paths
    )
    assert any(
        path.endswith("preview_scene.json")
        for path in (
            list(data.artifacts.render_blobs_base64)
            + list(data.artifacts.object_store_keys)
        )
    ), data.artifacts
    assert any(
        path.endswith("sampled_points.parquet")
        for path in (
            list(data.artifacts.render_blobs_base64)
            + list(data.artifacts.object_store_keys)
        )
    ), data.artifacts
    assert "sampled surface points" in data.message

    sampled_points_path = next(
        path
        for path in data.artifacts.object_store_keys
        if path.endswith("sampled_points.parquet")
    )
    assert sampled_points_path not in data.artifacts.render_blobs_base64, (
        data.artifacts.render_blobs_base64
    )
    local_sampled_points_path = tmp_path / f"{backend.value}_sampled_points.parquet"
    _s3_client().download_file(
        ASSET_BUCKET,
        data.artifacts.object_store_keys[sampled_points_path],
        str(local_sampled_points_path),
    )
    return data, local_sampled_points_path


@pytest.mark.int_id("INT-289")
@pytest.mark.asyncio
async def test_tube_guided_synthetic_corpus_point_cloud_render_keeps_parts_in_bounds(
    tmp_path: Path,
):
    _, _, scene, bundle_root, component, bundle_base64 = _staged_workspace(tmp_path)

    component_children = list(component.children)
    assert component_children, "expected staged solution_script.py to build parts"
    exported_entities = [
        entity
        for entity in scene.entities
        if (entity.mesh_paths or entity.box_size_mm is not None) and entity.label != ""
    ]
    assert exported_entities, scene.model_dump(mode="json")

    async with httpx.AsyncClient(timeout=300.0) as client:
        for backend, output_name in (
            (PointCloudRenderBackend.VTK, "point_cloud_vtk.png"),
            (PointCloudRenderBackend.MATPLOTLIB, "point_cloud_matplotlib.png"),
        ):
            _, sampled_points_path = await _render_point_cloud(
                client=client,
                bundle_base64=bundle_base64,
                backend=backend,
                session_id=f"INT-289-{backend.value}-{uuid.uuid4().hex[:8]}",
                output_name=output_name,
                tmp_path=tmp_path,
            )
            assert sampled_points_path.exists(), sampled_points_path
            table = pq.read_table(sampled_points_path)
            assert table.num_rows > 0, table
            assert {"x_mm", "y_mm", "z_mm"}.issubset(table.column_names), (
                table.column_names
            )
            points = np.column_stack(
                [
                    np.asarray(table.column("x_mm").to_numpy(zero_copy_only=False)),
                    np.asarray(table.column("y_mm").to_numpy(zero_copy_only=False)),
                    np.asarray(table.column("z_mm").to_numpy(zero_copy_only=False)),
                ]
            )
            assert np.isfinite(points).all()
            exported_bounds = [
                _exported_entity_world_bounds(
                    scene,
                    bundle_root=bundle_root,
                    label=entity.label,
                )
                for entity in exported_entities
            ]
            bounds_min = np.stack([bounds[0] for bounds in exported_bounds], axis=0)
            bounds_max = np.stack([bounds[1] for bounds in exported_bounds], axis=0)
            assert _points_within_any_bounds(
                points,
                bounds_min=bounds_min,
                bounds_max=bounds_max,
                tolerance_mm=1e-3,
            ), table.schema
            assert np.ptp(points, axis=0).max() > 0.0, (
                backend,
                output_name,
                table.schema,
            )


@pytest.mark.int_id("INT-290")
@pytest.mark.asyncio
async def test_tube_guided_synthetic_corpus_point_cloud_camera_is_not_occluded(
    tmp_path: Path,
):
    _, _, scene, _, component, _ = _staged_workspace(tmp_path)
    camera_position = _preview_camera_position(scene)
    component_children = list(component.children)
    assert component_children, "expected staged solution_script.py to build parts"
    assert not any(
        _point_in_bbox(camera_position, child.bounding_box())
        for child in component_children
    ), {
        "camera_position_mm": camera_position,
        "scene_center_mm": scene.center_mm,
        "scene_diagonal_mm": scene.diagonal,
    }


@pytest.mark.int_id("INT-291")
@pytest.mark.asyncio
async def test_tube_guided_synthetic_corpus_point_cloud_matches_exported_bounds(
    tmp_path: Path,
):
    _, scene, bundle_root, bundle_base64 = _boundary_workspace(
        tmp_path,
        probe_center_x_mm=37.8,
    )

    scene_box_bounds_min, scene_box_bounds_max = _exported_entity_world_bounds(
        scene,
        bundle_root=bundle_root,
        label="scene_box",
    )
    probe_bounds_min, probe_bounds_max = _exported_entity_world_bounds(
        scene,
        bundle_root=bundle_root,
        label="probe_box",
    )
    assert _points_within_bounds(
        np.stack([probe_bounds_min, probe_bounds_max], axis=0),
        bounds_min=scene_box_bounds_min,
        bounds_max=scene_box_bounds_max,
        tolerance_mm=1e-3,
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        for backend, output_name in (
            (PointCloudRenderBackend.VTK, "boundary_point_cloud_vtk.png"),
            (
                PointCloudRenderBackend.MATPLOTLIB,
                "boundary_point_cloud_matplotlib.png",
            ),
        ):
            _, sampled_points_path = await _render_point_cloud(
                client=client,
                bundle_base64=bundle_base64,
                backend=backend,
                session_id=f"INT-291-{backend.value}-{uuid.uuid4().hex[:8]}",
                output_name=output_name,
                tmp_path=tmp_path,
            )
            table = pq.read_table(sampled_points_path)
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
                bounds_min=scene_box_bounds_min,
                bounds_max=scene_box_bounds_max,
                tolerance_mm=1e-3,
            )


@pytest.mark.int_id("INT-NEG-291")
@pytest.mark.asyncio
async def test_tube_guided_synthetic_corpus_point_cloud_fails_for_just_outside_bounds(
    tmp_path: Path,
):
    _, scene, bundle_root, bundle_base64 = _boundary_workspace(
        tmp_path,
        probe_center_x_mm=38.2,
    )

    scene_box_bounds_min, scene_box_bounds_max = _exported_entity_world_bounds(
        scene,
        bundle_root=bundle_root,
        label="scene_box",
    )
    probe_bounds_min, probe_bounds_max = _exported_entity_world_bounds(
        scene,
        bundle_root=bundle_root,
        label="probe_box",
    )
    assert not _points_within_bounds(
        np.stack([probe_bounds_min, probe_bounds_max], axis=0),
        bounds_min=scene_box_bounds_min,
        bounds_max=scene_box_bounds_max,
        tolerance_mm=1e-3,
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        for backend, output_name in (
            (PointCloudRenderBackend.VTK, "boundary_point_cloud_vtk_outside.png"),
            (
                PointCloudRenderBackend.MATPLOTLIB,
                "boundary_point_cloud_matplotlib_outside.png",
            ),
        ):
            _, sampled_points_path = await _render_point_cloud(
                client=client,
                bundle_base64=bundle_base64,
                backend=backend,
                session_id=f"INT-NEG-291-{backend.value}-{uuid.uuid4().hex[:8]}",
                output_name=output_name,
                tmp_path=tmp_path,
            )
            table = pq.read_table(sampled_points_path)
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
                    bounds_min=scene_box_bounds_min,
                    bounds_max=scene_box_bounds_max,
                    tolerance_mm=1e-3,
                )
