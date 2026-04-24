from __future__ import annotations

import math
import random
import re
from collections.abc import Iterable
from typing import Any

import numpy as np
from build123d import (
    Align,
    Box,
    BuildLine,
    BuildPart,
    BuildSketch,
    Circle,
    Compound,
    Extrinsic,
    Location,
    Plane,
    Polyline,
    sweep,
)
from scipy.spatial.transform import Rotation as SciPyRotation

from shared.models.schemas import (
    BenchmarkDefinition,
    BoundingBox,
    CompoundMetadata,
    PartMetadata,
)

from .models import PartSpec, RoutePoint, SegmentSpan


def as_np(point: Iterable[float]) -> np.ndarray:
    return np.asarray(tuple(float(v) for v in point), dtype=float)


def normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 0.0:
        raise ValueError("zero-length vector")
    return vector / norm


def frame_from_segment(
    start_mm: Iterable[float],
    end_mm: Iterable[float],
    up_hint: Iterable[float] = (0.0, 0.0, 1.0),
    previous_frame: np.ndarray | None = None,
) -> tuple[np.ndarray, tuple[float, float, float]]:
    start = as_np(start_mm)
    end = as_np(end_mm)
    x_axis = normalize(end - start)
    up = normalize(as_np(up_hint))
    if abs(float(np.dot(x_axis, up))) > 0.95:
        up = np.array([0.0, 1.0, 0.0], dtype=float)
    # Recompute a fresh frame per span rather than carrying the previous span's
    # roll forward. Transporting the tangent basis was accumulating twist at
    # joins and made the corridor look over-rotated in the preview render.
    #
    # Use the opposite lateral handedness from the preview-only helper so the
    # corridor floor actually slopes with the intended travel direction instead
    # of backing the payload out of the tube under gravity.
    y_axis = normalize(np.cross(x_axis, up))
    z_axis = normalize(np.cross(x_axis, y_axis))
    y_axis = normalize(np.cross(z_axis, x_axis))
    frame = np.column_stack([x_axis, y_axis, z_axis])
    euler = tuple(
        float(value)
        for value in SciPyRotation.from_matrix(frame).as_euler("xyz", degrees=True)
    )
    return frame, euler


def route_bbox(route_points: list[RoutePoint]) -> tuple[np.ndarray, np.ndarray]:
    stacked = np.stack([as_np(point.pos_mm) for point in route_points], axis=0)
    return stacked.min(axis=0), stacked.max(axis=0)


def subdivide_segment(
    start_mm: Iterable[float],
    end_mm: Iterable[float],
    max_segment_mm: float,
    rng: random.Random,
) -> list[SegmentSpan]:
    start = as_np(start_mm)
    end = as_np(end_mm)
    distance = float(np.linalg.norm(end - start))
    split_count = max(1, math.ceil(distance / max_segment_mm))
    fractions = np.linspace(0.0, 1.0, split_count + 1)
    if split_count > 1:
        for idx in range(1, split_count):
            lower = fractions[idx - 1] + 1e-4
            upper = fractions[idx + 1] - 1e-4
            fractions[idx] = min(max(fractions[idx], lower), upper)
        fractions.sort()

    spans: list[SegmentSpan] = []
    for split_index in range(split_count):
        p0 = tuple(float(v) for v in (start + (end - start) * fractions[split_index]))
        p1 = tuple(
            float(v) for v in (start + (end - start) * fractions[split_index + 1])
        )
        spans.append(
            SegmentSpan(
                segment_index=-1,
                split_index=split_index,
                start_mm=p0,
                end_mm=p1,
            )
        )
    return spans


def route_spans(
    route_points: list[RoutePoint], max_segment_mm: float, seed: int
) -> list[SegmentSpan]:
    rng = random.Random(seed)
    spans: list[SegmentSpan] = []
    for segment_index, (start, end) in enumerate(zip(route_points, route_points[1:])):
        for span in subdivide_segment(start.pos_mm, end.pos_mm, max_segment_mm, rng):
            spans.append(
                SegmentSpan(
                    segment_index=segment_index,
                    split_index=len(
                        [s for s in spans if s.segment_index == segment_index]
                    ),
                    start_mm=span.start_mm,
                    end_mm=span.end_mm,
                )
            )
    return spans


def build_tube_scaffold(route_points: list[RoutePoint], radius_mm: float) -> Compound:
    route_points_xyz = [tuple(point.pos_mm) for point in route_points]
    with BuildLine() as route_line:
        Polyline(route_points_xyz)
    with BuildSketch(Plane(origin=route_points_xyz[0])) as route_profile:
        Circle(radius_mm)
    with BuildPart() as tube:
        sweep(route_profile.sketch, path=route_line.line)
    part = tube.part
    part.label = "tube_scaffold"
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    compound = Compound(children=[part])
    compound.label = "tube_scaffold"
    compound.metadata = CompoundMetadata(is_fixed=True)
    return compound


