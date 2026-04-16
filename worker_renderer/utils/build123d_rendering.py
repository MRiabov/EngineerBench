from __future__ import annotations

import base64
import colorsys
import math
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
import structlog
from build123d import Compound
from PIL import Image

from shared.agents import get_image_render_resolution
from shared.enums import ZoneType
from shared.models.schemas import (
    BenchmarkDefinition,
)
from shared.models.simulation import RendererCapabilities, RenderMode
from shared.rendering import (
    configure_headless_rendering,
    create_headless_vtk_render_window,
    materialize_preview_response,
)
from shared.simulation.backends import RendererBackend
from shared.simulation.scene_builder import (
    CommonAssemblyTraverser,
    MaterializedMovedObject,
    MeshProcessor,
    PreviewEntity,
    PreviewScene,
    materialize_moved_object,
    normalize_preview_label,
)
from shared.workers.bundling import bundle_directory_base64
from shared.workers.schema import SegmentationLegendEntry
from worker_renderer.utils.workbench_config import load_config, load_merged_config

configure_headless_rendering()
import vtk
from vtk.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkCommonTransforms import vtkTransform
from vtkmodules.vtkFiltersCore import vtkExtractEdges, vtkTubeFilter
from vtkmodules.vtkFiltersSources import vtkCubeSource
from vtkmodules.vtkIOGeometry import vtkOBJReader
from vtkmodules.vtkRenderingAnnotation import vtkCubeAxesActor2D
from vtkmodules.vtkRenderingCore import (
    vtkPolyDataMapper,
    vtkRenderer,
    vtkRenderWindow,
    vtkWindowToImageFilter,
)

logger = structlog.get_logger(__name__)

PREVIEW_BACKEND_NAME = "build123d_vtk"
_PARALLEL_MODALITIES_ENV = "PROBLEMOLOGIST_RENDER_PARALLEL_MODALITIES"
_FALSE_STRINGS = {"0", "false", "no", "off"}


@dataclass
class _RendererBundle:
    renderer: vtkRenderer
    window: vtkRenderWindow


@dataclass
class _CameraState:
    pos: tuple[float, float, float] | None = None
    lookat: tuple[float, float, float] | None = None
    up: tuple[float, float, float] | None = None
    fov: float | None = None


@dataclass
class PreviewRenderResult:
    saved_paths: list[str]
    legend_by_path: dict[str, list[SegmentationLegendEntry]]
    depth_ranges_by_path: dict[str, tuple[float, float]]


