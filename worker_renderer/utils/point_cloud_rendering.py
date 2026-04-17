# ruff: noqa: E402, I001
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=True)
import numpy as np
import structlog
import trimesh
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

from shared.agents import get_image_render_resolution
from shared.rendering import (
    configure_headless_rendering,
    create_headless_vtk_render_window,
)
from shared.simulation.scene_builder import PreviewEntity, PreviewScene
from shared.workers.schema import PointCloudRenderBackend
from worker_renderer.utils.build123d_rendering import (
    _RGB_AXES_COLOR,
    _make_transform,
    _preview_camera_distance,
    _render_view,
    _scene_axis_label_format,
    _scene_axis_tick_count,
    _scene_center,
    camera_position_from_orbit,
)

configure_headless_rendering()
import vtk
from vtkmodules.vtkRenderingAnnotation import vtkCubeAxesActor2D
from vtkmodules.vtkRenderingCore import vtkPolyDataMapper, vtkRenderer

logger = structlog.get_logger(__name__)

_DEFAULT_POINT_COLOR = (0.20, 0.82, 1.00)
_DEFAULT_POINT_CLOUD_PITCH_DEG = -35.0
_DEFAULT_POINT_CLOUD_YAW_DEG = 45.0
_DEFAULT_POINT_CLOUD_FRAMING_MARGIN = 1.35


@dataclass
class PointCloudRenderResult:
    image_path: Path
    sampled_point_count: int
    source_surface_count: int


@dataclass(frozen=True)
class _RendererBundle:
    renderer: vtkRenderer
    window: object


@dataclass(frozen=True)
class _SurfaceMesh:
    mesh_path: Path
    entity: PreviewEntity
    mesh: trimesh.Trimesh
    transform: vtk.vtkTransform


def _load_preview_scene(scene_path: Path) -> tuple[PreviewScene, str]:
    raw_scene_json = scene_path.read_text(encoding="utf-8")
    scene = PreviewScene.model_validate_json(raw_scene_json)
    scene_root = scene_path.parent.resolve()
    for entity in scene.entities:
        if not entity.mesh_paths:
            continue
        entity.mesh_paths = [
            str((scene_root / Path(mesh_path)).resolve())
            if not Path(mesh_path).is_absolute()
            else str(Path(mesh_path).resolve())
            for mesh_path in entity.mesh_paths
        ]
    return scene, raw_scene_json