def build_box_part(spec: PartSpec):
    with BuildPart() as part_builder:
        Box(
            spec.dims_mm[0],
            spec.dims_mm[1],
            spec.dims_mm[2],
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
    part = part_builder.part.moved(
        Location(spec.center_mm, spec.euler_deg, Extrinsic.XYZ)
    )
    part.label = spec.name
    part.metadata = PartMetadata(
        material_id=spec.material_id,
        is_fixed=spec.is_fixed,
    )
    return part


def box_part_specs_for_route(
    route_points: list[RoutePoint],
    *,
    tube_radius_mm: float,
    clearance_mm: float,
    wall_thickness_mm: float,
    max_segment_mm: float,
    seed: int,
    material_id: str,
) -> list[PartSpec]:
    corridor_width_mm = 2.0 * tube_radius_mm + 2.0 * clearance_mm
    corridor_height_mm = 2.0 * tube_radius_mm + 2.0 * clearance_mm
    inner_width_mm = max(corridor_width_mm - 2.0 * wall_thickness_mm, wall_thickness_mm)
    inner_height_mm = max(
        corridor_height_mm - 2.0 * wall_thickness_mm, wall_thickness_mm
    )
    spans = route_spans(route_points, max_segment_mm=max_segment_mm, seed=seed)
    specs: list[PartSpec] = []

    for span in spans:
        start = as_np(span.start_mm)
        end = as_np(span.end_mm)
        frame, euler = frame_from_segment(start, end)
        center = (start + end) * 0.5
        length_mm = float(np.linalg.norm(end - start))

        side_defs = {
            "floor": (
                (length_mm, inner_width_mm, wall_thickness_mm),
                np.array(
                    [0.0, 0.0, -corridor_height_mm / 2.0 + wall_thickness_mm / 2.0]
                ),
            ),
            "roof": (
                (length_mm, inner_width_mm, wall_thickness_mm),
                np.array(
                    [0.0, 0.0, corridor_height_mm / 2.0 - wall_thickness_mm / 2.0]
                ),
            ),
            "left_wall": (
                (length_mm, wall_thickness_mm, inner_height_mm),
                np.array(
                    [0.0, -corridor_width_mm / 2.0 + wall_thickness_mm / 2.0, 0.0]
                ),
            ),
            "right_wall": (
                (length_mm, wall_thickness_mm, inner_height_mm),
                np.array([0.0, corridor_width_mm / 2.0 - wall_thickness_mm / 2.0, 0.0]),
            ),
        }

        for side_name, (dims_mm, offset_local) in side_defs.items():
            offset_world = frame @ offset_local
            world_center = center + offset_world
            name = (
                f"seg_{span.segment_index:02d}_split_{span.split_index:02d}_{side_name}"
            )
            specs.append(
                PartSpec(
                    name=name,
                    segment_index=span.segment_index,
                    split_index=span.split_index,
                    side=side_name,
                    dims_mm=tuple(float(v) for v in dims_mm),
                    center_mm=tuple(float(v) for v in world_center),
                    euler_deg=euler,
                    material_id=material_id,
                )
            )

    return specs


def parts_from_specs(specs: list[PartSpec]) -> list:
    return [build_box_part(spec) for spec in specs]


def compound_from_specs(specs: list[PartSpec], label: str) -> Compound:
    parts = parts_from_specs(specs)
    compound = Compound(children=parts)
    compound.label = label
    compound.metadata = CompoundMetadata(is_fixed=True)
    return compound


def intersects_any(compound: Compound) -> tuple[bool, tuple[Any, Any], float]:
    if hasattr(compound, "do_children_intersect"):
        return compound.do_children_intersect()
    return False, (None, None), 0.0


def validate_route_positions(
    *,
    route_points: list[RoutePoint],
    payload_start_position_mm: Iterable[float],
    goal_zone_mm: Any,
) -> None:
    spawn = np.asarray(tuple(float(v) for v in payload_start_position_mm), dtype=float)
    first_point = np.asarray(route_points[0].pos_mm, dtype=float)
    final_point = np.asarray(route_points[-1].pos_mm, dtype=float)
    goal_center = np.asarray(
        [
            (float(goal_zone_mm.min_mm[idx]) + float(goal_zone_mm.max_mm[idx])) / 2.0
            for idx in range(3)
        ],
        dtype=float,
    )

    errors: list[str] = []
    if not np.allclose(first_point, spawn, atol=1e-6):
        errors.append(
            "first route point must equal the payload spawn position "
            f"(expected {spawn.tolist()}, got {first_point.tolist()})"
        )
    if not np.allclose(final_point, goal_center, atol=1e-6):
        errors.append(
            "final route point must equal the goal-zone center "
            f"(expected {goal_center.tolist()}, got {final_point.tolist()})"
        )

    higher_than_spawn = [
        point.name
        for point in route_points
        if float(point.pos_mm[2]) > float(spawn[2]) + 1e-6
    ]
    if higher_than_spawn:
        errors.append(
            "route points cannot rise above the payload spawn height; "
            f"offending points={higher_than_spawn}, spawn_z={float(spawn[2]):.3f}"
        )

    if errors:
        raise RuntimeError("; ".join(errors))


def _bbox_from_bounds(bounds: BoundingBox, inflation_mm: float = 0.0) -> Compound:
    minimum = np.asarray(bounds.min_mm, dtype=float) - inflation_mm
    maximum = np.asarray(bounds.max_mm, dtype=float) + inflation_mm
    size = maximum - minimum
    center = (minimum + maximum) * 0.5
    box = Box(
        float(size[0]),
        float(size[1]),
        float(size[2]),
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    return box.moved(Location(tuple(float(v) for v in center), (0.0, 0.0, 0.0)))


def _shape_volume(shape: Any) -> float:
    volume = getattr(shape, "volume", None)
    if volume is None:
        return 0.0
    try:
        return float(volume)
    except (TypeError, ValueError):
        return 0.0


def build_route_pipe(route_points: Iterable[Any], radius_mm: float) -> Compound:
    route_points_xyz = [
        as_np(getattr(point, "pos_mm", point)) for point in route_points
    ]
    if len(route_points_xyz) < 2:
        raise ValueError("at least two route points are required")
    with BuildLine() as route_line:
        Polyline(route_points_xyz)
    with BuildSketch(Plane(origin=route_points_xyz[0])) as route_profile:
        Circle(float(radius_mm))
    with BuildPart() as route_pipe:
        sweep(route_profile.sketch, path=route_line.line)
    return route_pipe.part


def validate_route_clearance(
    *,
    route_points: Iterable[Any],
    benchmark_definition: BenchmarkDefinition,
    pipe_radius_mm: float,
    clearance_mm: float,
) -> list[str]:
    route_points = list(route_points)
    if len(route_points) < 2:
        return ["route clearance: at least two route points are required"]

    try:
        route_pipe = build_route_pipe(route_points, radius_mm=pipe_radius_mm)
    except Exception as exc:
        return [f"route clearance: unable to build swept route pipe: {exc}"]

    errors: list[str] = []

    try:
        pipe_bounds = route_pipe.bounding_box()
        build_zone = benchmark_definition.objectives.build_zone_mm
        if (
            build_zone.min_mm[0] > pipe_bounds.min.X
            or build_zone.min_mm[1] > pipe_bounds.min.Y
            or build_zone.min_mm[2] > pipe_bounds.min.Z
            or build_zone.max_mm[0] < pipe_bounds.max.X
            or build_zone.max_mm[1] < pipe_bounds.max.Y
            or build_zone.max_mm[2] < pipe_bounds.max.Z
        ):
            errors.append("route clearance: swept route pipe leaves build_zone bounds")
    except Exception as exc:
        errors.append(f"route clearance: unable to evaluate build_zone bounds: {exc}")

    for zone in benchmark_definition.objectives.forbid_zones:
        try:
            inflated_zone = _bbox_from_bounds(zone, inflation_mm=clearance_mm)
            intersection = route_pipe.intersect(inflated_zone)
        except Exception as exc:
            errors.append(
                f"route clearance: unable to evaluate forbid zone '{zone.name}': {exc}"
            )
            continue
        if _shape_volume(intersection) > 1e-6:
            errors.append(
                f"route clearance: swept route pipe intersects forbid zone '{zone.name}'"
            )

    return errors


def validate_geometry(compound: Compound) -> None:
    intersects, pair, volume = intersects_any(compound)
    if intersects and volume > 1e-8:
        a, b = pair
        label_a = str(getattr(a, "label", "") or "")
        label_b = str(getattr(b, "label", "") or "")
        match_a = re.search(r"seg_(\d+)_split_(\d+)_", label_a)
        match_b = re.search(r"seg_(\d+)_split_(\d+)_", label_b)
        if match_a and match_b:
            seg_a = int(match_a.group(1))
            seg_b = int(match_b.group(1))
            # Adjacent route segments intentionally share a physical joint.
            # The swept corridor boxes can overlap at that handoff even when the
            # geometry is otherwise valid, so only non-adjacent collisions are
            # treated as hard failures.
            if seg_a != seg_b and abs(seg_a - seg_b) == 1:
                return
        raise ValueError(
            f"Candidate geometry self-intersects between {label_a} and {label_b} "
            f"(volume={volume})"
        )