def _rgba_from_hex(color: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    color = color.lstrip("#")
    if len(color) != 6:
        return (0.62, 0.67, 0.73, alpha)
    r = int(color[0:2], 16) / 255.0
    g = int(color[2:4], 16) / 255.0
    b = int(color[4:6], 16) / 255.0
    return (r, g, b, alpha)


def _material_color_rgba(
    material_id: str | None, manufacturing_config
) -> tuple[float, float, float, float]:
    if not material_id:
        return (0.62, 0.67, 0.73, 1.0)

    material = manufacturing_config.materials.get(material_id)
    if material is None and manufacturing_config.cnc:
        material = manufacturing_config.cnc.materials.get(material_id)
    if material is None and manufacturing_config.injection_molding:
        material = manufacturing_config.injection_molding.materials.get(material_id)
    if material is None and manufacturing_config.three_dp:
        material = manufacturing_config.three_dp.materials.get(material_id)

    if material is None or not getattr(material, "color", None):
        return (0.62, 0.67, 0.73, 1.0)
    return _rgba_from_hex(material.color, 1.0)


def _zone_color(zone_type: ZoneType) -> tuple[float, float, float, float]:
    if zone_type == ZoneType.GOAL:
        return (0.20, 0.72, 0.34, 0.22)
    if zone_type == ZoneType.BUILD:
        return (0.55, 0.55, 0.55, 0.14)
    return (0.83, 0.20, 0.20, 0.20)


def _unique_color(index: int) -> tuple[int, int, int]:
    hue = (index * 0.61803398875) % 1.0
    saturation = 0.75
    value = 0.92
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
    return (
        int(round(red * 255.0)),
        int(round(green * 255.0)),
        int(round(blue * 255.0)),
    )


def _hex_from_rgb(color_rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02x}" for channel in color_rgb)


_RGB_EDGE_COLOR = (0.14, 0.14, 0.14)
_OVERLAY_EDGE_COLOR = (0.95, 0.68, 0.18)
_RGB_AXES_COLOR = (0.12, 0.12, 0.12)
_OVERLAY_AXES_COLOR = (0.94, 0.94, 0.94)
_PREVIEW_EDGE_OPACITY = 0.96
_PREVIEW_EDGE_LINE_WIDTH = 2.4
_PREVIEW_EDGE_LINE_OFFSET = (1.0, 1.0)
_DEFAULT_PREVIEW_VIEW_ANGLE_DEG = 30.0
_DEFAULT_PREVIEW_FRAMING_MARGIN = 1.25
_UNNAMED_PREVIEW_LABEL_PREFIX = "unnamed"


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _resolve_component_preview_label(
    raw_label: object | None, *, unnamed_label_factory
) -> str:
    normalized = normalize_preview_label(raw_label)
    if normalized:
        return normalized
    return unnamed_label_factory()


def _preview_render_stem(
    label: str,
    pitch: float,
    yaw: float,
    *,
    view_index: int | None = None,
    view_count: int = 1,
) -> str:
    base = f"{label}_render_e{abs(int(round(pitch)))}_a{int(round(yaw))}"
    if view_count > 1:
        if view_index is None:
            raise ValueError("view_index is required for multi-view preview naming")
        return f"{base}_v{view_index}"
    return base


def _scene_axis_tick_count(scene: PreviewScene) -> int:
    spans = [scene.bounds_max[i] - scene.bounds_min[i] for i in range(3)]
    longest_span = max(max(spans), 1e-6)
    # Aim for roughly 20 mm spacing, then clamp to the requested 7-13 range.
    label_count = int(round(longest_span / 20.0)) + 1
    return _clamp(label_count, 7, 13)


def _scene_axis_label_format(scene: PreviewScene, label_count: int) -> str:
    spans = [scene.bounds_max[i] - scene.bounds_min[i] for i in range(3)]
    longest_span = max(max(spans), 1e-6)
    spacing = longest_span / max(label_count - 1, 1)
    if spacing >= 10.0:
        return "%.0f"
    if spacing >= 1.0:
        return "%.1f"
    if spacing >= 0.1:
        return "%.2f"
    return "%.3f"


def _depth_buffer_to_uint8(depth_buffer: np.ndarray) -> np.ndarray:
    finite_mask = np.isfinite(depth_buffer)
    depth_render = np.zeros(depth_buffer.shape, dtype=np.uint8)
    if not finite_mask.any():
        return depth_render

    depth_min = float(depth_buffer[finite_mask].min())
    depth_max = float(depth_buffer[finite_mask].max())
    if np.isclose(depth_min, depth_max):
        normalized = np.ones(depth_buffer.shape, dtype=np.float32)
    else:
        normalized = (depth_buffer - depth_min) / (depth_max - depth_min)
        normalized = 1.0 - np.clip(normalized, 0.0, 1.0)
    depth_render[finite_mask] = (normalized[finite_mask] * 255.0).astype(np.uint8)
    return depth_render


def _depth_buffer_to_display_rgb(
    depth_buffer: np.ndarray,
) -> tuple[np.ndarray, tuple[float, float] | None]:
    finite_mask = np.isfinite(depth_buffer)
    depth_render = np.zeros(depth_buffer.shape + (3,), dtype=np.uint8)
    if not finite_mask.any():
        return depth_render, None

    depth_min = float(depth_buffer[finite_mask].min())
    depth_max = float(depth_buffer[finite_mask].max())
    if np.isclose(depth_min, depth_max):
        normalized = np.ones(depth_buffer.shape, dtype=np.float32)
    else:
        normalized = (depth_buffer - depth_min) / (depth_max - depth_min)
    normalized = np.clip(normalized, 0.0, 1.0)
    # Use a simple depth colormap so the artifact is clearly distinguishable
    # from the RGB preview while still encoding camera-space depth.
    t = 1.0 - normalized
    red = np.interp(
        t[finite_mask],
        [0.0, 0.35, 0.70, 1.0],
        [0.03, 0.00, 0.95, 1.00],
    )
    green = np.interp(
        t[finite_mask],
        [0.0, 0.35, 0.70, 1.0],
        [0.06, 0.50, 0.84, 1.00],
    )
    blue = np.interp(
        t[finite_mask],
        [0.0, 0.35, 0.70, 1.0],
        [0.20, 0.95, 0.25, 1.00],
    )
    depth_render[finite_mask, 0] = (red * 255.0).astype(np.uint8)
    depth_render[finite_mask, 1] = (green * 255.0).astype(np.uint8)
    depth_render[finite_mask, 2] = (blue * 255.0).astype(np.uint8)
    return depth_render, (depth_min, depth_max)


def _composite_non_black(
    base_image: np.ndarray, overlay_image: np.ndarray
) -> np.ndarray:
    if base_image.ndim == 2:
        base_rgb = np.repeat(base_image[:, :, np.newaxis], 3, axis=2)
    else:
        base_rgb = np.array(base_image, copy=True)

    if overlay_image.ndim == 2:
        overlay_rgb = np.repeat(overlay_image[:, :, np.newaxis], 3, axis=2)
    else:
        overlay_rgb = overlay_image

    mask = np.any(overlay_rgb > 0, axis=2)
    if mask.any():
        base_rgb[mask] = overlay_rgb[mask]
    return base_rgb


def _build_feature_edges_mapper(
    source: vtkCubeSource | vtkOBJReader,
) -> vtkPolyDataMapper:
    # Use all extracted edges, not just sharp feature edges. Many CAD preview
    # meshes are smooth or heavily triangulated, so feature-only edges can vanish
    # on sloped faces even when the object outline is important.
    edge_extractor = vtkExtractEdges()
    edge_extractor.SetInputConnection(source.GetOutputPort())
    edge_extractor.Update()

    mapper = vtkPolyDataMapper()
    mapper.SetInputConnection(edge_extractor.GetOutputPort())
    mapper.ScalarVisibilityOff()
    # Keep the wire-like edge pass slightly in front of the shaded surface so
    # coincident triangles do not hide the outline on shallow viewing angles.
    if hasattr(mapper, "SetResolveCoincidentTopologyToPolygonOffset"):
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        if hasattr(mapper, "SetRelativeCoincidentTopologyLineOffsetParameters"):
            mapper.SetRelativeCoincidentTopologyLineOffsetParameters(
                *_PREVIEW_EDGE_LINE_OFFSET
            )
    if hasattr(edge_extractor, "GetOutput"):
        output = edge_extractor.GetOutput()
        bounds = output.GetBounds() if output is not None else None
        if bounds is not None:
            spans = [
                float(bounds[1] - bounds[0]),
                float(bounds[3] - bounds[2]),
                float(bounds[5] - bounds[4]),
            ]
            diagonal = math.sqrt(sum(span * span for span in spans))
            radius = max(diagonal * 0.0035, 0.7)
            tube_filter = vtkTubeFilter()
            tube_filter.SetInputConnection(edge_extractor.GetOutputPort())
            tube_filter.SetRadius(radius)
            tube_filter.SetNumberOfSides(8)
            tube_filter.CappingOn()
            tube_filter.Update()
            mapper.SetInputConnection(tube_filter.GetOutputPort())
    return mapper


def _combined_bounds(
    component: Compound,
    objectives: BenchmarkDefinition | None,
    payload: MaterializedMovedObject | None = None,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    bbox = component.bounding_box()
    min_x, min_y, min_z = bbox.min.X, bbox.min.Y, bbox.min.Z
    max_x, max_y, max_z = bbox.max.X, bbox.max.Y, bbox.max.Z

    if payload is not None:
        try:
            payload_bbox = payload.start_geometry().bounding_box()
        except Exception:
            payload_bbox = None
        if payload_bbox is not None:
            min_x = min(min_x, payload_bbox.min.X)
            min_y = min(min_y, payload_bbox.min.Y)
            min_z = min(min_z, payload_bbox.min.Z)
            max_x = max(max_x, payload_bbox.max.X)
            max_y = max(max_y, payload_bbox.max.Y)
            max_z = max(max_z, payload_bbox.max.Z)

    if objectives is not None:
        for box in [
            objectives.objectives.goal_zone,
            *objectives.objectives.forbid_zones,
            objectives.objectives.build_zone,
        ]:
            min_x = min(min_x, box.min[0])
            min_y = min(min_y, box.min[1])
            min_z = min(min_z, box.min[2])
            max_x = max(max_x, box.max[0])
            max_y = max(max_y, box.max[1])
            max_z = max(max_z, box.max[2])

    return (min_x, min_y, min_z), (max_x, max_y, max_z)


def _preview_camera_distance(
    scene: PreviewScene,
    *,
    width: int,
    height: int,
    view_angle_deg: float = _DEFAULT_PREVIEW_VIEW_ANGLE_DEG,
    framing_margin: float = _DEFAULT_PREVIEW_FRAMING_MARGIN,
) -> float:
    """Return a perspective camera distance that keeps the scene fully in frame."""

    aspect_ratio = max(float(width) / max(float(height), 1.0), 1e-6)
    half_vertical_fov = math.radians(max(view_angle_deg, 1e-3) / 2.0)
    half_horizontal_fov = math.atan(math.tan(half_vertical_fov) * aspect_ratio)
    limiting_half_fov = max(min(half_vertical_fov, half_horizontal_fov), 1e-3)

    radius = max(scene.diagonal * 0.5, 0.5)
    return max(
        (radius / math.sin(limiting_half_fov)) * framing_margin,
        radius + 0.5,
    )


def _build_box_actor(
    size: tuple[float, float, float],
) -> tuple[vtkCubeSource, vtkPolyDataMapper]:
    source = vtkCubeSource()
    source.SetXLength(max(size[0] * 2.0, 1e-6))
    source.SetYLength(max(size[1] * 2.0, 1e-6))
    source.SetZLength(max(size[2] * 2.0, 1e-6))
    source.Update()
    mapper = vtkPolyDataMapper()
    mapper.SetInputConnection(source.GetOutputPort())
    return source, mapper


def _build_mesh_actor(mesh_path: Path) -> tuple[vtkOBJReader, vtkPolyDataMapper]:
    reader = vtkOBJReader()
    reader.SetFileName(str(mesh_path))
    reader.Update()
    mapper = vtkPolyDataMapper()
    mapper.SetInputConnection(reader.GetOutputPort())
    return reader, mapper


def _make_transform(
    pos: tuple[float, float, float], euler: tuple[float, float, float]
) -> vtkTransform:
    transform = vtkTransform()
    transform.PostMultiply()
    transform.Translate(*pos)
    transform.RotateX(float(euler[0]))
    transform.RotateY(float(euler[1]))
    transform.RotateZ(float(euler[2]))
    return transform


def _style_preview_edge_actor(
    actor: vtk.vtkActor, color: tuple[float, float, float]
) -> None:
    prop = actor.GetProperty()
    prop.SetColor(*color)
    prop.SetOpacity(1.0)
    prop.SetLineWidth(max(_PREVIEW_EDGE_LINE_WIDTH, 2.5))
    prop.LightingOff()


def _build_preview_edge_actor(
    source: vtkCubeSource | vtkOBJReader,
    *,
    transform: vtkTransform,
    color: tuple[float, float, float] = _RGB_EDGE_COLOR,
) -> vtk.vtkActor:
    mapper = _build_feature_edges_mapper(source)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.SetUserTransform(transform)
    _style_preview_edge_actor(actor, color)
    return actor


def _build_axes_actor(
    scene: PreviewScene,
    renderer: vtkRenderer,
    *,
    color: tuple[float, float, float] = _RGB_AXES_COLOR,
) -> vtkCubeAxesActor2D:
    tick_count = _scene_axis_tick_count(scene)
    axes_actor = vtkCubeAxesActor2D()
    axes_actor.SetCamera(renderer.GetActiveCamera())
    axes_actor.SetBounds(
        scene.bounds_min[0],
        scene.bounds_max[0],
        scene.bounds_min[1],
        scene.bounds_max[1],
        scene.bounds_min[2],
        scene.bounds_max[2],
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


def _load_manufacturing_config(workspace_root: Path):
    custom_config_path = workspace_root / "manufacturing_config.yaml"
    if custom_config_path.exists():
        return load_merged_config(custom_config_path)
    return load_config()


def _objective_zone_labels(objectives: BenchmarkDefinition | None) -> set[str]:
    if objectives is None:
        return set()
    labels = {"zone_goal", "zone_build"}
    labels.update(
        f"zone_forbid_{index}_{forbid.name}"
        for index, forbid in enumerate(objectives.objectives.forbid_zones)
    )
    return labels


def collect_preview_scene(
    component: Compound,
    *,
    objectives: BenchmarkDefinition | None,
    workspace_root: Path,
    smoke_test_mode: bool = False,
    mesh_root: Path | None = None,
) -> PreviewScene:
    """Materialize a renderable preview scene from a build123d assembly."""

    manufacturing_config = _load_manufacturing_config(workspace_root)
    unnamed_index = 1

    def next_unnamed_label() -> str:
        nonlocal unnamed_index
        label = f"{_UNNAMED_PREVIEW_LABEL_PREFIX}_{unnamed_index}"
        unnamed_index += 1
        return label

    component_label = _resolve_component_preview_label(
        getattr(component, "label", None), unnamed_label_factory=next_unnamed_label
    )
    traversed_parts = CommonAssemblyTraverser.traverse(
        component,
        allow_unnamed_labels=True,
        unnamed_label_factory=next_unnamed_label,
    )
    objective_labels = _objective_zone_labels(objectives)
    render_entities: list[PreviewEntity] = []
    payload = (
        materialize_moved_object(objectives.payload)
        if objectives is not None and getattr(objectives, "payload", None) is not None
        else None
    )

    temp_dir = None
    if mesh_root is None:
        temp_dir = tempfile.TemporaryDirectory()
        temp_root = Path(temp_dir.name)
    else:
        temp_root = mesh_root
        temp_root.mkdir(parents=True, exist_ok=True)

    try:
        mesh_processor = MeshProcessor()
        for part_index, part_data in enumerate(traversed_parts):
            if part_data.is_zone:
                if part_data.label in objective_labels:
                    continue
                zone_type = part_data.zone_type or ZoneType.FORBID
                zone_color = _zone_color(zone_type)
                render_entities.append(
                    PreviewEntity(
                        label=part_data.label,
                        semantic_label=part_data.label,
                        instance_id=part_data.label,
                        instance_name=part_data.label,
                        object_type="zone",
                        object_id=part_index,
                        pos=tuple(float(v) for v in part_data.pos),
                        euler=tuple(float(v) for v in part_data.euler),
                        box_size=tuple(
                            float(v)
                            for v in (part_data.zone_size or [0.05, 0.05, 0.05])
                        ),
                        zone_type=zone_type,
                        color_rgba=zone_color,
                        segmentation_color_rgb=_unique_color(part_index),
                        include_in_segmentation=False,
                    )
                )
                continue

            mesh_base = temp_root / part_data.label
            tolerance = 1.0 if smoke_test_mode else 0.1
            saved_paths = mesh_processor.process_geometry(
                part_data.part,
                mesh_base,
                decompose=False,
                tolerance=tolerance,
                angular_tolerance=tolerance,
            )
            obj_paths = sorted(
                str(path) for path in saved_paths if path.suffix == ".obj"
            )

            render_entities.append(
                PreviewEntity(
                    label=part_data.label,
                    semantic_label=part_data.label,
                    instance_id=part_data.label,
                    instance_name=part_data.label,
                    object_type="part",
                    object_id=part_index,
                    pos=tuple(float(v) for v in part_data.pos),
                    euler=tuple(float(v) for v in part_data.euler),
                    mesh_paths=obj_paths,
                    material_id=part_data.material_id,
                    body_name=part_data.label,
                    geom_name=Path(obj_paths[0]).stem if obj_paths else None,
                    color_rgba=_material_color_rgba(
                        part_data.material_id,
                        manufacturing_config,
                    ),
                    segmentation_color_rgb=_unique_color(part_index),
                )
            )

        if payload is not None:
            mesh_base = temp_root / payload.scene_name
            tolerance = 1.0 if smoke_test_mode else 0.1
            saved_paths = mesh_processor.process_geometry(
                payload.geometry,
                mesh_base,
                decompose=False,
                tolerance=tolerance,
                angular_tolerance=tolerance,
            )
            obj_paths = sorted(
                str(path) for path in saved_paths if path.suffix == ".obj"
            )
            payload_object_id = len(render_entities)
            render_entities.append(
                PreviewEntity(
                    label=payload.label,
                    semantic_label=payload.label,
                    instance_id=payload.label,
                    instance_name=payload.label,
                    object_type="part",
                    object_id=payload_object_id,
                    pos=payload.start_position,
                    euler=(0.0, 0.0, 0.0),
                    mesh_paths=obj_paths,
                    material_id=payload.material_id,
                    body_name=payload.scene_name,
                    geom_name=Path(obj_paths[0]).stem if obj_paths else None,
                    color_rgba=_material_color_rgba(
                        payload.material_id,
                        manufacturing_config,
                    ),
                    segmentation_color_rgb=_unique_color(payload_object_id),
                )
            )

        if objectives is not None:
            objective_entities = [
                (
                    "zone_goal",
                    ZoneType.GOAL,
                    objectives.objectives.goal_zone.min,
                    objectives.objectives.goal_zone.max,
                ),
                *(
                    (
                        f"zone_forbid_{index}_{zone.name}",
                        ZoneType.FORBID,
                        zone.min,
                        zone.max,
                    )
                    for index, zone in enumerate(objectives.objectives.forbid_zones)
                ),
                (
                    "zone_build",
                    ZoneType.BUILD,
                    objectives.objectives.build_zone.min,
                    objectives.objectives.build_zone.max,
                ),
            ]

            base_index = len(render_entities)
            for offset, (label, zone_type, zone_min, zone_max) in enumerate(
                objective_entities
            ):
                if label in {entity.label for entity in render_entities}:
                    continue
                pos = (
                    (zone_min[0] + zone_max[0]) / 2.0,
                    (zone_min[1] + zone_max[1]) / 2.0,
                    (zone_min[2] + zone_max[2]) / 2.0,
                )
                size = (
                    (zone_max[0] - zone_min[0]) / 2.0,
                    (zone_max[1] - zone_min[1]) / 2.0,
                    (zone_max[2] - zone_min[2]) / 2.0,
                )
                color_rgba = _zone_color(zone_type)
                render_entities.append(
                    PreviewEntity(
                        label=label,
                        semantic_label=label,
                        instance_id=label,
                        instance_name=label,
                        object_type="zone",
                        object_id=base_index + offset,
                        pos=pos,
                        euler=(0.0, 0.0, 0.0),
                        box_size=size,
                        zone_type=zone_type,
                        color_rgba=color_rgba,
                        segmentation_color_rgb=_unique_color(base_index + offset),
                        include_in_segmentation=False,
                    )
                )

        bounds_min, bounds_max = _combined_bounds(component, objectives, payload)
        center = tuple((bounds_min[i] + bounds_max[i]) / 2.0 for i in range(3))
        diagonal = math.sqrt(
            sum((bounds_max[i] - bounds_min[i]) ** 2 for i in range(3))
        )
        return PreviewScene(
            component_label=component_label,
            entities=render_entities,
            bounds_min=bounds_min,
            bounds_max=bounds_max,
            center=center,
            diagonal=max(diagonal, 1e-6),
        )
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def _add_entity_actors(
    renderer: vtkRenderer,
    entity: PreviewEntity,
    *,
    segmentation: bool,
    include_fill: bool,
    include_edges: bool,
    edge_color: tuple[float, float, float],
) -> None:
    if entity.kind if hasattr(entity, "kind") else False:  # pragma: no cover
        raise RuntimeError("legacy entity format is unsupported")

    if segmentation and not entity.include_in_segmentation:
        return

    if entity.box_size is not None:
        source, mapper = _build_box_actor(entity.box_size)
        actor = None
        if include_fill:
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.SetUserTransform(_make_transform(entity.pos, entity.euler))
    else:
        if not entity.mesh_paths:
            return
        for mesh_path in entity.mesh_paths:
            source, mapper = _build_mesh_actor(Path(mesh_path))
            actor = None
            if include_fill:
                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                actor.SetUserTransform(_make_transform(entity.pos, entity.euler))
                renderer.AddActor(actor)
                _apply_actor_style(actor, entity, segmentation=segmentation)
            if include_edges:
                renderer.AddActor(
                    _build_preview_edge_actor(
                        source,
                        transform=_make_transform(entity.pos, entity.euler),
                        color=edge_color,
                    )
                )
        return

    if actor is not None:
        renderer.AddActor(actor)
        _apply_actor_style(actor, entity, segmentation=segmentation)
    if include_edges:
        renderer.AddActor(
            _build_preview_edge_actor(
                source,
                transform=_make_transform(entity.pos, entity.euler),
                color=edge_color,
            )
        )


def _apply_actor_style(
    actor: vtk.vtkActor, entity: PreviewEntity, *, segmentation: bool
) -> None:
    prop = actor.GetProperty()
    if segmentation:
        color = entity.segmentation_color_rgb or (255, 255, 255)
        prop.SetColor(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)
        prop.SetOpacity(1.0)
        prop.SetInterpolationToFlat()
        prop.LightingOff()
        prop.SetAmbient(1.0)
        prop.SetDiffuse(0.0)
        prop.SetSpecular(0.0)
        return

    rgba = entity.color_rgba or (0.62, 0.67, 0.73, 1.0)
    prop.SetColor(rgba[0], rgba[1], rgba[2])
    prop.SetOpacity(rgba[3])
    prop.SetInterpolationToFlat()
    prop.LightingOff()
    prop.SetAmbient(1.0)
    prop.SetDiffuse(0.0)
    prop.SetSpecular(0.0)


def _build_renderer(
    scene: PreviewScene,
    *,
    width: int,
    height: int,
    segmentation: bool,
    include_axes: bool,
    include_edges: bool,
    include_fill: bool,
    axes_color: tuple[float, float, float],
    edge_color: tuple[float, float, float],
    background: tuple[float, float, float],
) -> _RendererBundle:
    configure_headless_rendering()
    renderer = vtkRenderer()
    renderer.SetBackground(*background)
    if hasattr(renderer, "SetUseDepthPeeling"):
        renderer.SetUseDepthPeeling(True)
    if hasattr(renderer, "SetMaximumNumberOfPeels"):
        renderer.SetMaximumNumberOfPeels(100)
    if hasattr(renderer, "SetOcclusionRatio"):
        renderer.SetOcclusionRatio(0.1)

    for entity in scene.entities:
        _add_entity_actors(
            renderer,
            entity,
            segmentation=segmentation,
            include_fill=include_fill,
            include_edges=include_edges,
            edge_color=edge_color,
        )

    if include_axes:
        axes_actor = _build_axes_actor(scene, renderer, color=axes_color)
        renderer.AddActor2D(axes_actor)

    render_window = create_headless_vtk_render_window()
    render_window.AddRenderer(renderer)
    if hasattr(render_window, "SetAlphaBitPlanes"):
        render_window.SetAlphaBitPlanes(1)
    render_window.SetSize(width, height)
    render_window.SetMultiSamples(0)
    return _RendererBundle(renderer=renderer, window=render_window)


def _build_payload_path_overlay_bundle(
    points: list[tuple[float, float, float]],
    *,
    width: int,
    height: int,
) -> _RendererBundle | None:
    if len(points) < 2:
        return None

    configure_headless_rendering()
    renderer = vtkRenderer()
    renderer.SetBackground(0.0, 0.0, 0.0)

    vtk_points = vtk.vtkPoints()
    polyline = vtk.vtkPolyLine()
    polyline.GetPointIds().SetNumberOfIds(len(points))
    for index, point in enumerate(points):
        vtk_points.InsertNextPoint(float(point[0]), float(point[1]), float(point[2]))
        polyline.GetPointIds().SetId(index, index)

    cells = vtk.vtkCellArray()
    cells.InsertNextCell(polyline)
    poly_data = vtk.vtkPolyData()
    poly_data.SetPoints(vtk_points)
    poly_data.SetLines(cells)

    mapper = vtkPolyDataMapper()
    mapper.SetInputData(poly_data)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    prop = actor.GetProperty()
    prop.SetColor(0.96, 0.26, 0.18)
    prop.SetLineWidth(5.0)
    prop.LightingOff()
    prop.SetAmbient(1.0)
    prop.SetDiffuse(0.0)
    prop.SetSpecular(0.0)
    if hasattr(prop, "SetRenderLinesAsTubes"):
        prop.SetRenderLinesAsTubes(True)
    renderer.AddActor(actor)

    render_window = create_headless_vtk_render_window()
    render_window.AddRenderer(renderer)
    if hasattr(render_window, "SetAlphaBitPlanes"):
        render_window.SetAlphaBitPlanes(1)
    render_window.SetSize(width, height)
    render_window.SetMultiSamples(0)
    return _RendererBundle(renderer=renderer, window=render_window)


def _preview_segmentation_legend(scene: PreviewScene) -> list[SegmentationLegendEntry]:
    legend: list[SegmentationLegendEntry] = []
    for entity in scene.entities:
        if not entity.include_in_segmentation:
            continue
        color = entity.segmentation_color_rgb or (255, 255, 255)
        legend.append(
            SegmentationLegendEntry(
                instance_id=entity.instance_id,
                instance_name=entity.instance_name,
                semantic_label=entity.semantic_label,
                object_type=entity.object_type,
                object_id=entity.object_id,
                body_name=entity.body_name,
                geom_name=entity.geom_name,
                color_rgb=color,
                color_hex=_hex_from_rgb(color),
            )
        )
    return legend


def _preview_scene_with_relative_mesh_paths(
    scene: PreviewScene, *, bundle_root: Path
) -> PreviewScene:
    normalized = scene.model_copy(deep=True)
    bundle_root = bundle_root.resolve()
    for entity in normalized.entities:
        if not entity.mesh_paths:
            continue
        entity.mesh_paths = [
            str(Path(path).resolve().relative_to(bundle_root))
            if Path(path).is_absolute()
            else str(Path(path))
            for path in entity.mesh_paths
        ]
    return normalized


def export_preview_scene_bundle(
    component: Compound,
    *,
    objectives: BenchmarkDefinition | None,
    workspace_root: Path,
    smoke_test_mode: bool = False,
) -> str:
    """Materialize a mesh-backed render bundle for renderer-worker handoff."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_root = Path(tmpdir)
        mesh_root = bundle_root / "meshes"
        mesh_root.mkdir(parents=True, exist_ok=True)
        current_role_path = workspace_root / ".manifests" / "current_role.json"
        if current_role_path.exists() and current_role_path.is_file():
            bundle_current_role_path = bundle_root / ".manifests" / "current_role.json"
            bundle_current_role_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current_role_path, bundle_current_role_path)
        for rel_path in (
            "benchmark_definition.yaml",
            "assembly_definition.yaml",
            "payload_trajectory_definition.yaml",
        ):
            source_path = workspace_root / rel_path
            if source_path.exists() and source_path.is_file():
                shutil.copy2(source_path, bundle_root / rel_path)
        scene = collect_preview_scene(
            component,
            objectives=objectives,
            workspace_root=workspace_root,
            smoke_test_mode=smoke_test_mode,
            mesh_root=mesh_root,
        )
        normalized_scene = _preview_scene_with_relative_mesh_paths(
            scene, bundle_root=bundle_root
        )
        (bundle_root / "preview_scene.json").write_text(
            normalized_scene.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info(
            "preview_scene_bundle_exported",
            bundle_root=str(bundle_root),
            entity_count=len(normalized_scene.entities),
        )
        return bundle_directory_base64(bundle_root)


def render_preview_scene(
    scene: PreviewScene,
    *,
    pitch: float = -35.0,
    yaw: float = 45.0,
    output_dir: Path | None = None,
    width: int | None = None,
    height: int | None = None,
    include_axes: bool = True,
    include_edges: bool = True,
    payload_path_points: list[tuple[float, float, float]] | None = None,
    include_payload_path_overlay: bool = False,
) -> Path:
    """Render a single preview image from a pre-built scene bundle."""
    if width is None or height is None:
        default_width, default_height = get_image_render_resolution()
        width = default_width if width is None else width
        height = default_height if height is None else height

    center = scene.center
    distance = _preview_camera_distance(scene, width=width, height=height)
    camera_position = camera_position_from_orbit(center, distance, pitch, yaw)
    bundle = _build_renderer(
        scene,
        width=width,
        height=height,
        segmentation=False,
        include_axes=include_axes,
        include_edges=include_edges,
        include_fill=True,
        axes_color=_RGB_AXES_COLOR,
        edge_color=_RGB_EDGE_COLOR,
        background=(0.98, 0.98, 0.99),
    )
    try:
        frame, _ = _render_view(
            bundle,
            camera_position=camera_position,
            lookat=center,
            up=(0.0, 0.0, 1.0),
            capture_depth=False,
        )
        if include_payload_path_overlay and payload_path_points:
            overlay_bundle = _build_payload_path_overlay_bundle(
                payload_path_points,
                width=width,
                height=height,
            )
            if overlay_bundle is not None:
                overlay_frame, _ = _render_view(
                    overlay_bundle,
                    camera_position=camera_position,
                    lookat=center,
                    up=(0.0, 0.0, 1.0),
                    capture_depth=False,
                )
                frame = _composite_non_black(frame, overlay_frame)
    finally:
        # VTK objects are owned by the bundle; let them fall out of scope.
        del bundle

    if output_dir is None:
        output_dir = Path("/tmp")
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_label = (
        normalize_preview_label(scene.component_label)
        or (normalize_preview_label(scene.entities[0].label) if scene.entities else "")
        or f"{_UNNAMED_PREVIEW_LABEL_PREFIX}_1"
    )
    image_path = output_dir / f"{_preview_render_stem(preview_label, pitch, yaw)}.png"
    Image.fromarray(frame).save(image_path, "PNG")
    return image_path


def render_preview_scene_bundle(
    scene: PreviewScene,
    *,
    output_dir: Path,
    workspace_root: Path | None = None,
    smoke_test_mode: bool = False,
    width: int | None = None,
    height: int | None = None,
    include_rgb: bool = True,
    include_depth: bool = True,
    include_segmentation: bool = True,
    rgb_axes: bool = True,
    rgb_edges: bool = True,
    depth_axes: bool = True,
    depth_edges: bool = True,
    segmentation_axes: bool = True,
    segmentation_edges: bool = True,
    payload_path_points: list[tuple[float, float, float]] | None = None,
    include_payload_path_overlay: bool = False,
) -> PreviewRenderResult:
    """Render the standard render bundle from a pre-built mesh scene."""
    if width is None or height is None:
        default_width, default_height = get_image_render_resolution()
        width = default_width if width is None else width
        height = default_height if height is None else height

    relative_root = workspace_root or (
        output_dir.parent.parent
        if output_dir.parent.name == "renders"
        else output_dir.parent
    )

    center = scene.center
    distance = _preview_camera_distance(scene, width=width, height=height)
    angles = [0, 45, 90, 135, 180, 225, 270, 315]
    elevations = [-15, -45, -75]
    preview_label = (
        normalize_preview_label(scene.component_label)
        or (normalize_preview_label(scene.entities[0].label) if scene.entities else "")
        or f"{_UNNAMED_PREVIEW_LABEL_PREFIX}_1"
    )
    view_specs = [(elevation, angle) for elevation in elevations for angle in angles]
    if smoke_test_mode:
        logger.info("smoke_test_mode_reducing_render_views")
        view_specs = [(-45.0, 45.0)]

    modality_jobs: list[str] = []
    if include_rgb:
        modality_jobs.append("rgb")
    if include_depth:
        modality_jobs.append("depth")
    if include_segmentation:
        modality_jobs.append("segmentation")

    parallel_modalities = (
        os.getenv(_PARALLEL_MODALITIES_ENV, "false").strip().lower()
        not in _FALSE_STRINGS
    )
    if parallel_modalities and not smoke_test_mode and len(modality_jobs) > 1:
        raise NotImplementedError(
            "Parallel preview modality rendering is not implemented outside "
            "smoke-test mode. Set PROBLEMOLOGIST_RENDER_PARALLEL_MODALITIES=false."
        )

    render_results: dict[str, _PreviewModalityRenderResult] = {}
    if parallel_modalities and len(modality_jobs) > 1:
        with ThreadPoolExecutor(max_workers=len(modality_jobs)) as executor:
            futures = {
                modality: executor.submit(
                    _render_preview_modality_bundle,
                    scene,
                    output_dir=output_dir,
                    workspace_root=relative_root,
                    center=center,
                    distance=distance,
                    width=width,
                    height=height,
                    preview_label=preview_label,
                    view_specs=view_specs,
                    include_payload_path_overlay=include_payload_path_overlay,
                    payload_path_points=payload_path_points,
                    modality=modality,
                    rgb_axes=rgb_axes,
                    rgb_edges=rgb_edges,
                    depth_axes=depth_axes,
                    depth_edges=depth_edges,
                    segmentation_axes=segmentation_axes,
                    segmentation_edges=segmentation_edges,
                )
                for modality in modality_jobs
            }
            for modality in modality_jobs:
                render_results[modality] = futures[modality].result()
    elif modality_jobs:
        modality = modality_jobs[0]
        render_results[modality] = _render_preview_modality_bundle(
            scene,
            output_dir=output_dir,
            workspace_root=relative_root,
            center=center,
            distance=distance,
            width=width,
            height=height,
            preview_label=preview_label,
            view_specs=view_specs,
            include_payload_path_overlay=include_payload_path_overlay,
            payload_path_points=payload_path_points,
            modality=modality,
            rgb_axes=rgb_axes,
            rgb_edges=rgb_edges,
            depth_axes=depth_axes,
            depth_edges=depth_edges,
            segmentation_axes=segmentation_axes,
            segmentation_edges=segmentation_edges,
        )

    legend_by_path: dict[str, list[SegmentationLegendEntry]] = {}
    depth_ranges_by_path: dict[str, tuple[float, float]] = {}
    for modality in ("rgb", "depth", "segmentation"):
        result = render_results.get(modality)
        if result is None:
            continue
        legend_by_path.update(result.legend_by_path)
        depth_ranges_by_path.update(result.depth_ranges_by_path)

    saved_paths: list[str] = []
    for elevation, angle in view_specs:
        group_key = _preview_render_stem(preview_label, elevation, angle)
        if "rgb" in render_results:
            saved_paths.append(
                str((output_dir / f"{group_key}.png").relative_to(relative_root))
            )
        if "depth" in render_results:
            saved_paths.append(
                str((output_dir / f"{group_key}_depth.png").relative_to(relative_root))
            )
        if "segmentation" in render_results:
            saved_paths.append(
                str(
                    (output_dir / f"{group_key}_segmentation.png").relative_to(
                        relative_root
                    )
                )
            )

    return PreviewRenderResult(
        saved_paths=saved_paths,
        legend_by_path=legend_by_path,
        depth_ranges_by_path=depth_ranges_by_path,
    )


def _configure_camera(
    renderer: vtkRenderer,
    *,
    camera_position: tuple[float, float, float],
    lookat: tuple[float, float, float],
    up: tuple[float, float, float],
    fov: float | None = None,
) -> None:
    camera = renderer.GetActiveCamera()
    camera.SetPosition(*camera_position)
    camera.SetFocalPoint(*lookat)
    camera.SetViewUp(*up)
    if fov is not None:
        camera.SetViewAngle(float(fov))
    camera.SetParallelProjection(False)


def _vtk_image_to_numpy_rgb(
    window: vtkRenderWindow, *, depth_buffer: bool = False
) -> np.ndarray:
    capture = vtkWindowToImageFilter()
    capture.SetInput(window)
    if depth_buffer:
        capture.SetInputBufferTypeToZBuffer()
        capture.ReadFrontBufferOff()
    capture.Update()
    image = capture.GetOutput()
    width, height, _ = image.GetDimensions()
    scalars = vtk_to_numpy(image.GetPointData().GetScalars())
    if depth_buffer:
        array = scalars.reshape(height, width).astype(np.float32)
        return np.flipud(array)
    channels = image.GetNumberOfScalarComponents()
    array = scalars.reshape(height, width, channels).astype(np.uint8)
    return np.flipud(array)


def _linearize_depth_buffer(
    depth_buffer: np.ndarray, near: float, far: float
) -> np.ndarray:
    depth = np.full_like(depth_buffer, np.inf, dtype=np.float32)
    valid = np.isfinite(depth_buffer) & (depth_buffer < 0.999999)
    if not valid.any():
        return depth

    z = depth_buffer[valid].astype(np.float32)
    denom = far + near - (2.0 * z - 1.0) * (far - near)
    with np.errstate(divide="ignore", invalid="ignore"):
        depth_values = (2.0 * near * far) / denom
    depth[valid] = depth_values.astype(np.float32)
    return depth


def _render_view(
    bundle: _RendererBundle,
    *,
    camera_position: tuple[float, float, float],
    lookat: tuple[float, float, float],
    up: tuple[float, float, float],
    fov: float | None = None,
    capture_rgb: bool = True,
    capture_depth: bool = False,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    _configure_camera(
        bundle.renderer,
        camera_position=camera_position,
        lookat=lookat,
        up=up,
        fov=fov,
    )
    bundle.renderer.ResetCameraClippingRange()
    bundle.window.Render()

    rgb_image = _vtk_image_to_numpy_rgb(bundle.window) if capture_rgb else None
    depth_image = None
    if capture_depth:
        depth_buffer = _vtk_image_to_numpy_rgb(bundle.window, depth_buffer=True)
        near, far = bundle.renderer.GetActiveCamera().GetClippingRange()
        depth_image = _linearize_depth_buffer(depth_buffer, near, far)
    return rgb_image, depth_image


@dataclass
class _PreviewModalityRenderResult:
    saved_paths: list[str]
    legend_by_path: dict[str, list[SegmentationLegendEntry]]
    depth_ranges_by_path: dict[str, tuple[float, float]]


def _render_preview_modality_bundle(
    scene: PreviewScene,
    *,
    output_dir: Path,
    workspace_root: Path,
    center: tuple[float, float, float],
    distance: float,
    width: int,
    height: int,
    preview_label: str,
    view_specs: list[tuple[float, float]],
    include_payload_path_overlay: bool,
    payload_path_points: list[tuple[float, float, float]] | None,
    modality: str,
    rgb_axes: bool,
    rgb_edges: bool,
    depth_axes: bool,
    depth_edges: bool,
    segmentation_axes: bool,
    segmentation_edges: bool,
) -> _PreviewModalityRenderResult:
    legend_entries = _preview_segmentation_legend(scene)
    saved_paths: list[str] = []
    legend_by_path: dict[str, list[SegmentationLegendEntry]] = {}
    depth_ranges_by_path: dict[str, tuple[float, float]] = {}
    bundle: _RendererBundle | None = None
    overlay_bundle: _RendererBundle | None = None

    if modality == "rgb":
        bundle = _build_renderer(
            scene,
            width=width,
            height=height,
            segmentation=False,
            include_axes=rgb_axes,
            include_edges=rgb_edges,
            include_fill=True,
            axes_color=_RGB_AXES_COLOR,
            edge_color=_RGB_EDGE_COLOR,
            background=(0.98, 0.98, 0.99),
        )
        overlay_bundle = None
        if include_payload_path_overlay and payload_path_points:
            overlay_bundle = _build_payload_path_overlay_bundle(
                payload_path_points,
                width=width,
                height=height,
            )
    elif modality == "depth":
        bundle = _build_renderer(
            scene,
            width=width,
            height=height,
            segmentation=False,
            include_axes=False,
            include_edges=False,
            include_fill=True,
            axes_color=_OVERLAY_AXES_COLOR,
            edge_color=_OVERLAY_EDGE_COLOR,
            background=(0.98, 0.98, 0.99),
        )
        overlay_bundle = None
        if depth_axes or depth_edges:
            overlay_bundle = _build_renderer(
                scene,
                width=width,
                height=height,
                segmentation=False,
                include_axes=depth_axes,
                include_edges=depth_edges,
                include_fill=False,
                axes_color=_OVERLAY_AXES_COLOR,
                edge_color=_OVERLAY_EDGE_COLOR,
                background=(0.0, 0.0, 0.0),
            )
    elif modality == "segmentation":
        bundle = _build_renderer(
            scene,
            width=width,
            height=height,
            segmentation=True,
            include_axes=False,
            include_edges=False,
            include_fill=True,
            axes_color=_OVERLAY_AXES_COLOR,
            edge_color=_OVERLAY_EDGE_COLOR,
            background=(0.0, 0.0, 0.0),
        )
        overlay_bundle = None
        if segmentation_axes or segmentation_edges:
            overlay_bundle = _build_renderer(
                scene,
                width=width,
                height=height,
                segmentation=False,
                include_axes=segmentation_axes,
                include_edges=segmentation_edges,
                include_fill=False,
                axes_color=_OVERLAY_AXES_COLOR,
                edge_color=_OVERLAY_EDGE_COLOR,
                background=(0.0, 0.0, 0.0),
            )
    else:  # pragma: no cover - defensive programming
        raise ValueError(f"unsupported modality: {modality}")

    try:
        for elevation, angle in view_specs:
            camera_position = camera_position_from_orbit(
                center, distance, elevation, angle
            )
            group_key = _preview_render_stem(preview_label, elevation, angle)
            rgb_path = output_dir / f"{group_key}.png"
            depth_path = output_dir / f"{group_key}_depth.png"
            segmentation_path = output_dir / f"{group_key}_segmentation.png"

            if modality == "rgb":
                rgb_image, _ = _render_view(
                    bundle,
                    camera_position=camera_position,
                    lookat=center,
                    up=(0.0, 0.0, 1.0),
                    capture_depth=False,
                )
                if overlay_bundle is not None:
                    rgb_overlay_image, _ = _render_view(
                        overlay_bundle,
                        camera_position=camera_position,
                        lookat=center,
                        up=(0.0, 0.0, 1.0),
                        capture_depth=False,
                    )
                    rgb_image = _composite_non_black(rgb_image, rgb_overlay_image)
                Image.fromarray(rgb_image).save(rgb_path, "PNG")
                saved_paths.append(str(rgb_path.relative_to(workspace_root)))
                continue

            if modality == "depth":
                _, depth_buffer = _render_view(
                    bundle,
                    camera_position=camera_position,
                    lookat=center,
                    up=(0.0, 0.0, 1.0),
                    capture_rgb=False,
                    capture_depth=True,
                )
                if depth_buffer is None:
                    raise RuntimeError("depth rendering was disabled for render")
                depth_render, depth_range = _depth_buffer_to_display_rgb(depth_buffer)
                if depth_range is not None:
                    depth_ranges_by_path[
                        str(depth_path.relative_to(workspace_root))
                    ] = depth_range
                if overlay_bundle is not None:
                    depth_overlay, _ = _render_view(
                        overlay_bundle,
                        camera_position=camera_position,
                        lookat=center,
                        up=(0.0, 0.0, 1.0),
                        capture_depth=False,
                    )
                    depth_render = _composite_non_black(depth_render, depth_overlay)
                Image.fromarray(depth_render, mode="RGB").save(depth_path, "PNG")
                saved_paths.append(str(depth_path.relative_to(workspace_root)))
                continue

            seg_image, _ = _render_view(
                bundle,
                camera_position=camera_position,
                lookat=center,
                up=(0.0, 0.0, 1.0),
                capture_depth=False,
            )
            if overlay_bundle is not None:
                seg_overlay, _ = _render_view(
                    overlay_bundle,
                    camera_position=camera_position,
                    lookat=center,
                    up=(0.0, 0.0, 1.0),
                    capture_depth=False,
                )
                seg_image = _composite_non_black(seg_image, seg_overlay)
            Image.fromarray(seg_image, mode="RGB").save(segmentation_path, "PNG")
            rel_segmentation_path = str(segmentation_path.relative_to(workspace_root))
            saved_paths.append(rel_segmentation_path)
            legend_by_path[rel_segmentation_path] = legend_entries
    finally:
        if bundle is not None:
            del bundle
        if overlay_bundle is not None:
            del overlay_bundle

    return _PreviewModalityRenderResult(
        saved_paths=saved_paths,
        legend_by_path=legend_by_path,
        depth_ranges_by_path=depth_ranges_by_path,
    )


def camera_position_from_orbit(
    center: tuple[float, float, float],
    distance: float,
    elevation_deg: float,
    azimuth_deg: float,
) -> tuple[float, float, float]:
    rad_azim = math.radians(azimuth_deg)
    rad_elev = math.radians(elevation_deg)
    x = center[0] + distance * math.cos(rad_elev) * math.sin(rad_azim)
    y = center[1] - distance * math.cos(rad_elev) * math.cos(rad_azim)
    z = center[2] - distance * math.sin(rad_elev)
    return (x, y, z)


class Build123dRendererBackend(RendererBackend):
    """RendererBackend implementation backed by build123d geometry and VTK."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        objectives: BenchmarkDefinition | None = None,
        smoke_test_mode: bool = False,
        include_axes: bool | None = None,
        include_edges: bool | None = None,
        rgb_axes: bool | None = None,
        rgb_edges: bool | None = None,
        depth_axes: bool | None = None,
        depth_edges: bool | None = None,
        segmentation_axes: bool | None = None,
        segmentation_edges: bool | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.objectives = objectives
        self.smoke_test_mode = smoke_test_mode
        default_axes = True if include_axes is None else include_axes
        default_edges = True if include_edges is None else include_edges
        self.rgb_axes = default_axes if rgb_axes is None else rgb_axes
        self.rgb_edges = default_edges if rgb_edges is None else rgb_edges
        self.depth_axes = self.rgb_axes if depth_axes is None else depth_axes
        self.depth_edges = self.rgb_edges if depth_edges is None else depth_edges
        self.segmentation_axes = (
            self.rgb_axes if segmentation_axes is None else segmentation_axes
        )
        self.segmentation_edges = (
            self.rgb_edges if segmentation_edges is None else segmentation_edges
        )
        self.scene: PreviewScene | None = None
        self._camera_states: dict[str, _CameraState] = {}
        self._mesh_temp_dir: tempfile.TemporaryDirectory | None = None

    def load_scene(self, scene: Compound, render_only: bool = False) -> None:
        del render_only
        self._cleanup_mesh_temp_dir()
        self._mesh_temp_dir = tempfile.TemporaryDirectory()
        self.scene = collect_preview_scene(
            scene,
            objectives=self.objectives,
            workspace_root=self.workspace_root,
            smoke_test_mode=self.smoke_test_mode,
            mesh_root=Path(self._mesh_temp_dir.name),
        )

    def render(self) -> np.ndarray:
        width, height = get_image_render_resolution()
        return self.render_camera("preview", width, height)

    def get_render_capabilities(self) -> RendererCapabilities:
        return RendererCapabilities(
            backend_name=PREVIEW_BACKEND_NAME,
            artifact_modes_supported=[RenderMode.STATIC_PREVIEW],
            supports_default_view=True,
            supports_named_cameras=True,
            supports_rgb=True,
            supports_depth=True,
            supports_segmentation=True,
            default_view_label="preview",
        )

    def render_camera(self, camera_name: str, width: int, height: int) -> np.ndarray:
        if self.scene is None:
            raise RuntimeError("Scene not loaded")

        logger.debug(
            "build123d_render_camera_start",
            camera_name=camera_name,
            width=width,
            height=height,
        )
        try:
            camera_position, lookat, up, fov = self._resolve_camera(
                camera_name, width=width, height=height
            )
            bundle = _build_renderer(
                self.scene,
                width=width,
                height=height,
                segmentation=False,
                include_axes=self.rgb_axes,
                include_edges=self.rgb_edges,
                include_fill=True,
                axes_color=_RGB_AXES_COLOR,
                edge_color=_RGB_EDGE_COLOR,
                background=(0.98, 0.98, 0.99),
            )
            rgb_image, _ = _render_view(
                bundle,
                camera_position=camera_position,
                lookat=lookat,
                up=up,
                fov=fov,
                capture_depth=False,
            )
            logger.debug(
                "build123d_render_camera_complete",
                camera_name=camera_name,
                width=width,
                height=height,
                shape=tuple(rgb_image.shape),
            )
            return rgb_image
        except Exception as exc:
            logger.error(
                "build123d_render_camera_failed",
                camera_name=camera_name,
                width=width,
                height=height,
                error=str(exc),
            )
            raise

    def get_particle_positions(self) -> np.ndarray | None:
        return None

    def render_camera_modalities(
        self,
        camera_name: str,
        width: int,
        height: int,
        *,
        include_rgb: bool = True,
        include_depth: bool = True,
        include_segmentation: bool = True,
    ) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
        if self.scene is None:
            raise RuntimeError("Scene not loaded")

        logger.debug(
            "build123d_render_camera_modalities_start",
            camera_name=camera_name,
            width=width,
            height=height,
            include_rgb=include_rgb,
            include_depth=include_depth,
            include_segmentation=include_segmentation,
        )
        try:
            camera_position, lookat, up, fov = self._resolve_camera(
                camera_name, width=width, height=height
            )
            rgb_bundle: _RendererBundle | None = None
            if include_rgb:
                rgb_bundle = _build_renderer(
                    self.scene,
                    width=width,
                    height=height,
                    segmentation=False,
                    include_axes=self.rgb_axes,
                    include_edges=self.rgb_edges,
                    include_fill=True,
                    axes_color=_RGB_AXES_COLOR,
                    edge_color=_RGB_EDGE_COLOR,
                    background=(0.98, 0.98, 0.99),
                )

            depth_base_bundle: _RendererBundle | None = None
            depth_overlay_bundle: _RendererBundle | None = None
            if include_depth:
                depth_base_bundle = _build_renderer(
                    self.scene,
                    width=width,
                    height=height,
                    segmentation=False,
                    include_axes=False,
                    include_edges=False,
                    include_fill=True,
                    axes_color=_OVERLAY_AXES_COLOR,
                    edge_color=_OVERLAY_EDGE_COLOR,
                    background=(0.98, 0.98, 0.99),
                )
                if self.depth_axes or self.depth_edges:
                    depth_overlay_bundle = _build_renderer(
                        self.scene,
                        width=width,
                        height=height,
                        segmentation=False,
                        include_axes=self.depth_axes,
                        include_edges=self.depth_edges,
                        include_fill=False,
                        axes_color=_OVERLAY_AXES_COLOR,
                        edge_color=_OVERLAY_EDGE_COLOR,
                        background=(0.0, 0.0, 0.0),
                    )

            seg_base_bundle: _RendererBundle | None = None
            seg_overlay_bundle: _RendererBundle | None = None
            if include_segmentation:
                seg_base_bundle = _build_renderer(
                    self.scene,
                    width=width,
                    height=height,
                    segmentation=True,
                    include_axes=False,
                    include_edges=False,
                    include_fill=True,
                    axes_color=_OVERLAY_AXES_COLOR,
                    edge_color=_OVERLAY_EDGE_COLOR,
                    background=(0.0, 0.0, 0.0),
                )
                if self.segmentation_axes or self.segmentation_edges:
                    seg_overlay_bundle = _build_renderer(
                        self.scene,
                        width=width,
                        height=height,
                        segmentation=False,
                        include_axes=self.segmentation_axes,
                        include_edges=self.segmentation_edges,
                        include_fill=False,
                        axes_color=_OVERLAY_AXES_COLOR,
                        edge_color=_OVERLAY_EDGE_COLOR,
                        background=(0.0, 0.0, 0.0),
                    )

            rgb_image: np.ndarray | None = None
            depth_image: np.ndarray | None = None
            seg_image: np.ndarray | None = None

            if rgb_bundle is not None:
                rgb_image, _ = _render_view(
                    rgb_bundle,
                    camera_position=camera_position,
                    lookat=lookat,
                    up=up,
                    fov=fov,
                    capture_depth=False,
                )
            if depth_base_bundle is not None:
                _, depth_buffer = _render_view(
                    depth_base_bundle,
                    camera_position=camera_position,
                    lookat=lookat,
                    up=up,
                    fov=fov,
                    capture_depth=True,
                )
                if depth_buffer is None:
                    raise RuntimeError("depth rendering was disabled for render")
                depth_render = _depth_buffer_to_uint8(depth_buffer)
                if depth_overlay_bundle is not None:
                    depth_overlay, _ = _render_view(
                        depth_overlay_bundle,
                        camera_position=camera_position,
                        lookat=lookat,
                        up=up,
                        fov=fov,
                        capture_depth=False,
                    )
                    depth_image = _composite_non_black(depth_render, depth_overlay)
                else:
                    depth_image = depth_render
            if seg_base_bundle is not None:
                seg_image, _ = _render_view(
                    seg_base_bundle,
                    camera_position=camera_position,
                    lookat=lookat,
                    up=up,
                    fov=fov,
                    capture_depth=False,
                )
                if seg_overlay_bundle is not None:
                    seg_overlay, _ = _render_view(
                        seg_overlay_bundle,
                        camera_position=camera_position,
                        lookat=lookat,
                        up=up,
                        fov=fov,
                        capture_depth=False,
                    )
                    seg_image = _composite_non_black(seg_image, seg_overlay)
            logger.debug(
                "build123d_render_camera_modalities_complete",
                camera_name=camera_name,
                width=width,
                height=height,
                include_rgb=include_rgb,
                include_depth=include_depth,
                include_segmentation=include_segmentation,
                rgb_shape=tuple(rgb_image.shape) if rgb_image is not None else None,
                depth_shape=(
                    tuple(depth_image.shape) if depth_image is not None else None
                ),
                segmentation_shape=(
                    tuple(seg_image.shape) if seg_image is not None else None
                ),
            )
            return (
                rgb_image if include_rgb else None,
                depth_image if include_depth else None,
                seg_image if include_segmentation else None,
            )
        except Exception as exc:
            logger.error(
                "build123d_render_camera_modalities_failed",
                camera_name=camera_name,
                width=width,
                height=height,
                include_rgb=include_rgb,
                include_depth=include_depth,
                include_segmentation=include_segmentation,
                error=str(exc),
            )
            raise

    def describe_segmentation(
        self, segmentation_frame: np.ndarray
    ) -> list[SegmentationLegendEntry]:
        del segmentation_frame
        if self.scene is None:
            return []

        legend: list[SegmentationLegendEntry] = []
        for entity in self.scene.entities:
            if not entity.include_in_segmentation:
                continue
            if entity.segmentation_color_rgb is None:
                continue
            legend.append(
                SegmentationLegendEntry(
                    instance_id=entity.instance_id,
                    instance_name=entity.instance_name,
                    semantic_label=entity.semantic_label,
                    object_type=entity.object_type,
                    object_id=entity.object_id,
                    body_name=entity.body_name,
                    geom_name=entity.geom_name,
                    color_rgb=entity.segmentation_color_rgb,
                    color_hex=_hex_from_rgb(entity.segmentation_color_rgb),
                )
            )
        return legend

    def set_camera(
        self,
        camera_name: str,
        pos: tuple[float, float, float] | None = None,
        lookat: tuple[float, float, float] | None = None,
        up: tuple[float, float, float] | None = None,
        fov: float | None = None,
    ) -> None:
        self._camera_states[camera_name] = _CameraState(
            pos=pos,
            lookat=lookat,
            up=up,
            fov=fov,
        )

    def get_all_camera_names(self) -> list[str]:
        names = list(self._camera_states.keys())
        if not names:
            names.append("preview")
        return sorted(dict.fromkeys(names))

    def close(self) -> None:
        self.scene = None
        self._camera_states.clear()
        self._cleanup_mesh_temp_dir()

    def _resolve_camera(
        self, camera_name: str, *, width: int, height: int
    ) -> tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
        float | None,
    ]:
        if self.scene is None:
            raise RuntimeError("Scene not loaded")

        state = self._camera_states.get(camera_name)
        if state and state.pos is not None and state.lookat is not None:
            return (
                state.pos,
                state.lookat,
                state.up or (0.0, 0.0, 1.0),
                state.fov,
            )

        distance = _preview_camera_distance(
            self.scene,
            width=width,
            height=height,
            view_angle_deg=state.fov
            if state and state.fov is not None
            else _DEFAULT_PREVIEW_VIEW_ANGLE_DEG,
        )
        default_lookat = self.scene.center
        default_pos = camera_position_from_orbit(
            default_lookat,
            distance,
            -35.0,
            45.0,
        )
        return (
            default_pos,
            default_lookat,
            (0.0, 0.0, 1.0),
            state.fov if state else None,
        )

    def _cleanup_mesh_temp_dir(self) -> None:
        if self._mesh_temp_dir is None:
            return
        self._mesh_temp_dir.cleanup()
        self._mesh_temp_dir = None


def render_preview_view(
    component: Compound,
    *,
    output_path: Path,
    pitch: float,
    yaw: float,
    objectives: BenchmarkDefinition | None = None,
    smoke_test_mode: bool = False,
    workspace_root: Path,
    include_axes: bool = True,
    include_edges: bool = True,
    width: int | None = None,
    height: int | None = None,
) -> Path:
    """Render a single build123d preview image via the dedicated renderer."""
    if width is None or height is None:
        default_width, default_height = get_image_render_resolution()
        width = default_width if width is None else width
        height = default_height if height is None else height

    bundle_base64 = export_preview_scene_bundle(
        component,
        objectives=objectives,
        workspace_root=workspace_root,
        smoke_test_mode=smoke_test_mode,
    )
    from shared.rendering.renderer_client import render_preview

    response = render_preview(
        bundle_base64=bundle_base64,
        script_path="preview_scene.json",
        orbit_pitch=pitch,
        orbit_yaw=yaw,
        session_id=os.getenv("SESSION_ID"),
        agent_role=os.getenv("AGENT_NAME") or None,
    )
    if not response.success:
        raise RuntimeError(response.message or "build123d preview render failed")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    materialized_path = materialize_preview_response(response, output_path.parent)
    if materialized_path is not None:
        if materialized_path != output_path:
            shutil.copy2(materialized_path, output_path)
        return output_path

    if not response.image_bytes_base64:
        raise RuntimeError("renderer returned no preview image bytes")

    image_bytes = base64.b64decode(response.image_bytes_base64)
    output_suffix = output_path.suffix.lower()
    output_format_map = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
    }
    output_format = output_format_map.get(output_suffix)
    if output_format is None:
        output_path.write_bytes(image_bytes)
        return output_path

    with Image.open(BytesIO(image_bytes)) as preview_image:
        image_to_save = preview_image
        if output_format == "JPEG" and preview_image.mode not in {"RGB", "L"}:
            image_to_save = preview_image.convert("RGB")
        image_to_save.save(output_path, format=output_format)
    return output_path


def render_preview_bundle(
    component: Compound,
    *,
    output_dir: Path,
    objectives: BenchmarkDefinition | None = None,
    smoke_test_mode: bool = False,
    workspace_root: Path,
    rgb_axes: bool = True,
    rgb_edges: bool = True,
    depth_axes: bool = True,
    depth_edges: bool = True,
    segmentation_axes: bool = True,
    segmentation_edges: bool = True,
    include_rgb: bool = True,
    include_depth: bool = True,
    include_segmentation: bool = True,
    width: int | None = None,
    height: int | None = None,
) -> PreviewRenderResult:
    """
    Render the standard render bundle through build123d/VTK.

    Returns the saved render paths and the per-entity segmentation legend.
    """
    if width is None or height is None:
        default_width, default_height = get_image_render_resolution()
        width = default_width if width is None else width
        height = default_height if height is None else height

    backend = Build123dRendererBackend(
        workspace_root=workspace_root,
        objectives=objectives,
        smoke_test_mode=smoke_test_mode,
        rgb_axes=rgb_axes,
        rgb_edges=rgb_edges,
        depth_axes=depth_axes,
        depth_edges=depth_edges,
        segmentation_axes=segmentation_axes,
        segmentation_edges=segmentation_edges,
    )
    try:
        backend.load_scene(component)
        scene = backend.scene
        if scene is None:
            raise RuntimeError("build123d preview scene failed to load")
        return render_preview_scene_bundle(
            scene,
            output_dir=output_dir,
            workspace_root=workspace_root,
            smoke_test_mode=smoke_test_mode,
            width=width,
            height=height,
            include_rgb=include_rgb,
            include_depth=include_depth,
            include_segmentation=include_segmentation,
            rgb_axes=rgb_axes,
            rgb_edges=rgb_edges,
            depth_axes=depth_axes,
            depth_edges=depth_edges,
            segmentation_axes=segmentation_axes,
            segmentation_edges=segmentation_edges,
        )
    finally:
        backend.close()


# Backward compatibility for the earlier name while the rename settles.
Build123dViewerBackend = Build123dRendererBackend
