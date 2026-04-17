"""Helper utilities for tube-guided synthetic corpus generation."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
from build123d import (
    Align,
    Box,
    BuildLine,
    BuildPart,
    BuildSketch,
    Circle,
    Compound,
    Location,
    Plane,
    Polyline,
    sweep,
)

from shared.models.schemas import BenchmarkDefinition, BoundingBox


def _as_xyz(point: Any) -> tuple[float, float, float]:
    if hasattr(point, "pos_mm"):
        point = getattr(point, "pos_mm")
    return tuple(float(value) for value in point)


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
    route_points_xyz = [_as_xyz(point) for point in route_points]
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
            pipe_bounds.min.X < build_zone.min_mm[0]
            or pipe_bounds.min.Y < build_zone.min_mm[1]
            or pipe_bounds.min.Z < build_zone.min_mm[2]
            or pipe_bounds.max.X > build_zone.max_mm[0]
            or pipe_bounds.max.Y > build_zone.max_mm[1]
            or pipe_bounds.max.Z > build_zone.max_mm[2]
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