def _scene_signature(raw_scene_json: str, *, sample_limit: int) -> int:
    payload = json.dumps(
        json.loads(raw_scene_json),
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(
        f"{payload}|sample_limit={sample_limit}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _load_mesh(mesh_path: Path) -> trimesh.Trimesh:
    try:
        loaded = trimesh.load(mesh_path, force="mesh", process=False)
    except Exception as exc:  # pragma: no cover - runtime failure path
        raise RuntimeError(f"failed to read mesh {mesh_path}: {exc}") from exc

    if isinstance(loaded, trimesh.Scene):
        loaded = loaded.dump(concatenate=True)

    if not isinstance(loaded, trimesh.Trimesh):
        raise RuntimeError(f"failed to interpret mesh {mesh_path} as a surface mesh")
    if loaded.is_empty:
        raise RuntimeError(f"mesh {mesh_path} does not contain any triangles")
    return loaded.copy()


def _scene_surface_meshes(scene: PreviewScene) -> list[_SurfaceMesh]:
    surfaces: list[_SurfaceMesh] = []
    for entity in sorted(
        scene.entities,
        key=lambda item: (
            item.object_id,
            item.label,
            item.instance_name,
        ),
    ):
        transform = _make_transform(entity.pos_mm, entity.euler_deg)
        if entity.mesh_paths:
            for mesh_path in sorted(entity.mesh_paths):
                surfaces.append(
                    _SurfaceMesh(
                        mesh_path=Path(mesh_path),
                        entity=entity,
                        mesh=_load_mesh(Path(mesh_path)),
                        transform=transform,
                    )
                )
            continue

        if entity.box_size_mm is None:
            continue

        mesh = trimesh.creation.box(
            extents=tuple(float(value) * 2.0 for value in entity.box_size_mm)
        )
        surfaces.append(
            _SurfaceMesh(
                mesh_path=Path(entity.label),
                entity=entity,
                mesh=mesh,
                transform=transform,
            )
        )

    if not surfaces:
        raise ValueError("preview scene does not contain any surface-bearing entities")
    return surfaces


def _allocate_sample_counts(
    surfaces: list[_SurfaceMesh], *, sample_limit: int
) -> list[int]:
    areas = np.asarray(
        [max(float(mesh.mesh.area), 0.0) for mesh in surfaces], dtype=float
    )
    total_area = float(areas.sum())
    if total_area <= 0.0:
        raise ValueError("preview scene surfaces do not expose any measurable area")

    weighted = (areas / total_area) * float(sample_limit)
    counts = np.floor(weighted).astype(int)
    remainder = int(sample_limit - int(counts.sum()))
    if remainder > 0:
        fractions = weighted - counts
        order = np.argsort(-fractions, kind="stable")
        for index in order[:remainder]:
            counts[index] += 1
    return counts.tolist()


def _sample_mesh_surface_points(
    mesh: trimesh.Trimesh, *, sample_count: int, rng: np.random.Generator
) -> np.ndarray:
    if sample_count <= 0:
        return np.empty((0, 3), dtype=float)

    face_areas = np.asarray(mesh.area_faces, dtype=float)
    total_face_area = float(face_areas.sum())
    if total_face_area <= 0.0:
        raise ValueError("surface mesh does not expose any measurable area")

    face_probabilities = face_areas / total_face_area
    face_indices = rng.choice(
        len(mesh.faces),
        size=sample_count,
        replace=True,
        p=face_probabilities,
    )
    triangles = np.asarray(mesh.vertices[mesh.faces[face_indices]], dtype=float)

    r1 = np.sqrt(rng.random(sample_count))
    r2 = rng.random(sample_count)
    bary_u = 1.0 - r1
    bary_v = r1 * (1.0 - r2)
    bary_w = r1 * r2
    return (
        triangles[:, 0] * bary_u[:, np.newaxis]
        + triangles[:, 1] * bary_v[:, np.newaxis]
        + triangles[:, 2] * bary_w[:, np.newaxis]
    )


def _transform_points(points: np.ndarray, *, transform: vtk.vtkTransform) -> np.ndarray:
    if points.size == 0:
        return points
    return np.asarray(
        [
            transform.TransformPoint(float(point[0]), float(point[1]), float(point[2]))
            for point in points
        ],
        dtype=float,
    )


def _build_bounds_axes_actor(
    scene: PreviewScene,
    renderer: vtkRenderer,
    *,
    color: tuple[float, float, float] = _RGB_AXES_COLOR,
) -> vtkCubeAxesActor2D:
    tick_count = _scene_axis_tick_count(scene)
    axes_actor = vtkCubeAxesActor2D()
    axes_actor.SetCamera(renderer.GetActiveCamera())
    axes_actor.SetBounds(
        *scene.bounds_min_mm,
        *scene.bounds_max_mm,
    )
    axes_actor.SetFlyModeToOuterEdges()
    axes_actor.SetNumberOfLabels(tick_count)
    axes_actor.SetLabelFormat(_scene_axis_label_format(scene, tick_count))
    axes_actor.SetXLabel("X")
    axes_actor.SetYLabel("Y")
    axes_actor.SetZLabel("Z")
    axes_actor.GetAxisLabelTextProperty().SetColor(*color)
    axes_actor.GetAxisLabelTextProperty().SetFontSize(12)
    axes_actor.GetAxisTitleTextProperty().SetColor(*color)
    axes_actor.GetAxisTitleTextProperty().SetFontSize(13)
    axes_actor.GetAxisLabelTextProperty().ShadowOff()
    axes_actor.GetAxisTitleTextProperty().ShadowOff()
    return axes_actor


def _render_point_cloud_vtk(
    scene: PreviewScene,
    points: np.ndarray,
    *,
    point_size_px: int,
    width: int,
    height: int,
    output_dir: Path,
    output_name: str,
    orbit_pitch_deg: float,
    orbit_yaw_deg: float,
) -> Path:
    renderer = vtkRenderer()
    renderer.SetBackground(0.02, 0.03, 0.05)
    if hasattr(renderer, "SetUseDepthPeeling"):
        renderer.SetUseDepthPeeling(True)
    if hasattr(renderer, "SetMaximumNumberOfPeels"):
        renderer.SetMaximumNumberOfPeels(100)
    if hasattr(renderer, "SetOcclusionRatio"):
        renderer.SetOcclusionRatio(0.1)

    vtk_points = vtk.vtkPoints()
    verts = vtk.vtkCellArray()
    for point_index, point in enumerate(points):
        vtk_points.InsertNextPoint(float(point[0]), float(point[1]), float(point[2]))
        verts.InsertNextCell(1)
        verts.InsertCellPoint(point_index)

    poly_data = vtk.vtkPolyData()
    poly_data.SetPoints(vtk_points)
    poly_data.SetVerts(verts)

    mapper = vtkPolyDataMapper()
    mapper.SetInputData(poly_data)
    mapper.ScalarVisibilityOff()

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    prop = actor.GetProperty()
    prop.SetColor(*_DEFAULT_POINT_COLOR)
    prop.SetPointSize(point_size_px)
    prop.LightingOff()
    prop.SetAmbient(1.0)
    prop.SetDiffuse(0.0)
    prop.SetSpecular(0.0)
    if hasattr(prop, "SetRenderPointsAsSpheres"):
        prop.SetRenderPointsAsSpheres(True)
    renderer.AddActor(actor)
    renderer.AddActor2D(_build_bounds_axes_actor(scene, renderer))

    render_window = create_headless_vtk_render_window()
    render_window.AddRenderer(renderer)
    if hasattr(render_window, "SetAlphaBitPlanes"):
        render_window.SetAlphaBitPlanes(1)
    render_window.SetSize(width, height)
    render_window.SetMultiSamples(0)

    center = _scene_center(scene)
    distance = _preview_camera_distance(scene, width=width, height=height)
    camera_position = camera_position_from_orbit(
        center,
        distance,
        orbit_pitch_deg,
        orbit_yaw_deg,
    )
    bundle = _RendererBundle(renderer=renderer, window=render_window)
    try:
        image, _ = _render_view(
            bundle,
            camera_position=camera_position,
            lookat=center,
            up=(0.0, 0.0, 1.0),
            capture_depth=False,
        )
    finally:
        del render_window

    if image is None:
        raise RuntimeError("point cloud renderer returned no image")

    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / Path(output_name).name
    from PIL import Image

    Image.fromarray(image).save(image_path, "PNG")
    return image_path


def _render_point_cloud_matplotlib(
    scene: PreviewScene,
    points: np.ndarray,
    *,
    point_size_px: int,
    width: int,
    height: int,
    output_dir: Path,
    output_name: str,
    orbit_pitch_deg: float,
    orbit_yaw_deg: float,
) -> Path:
    figure = Figure(figsize=(width / 100.0, height / 100.0), dpi=100)
    FigureCanvasAgg(figure)
    figure.patch.set_facecolor((0.02, 0.03, 0.05))

    axes = figure.add_subplot(111, projection="3d")
    axes.set_facecolor((0.02, 0.03, 0.05))
    axes.scatter(
        points[:, 0],
        points[:, 1],
        points[:, 2],
        s=max(point_size_px, 1) ** 2 * 1.8,
        color=_DEFAULT_POINT_COLOR,
        depthshade=False,
        linewidths=0,
    )
    axes.set_xlabel("X")
    axes.set_ylabel("Y")
    axes.set_zlabel("Z")
    axes.tick_params(colors=(0.92, 0.92, 0.92))
    axes.xaxis.label.set_color((0.92, 0.92, 0.92))
    axes.yaxis.label.set_color((0.92, 0.92, 0.92))
    axes.zaxis.label.set_color((0.92, 0.92, 0.92))
    axes.view_init(elev=orbit_pitch_deg, azim=orbit_yaw_deg)

    bounds_min = np.asarray(scene.bounds_min_mm, dtype=float)
    bounds_max = np.asarray(scene.bounds_max_mm, dtype=float)
    center = np.asarray(scene.center_mm, dtype=float)
    half_span = np.maximum((bounds_max - bounds_min) * 0.5, 0.5)
    margin = half_span * _DEFAULT_POINT_CLOUD_FRAMING_MARGIN
    limits_min = center - margin
    limits_max = center + margin
    axes.set_xlim(limits_min[0], limits_max[0])
    axes.set_ylim(limits_min[1], limits_max[1])
    axes.set_zlim(limits_min[2], limits_max[2])
    axes.set_box_aspect(
        (
            max(limits_max[0] - limits_min[0], 1e-3),
            max(limits_max[1] - limits_min[1], 1e-3),
            max(limits_max[2] - limits_min[2], 1e-3),
        )
    )
    axes.grid(False)
    figure.subplots_adjust(left=0, right=1, bottom=0, top=1)

    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / Path(output_name).name
    figure.savefig(
        image_path,
        format="png",
        facecolor=figure.get_facecolor(),
        bbox_inches=None,
        pad_inches=0,
    )
    return image_path


def render_scene_point_cloud(
    scene_path: Path,
    *,
    output_dir: Path,
    output_name: str = "point_cloud.png",
    sample_limit: int = 50000,
    point_size_px: int = 4,
    render_backend: PointCloudRenderBackend = PointCloudRenderBackend.VTK,
    orbit_pitch_deg: float = _DEFAULT_POINT_CLOUD_PITCH_DEG,
    orbit_yaw_deg: float = _DEFAULT_POINT_CLOUD_YAW_DEG,
    width: int | None = None,
    height: int | None = None,
) -> PointCloudRenderResult:
    """Render a static point cloud from a preview scene bundle."""

    if width is None or height is None:
        default_width, default_height = get_image_render_resolution()
        width = default_width if width is None else width
        height = default_height if height is None else height

    scene, raw_scene_json = _load_preview_scene(scene_path)
    surfaces = _scene_surface_meshes(scene)
    sample_counts = _allocate_sample_counts(surfaces, sample_limit=sample_limit)
    rng = np.random.default_rng(
        _scene_signature(raw_scene_json, sample_limit=sample_limit)
    )

    sampled_points: list[np.ndarray] = []
    for surface_mesh, sample_count in zip(surfaces, sample_counts, strict=False):
        if sample_count <= 0:
            continue
        local_points = _sample_mesh_surface_points(
            surface_mesh.mesh,
            sample_count=sample_count,
            rng=rng,
        )
        transformed_points = _transform_points(
            local_points,
            transform=surface_mesh.transform,
        )
        sampled_points.append(transformed_points)

    if not sampled_points:
        raise ValueError("preview scene does not contain any sampleable surfaces")

    points = np.concatenate(sampled_points, axis=0)
    backend = PointCloudRenderBackend(render_backend)
    if backend == PointCloudRenderBackend.MATPLOTLIB:
        image_path = _render_point_cloud_matplotlib(
            scene,
            points,
            point_size_px=point_size_px,
            width=width,
            height=height,
            output_dir=output_dir,
            output_name=output_name,
            orbit_pitch_deg=orbit_pitch_deg,
            orbit_yaw_deg=orbit_yaw_deg,
        )
    else:
        image_path = _render_point_cloud_vtk(
            scene,
            points,
            point_size_px=point_size_px,
            width=width,
            height=height,
            output_dir=output_dir,
            output_name=output_name,
            orbit_pitch_deg=orbit_pitch_deg,
            orbit_yaw_deg=orbit_yaw_deg,
        )

    logger.info(
        "point_cloud_render_complete",
        path=str(image_path),
        scene_path=str(scene_path),
        sampled_point_count=len(points),
        source_surface_count=len(surfaces),
        backend=backend.value,
    )
    return PointCloudRenderResult(
        image_path=image_path,
        sampled_point_count=len(points),
        source_surface_count=len(surfaces),
    )
