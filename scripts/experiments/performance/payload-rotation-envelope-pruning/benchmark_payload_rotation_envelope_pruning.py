#!/usr/bin/env python3
"""Benchmark naive rotation-grid search versus adaptive broad-phase pruning.

The experiment is intentionally small and inspectable:

1. build or load a payload and fixture,
2. compare a naive uniform grid of orientations against an adaptive search,
3. record raw rows plus scenario summaries, and
4. write JSON metadata that explains the hypothesis and the observed gain.

The adaptive search is the same idea used in the throwaway visualizer, but this
script focuses on performance metadata instead of previews.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build123d import (
    Box,
    BuildPart,
    Color,
    Compound,
    Cylinder,
    Location,
    import_step,
)

from worker_heavy.workbenches.analysis_utils import part_to_trimesh

RESULT_PREFIX = "__EXPERIMENT_RESULT__="
DEFAULT_WINDOW_DEG = (15.0, 15.0, 15.0)
DEFAULT_ROTATION_DEG = (90.0, 90.0, 90.0)
DEFAULT_NAIVE_STEP_DEG = 5.0
DEFAULT_LEAF_STEP_DEG = 5.0
DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_CELLS = 24
DEFAULT_MAX_EXACT_CHECKS = 8

PAYLOAD_COLOR = Color(0.18, 0.52, 0.95, 0.55)
FIXTURE_COLOR = Color(1.0, 0.62, 0.20, 0.45)


@dataclass(frozen=True)
class ShapeReport:
    source: str
    label: str
    solid_count: int
    volume_mm3: float
    bbox_min_mm: list[float]
    bbox_max_mm: list[float]
    bbox_size_mm: list[float]


@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    description: str
    payload_rotation_deg: tuple[float, float, float]
    payload_translation_mm: tuple[float, float, float]
    rotation_window_deg: tuple[float, float, float]


@dataclass(frozen=True)
class AdaptiveCellTrace:
    cell_id: int
    depth: int
    min_deg: list[float]
    max_deg: list[float]
    center_deg: list[float]
    span_deg: list[float]
    rotation_pad_mm: float
    broad_phase_bbox_min_mm: list[float]
    broad_phase_bbox_max_mm: list[float]
    fixture_bbox_min_mm: list[float]
    fixture_bbox_max_mm: list[float]
    split_axis: int | None
    status: str
    exact_checked: bool
    exact_hit: bool | None
    note: str | None


@dataclass(frozen=True)
class ModeMeasurement:
    mode: str
    scenario: str
    repetition: int
    elapsed_sec: float
    exact_checks: int
    hit_found: bool
    first_hit_rotation_deg: list[float] | None
    first_hit_exact_volume_mm3: float | None
    samples_examined: int | None = None
    cells_visited: int | None = None
    broad_phase_rejected: int | None = None
    subdivisions: int | None = None
    budget_exhausted: bool | None = None
    first_hit_note: str | None = None


@dataclass(frozen=True)
class ScenarioSummary:
    scenario: str
    description: str
    setup_sec: float
    payload: ShapeReport
    fixture: ShapeReport
    config: dict[str, Any]
    naive: dict[str, Any]
    adaptive: dict[str, Any]
    speedups: dict[str, Any]
    adaptive_trace: list[AdaptiveCellTrace]


def _vec3(values: Sequence[float | str]) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError("expected exactly 3 values")
    return (float(values[0]), float(values[1]), float(values[2]))


def _format_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _bbox_numbers(shape) -> tuple[list[float], list[float], list[float]]:
    bbox = shape.bounding_box()
    bbox_min = [
        round(float(bbox.min.X), 6),
        round(float(bbox.min.Y), 6),
        round(float(bbox.min.Z), 6),
    ]
    bbox_max = [
        round(float(bbox.max.X), 6),
        round(float(bbox.max.Y), 6),
        round(float(bbox.max.Z), 6),
    ]
    bbox_size = [
        round(bbox_max[0] - bbox_min[0], 6),
        round(bbox_max[1] - bbox_min[1], 6),
        round(bbox_max[2] - bbox_min[2], 6),
    ]
    return bbox_min, bbox_max, bbox_size


def _shape_report(shape, *, source: str) -> ShapeReport:
    solid_count = len(list(shape.solids())) if hasattr(shape, "solids") else 0
    bbox_min, bbox_max, bbox_size = _bbox_numbers(shape)
    return ShapeReport(
        source=source,
        label=str(getattr(shape, "label", "")),
        solid_count=solid_count,
        volume_mm3=round(float(getattr(shape, "volume", 0.0)), 6),
        bbox_min_mm=bbox_min,
        bbox_max_mm=bbox_max,
        bbox_size_mm=bbox_size,
    )


def _center_shape(shape):
    bbox = shape.bounding_box()
    center_x = (float(bbox.min.X) + float(bbox.max.X)) / 2.0
    center_y = (float(bbox.min.Y) + float(bbox.max.Y)) / 2.0
    center_z = (float(bbox.min.Z) + float(bbox.max.Z)) / 2.0
    return shape.moved(Location((-center_x, -center_y, -center_z)))


def _apply_pose(
    shape,
    *,
    rotation_deg: Sequence[float],
    translation_mm: Sequence[float],
):
    return shape.moved(
        Location(
            tuple(float(v) for v in translation_mm),
            tuple(float(v) for v in rotation_deg),
        )
    )


def _assign_color(shape, color: Color, label: str):
    shape.color = color
    shape.label = label
    return shape


def _load_step_or_demo(path: Path | None, *, role: str):
    if path is None:
        return None
    if path.suffix.lower() not in {".step", ".stp"}:
        raise ValueError(f"{role} must be a STEP file: {path}")
    if not path.exists():
        raise FileNotFoundError(f"{role} STEP file does not exist: {path}")
    shape = import_step(path)
    shape.label = path.stem
    return shape


def build_demo_payload():
    with BuildPart() as builder:
        Box(120, 52, 28)
        Box(34, 84, 18).moved(Location((35, 0, 8)))
        Box(18, 30, 44).moved(Location((-18, 16, 8)))
        Cylinder(10, 62, rotation=(0, 90, 0)).moved(Location((-30, -10, 0)))

    payload = builder.part
    return _assign_color(payload, PAYLOAD_COLOR, "demo_payload")


def build_demo_fixture():
    with BuildPart() as builder:
        Box(92, 70, 36)
        Box(24, 46, 16).moved(Location((18, -18, 10)))
        Cylinder(12, 50, rotation=(90, 0, 0)).moved(Location((22, 16, 0)))

    fixture = builder.part
    return _assign_color(fixture, FIXTURE_COLOR, "demo_fixture")


def _boolean_intersection(shape_a, shape_b) -> tuple[object | None, float, bool]:
    result = shape_a.intersect(shape_b)
    if result is None:
        return None, 0.0, False

    candidates = list(result)
    if not candidates:
        return None, 0.0, False

    volume = sum(float(candidate.volume) for candidate in candidates)
    if volume <= 1e-9:
        return None, volume, False

    if len(candidates) == 1:
        intersection = candidates[0]
    else:
        intersection = Compound(children=candidates, label="intersection")
    return intersection, volume, True


def _max_radius_mm(shape) -> float:
    # The trimesh export/import cost is paid once per scenario during setup.
    # The search loop reuses the derived radius and never reinitializes trimesh.
    mesh = part_to_trimesh(shape)
    max_radius = 0.0
    for vertex in mesh.vertices:
        x = float(vertex[0])
        y = float(vertex[1])
        z = float(vertex[2])
        radius = math.sqrt(x * x + y * y + z * z)
        if radius > max_radius:
            max_radius = radius
    return max_radius


def _rotation_padding_mm(max_radius_mm: float, span_deg: Sequence[float]) -> float:
    if max_radius_mm <= 0:
        return 0.0
    half_spans_rad = [math.radians(float(span) / 2.0) for span in span_deg]
    angular_radius = min(math.pi, sum(half_spans_rad))
    if angular_radius <= 0:
        return 0.0
    return 2.0 * max_radius_mm * math.sin(angular_radius / 2.0)


def _bbox_intersects(
    min_a: Sequence[float],
    max_a: Sequence[float],
    min_b: Sequence[float],
    max_b: Sequence[float],
    *,
    eps: float = 1e-9,
) -> bool:
    return not (
        max_a[0] < min_b[0] - eps
        or min_a[0] > max_b[0] + eps
        or max_a[1] < min_b[1] - eps
        or min_a[1] > max_b[1] + eps
        or max_a[2] < min_b[2] - eps
        or min_a[2] > max_b[2] + eps
    )


def _rotation_cell_center(
    cell_min_deg: Sequence[float], cell_max_deg: Sequence[float]
) -> tuple[float, float, float]:
    return (
        (cell_min_deg[0] + cell_max_deg[0]) / 2.0,
        (cell_min_deg[1] + cell_max_deg[1]) / 2.0,
        (cell_min_deg[2] + cell_max_deg[2]) / 2.0,
    )


def _rotation_cell_span(
    cell_min_deg: Sequence[float], cell_max_deg: Sequence[float]
) -> tuple[float, float, float]:
    return (
        cell_max_deg[0] - cell_min_deg[0],
        cell_max_deg[1] - cell_min_deg[1],
        cell_max_deg[2] - cell_min_deg[2],
    )


def _widest_axis(span_deg: Sequence[float]) -> int:
    widest = 0
    widest_size = float(span_deg[0])
    for idx in range(1, 3):
        if float(span_deg[idx]) > widest_size:
            widest = idx
            widest_size = float(span_deg[idx])
    return widest


def _inclusive_axis_samples(
    center_deg: float, half_window_deg: float, step_deg: float
) -> list[float]:
    start = center_deg - half_window_deg
    stop = center_deg + half_window_deg
    if step_deg <= 0:
        raise ValueError("step_deg must be positive")

    count = int(math.floor(((stop - start) / step_deg) + 1e-9)) + 1
    values = [start + (idx * step_deg) for idx in range(max(1, count))]
    if not values:
        values = [center_deg]
    if abs(values[-1] - stop) > 1e-9:
        values.append(stop)
    return [round(float(v), 6) for v in values]


def _naive_grid_search(
    payload,
    fixture,
    *,
    center_rotation_deg: Sequence[float],
    translation_mm: Sequence[float],
    window_deg: Sequence[float],
    step_deg: float,
) -> tuple[ModeMeasurement, list[dict[str, Any]]]:
    xs = _inclusive_axis_samples(
        float(center_rotation_deg[0]), float(window_deg[0]), step_deg
    )
    ys = _inclusive_axis_samples(
        float(center_rotation_deg[1]), float(window_deg[1]), step_deg
    )
    zs = _inclusive_axis_samples(
        float(center_rotation_deg[2]), float(window_deg[2]), step_deg
    )
    total_cells = len(xs) * len(ys) * len(zs)

    trace: list[dict[str, Any]] = []
    exact_checks = 0
    samples_examined = 0
    first_hit_rotation_deg: list[float] | None = None
    first_hit_exact_volume_mm3: float | None = None
    hit_found = False
    start = time.perf_counter()

    for rx in xs:
        if hit_found:
            break
        for ry in ys:
            if hit_found:
                break
            for rz in zs:
                samples_examined += 1
                exact_checks += 1
                posed_payload = _apply_pose(
                    payload,
                    rotation_deg=(rx, ry, rz),
                    translation_mm=translation_mm,
                )
                intersection, exact_volume, exact_hit = _boolean_intersection(
                    posed_payload,
                    fixture,
                )
                row = {
                    "rotation_deg": [rx, ry, rz],
                    "exact_hit": exact_hit,
                    "exact_volume_mm3": round(float(exact_volume), 6),
                }
                trace.append(row)
                if exact_hit:
                    hit_found = True
                    first_hit_rotation_deg = [rx, ry, rz]
                    first_hit_exact_volume_mm3 = round(float(exact_volume), 6)
                    break

    elapsed_sec = time.perf_counter() - start
    measurement = ModeMeasurement(
        mode="naive_grid",
        scenario="",
        repetition=0,
        elapsed_sec=elapsed_sec,
        exact_checks=exact_checks,
        hit_found=hit_found,
        first_hit_rotation_deg=first_hit_rotation_deg,
        first_hit_exact_volume_mm3=first_hit_exact_volume_mm3,
        samples_examined=samples_examined,
    )
    return measurement, trace[: min(len(trace), total_cells)]


def _adaptive_search(
    payload,
    fixture,
    *,
    center_rotation_deg: Sequence[float],
    translation_mm: Sequence[float],
    window_deg: Sequence[float],
    leaf_step_deg: float,
    max_depth: int,
    max_cells: int,
    max_exact_checks: int,
    payload_max_radius_mm: float,
    fixture_bbox_min: Sequence[float],
    fixture_bbox_max: Sequence[float],
) -> tuple[ModeMeasurement, list[AdaptiveCellTrace]]:
    center_rotation = tuple(float(v) for v in center_rotation_deg)
    window = tuple(max(0.0, float(v)) for v in window_deg)
    fixture_bbox_min = [float(v) for v in fixture_bbox_min]
    fixture_bbox_max = [float(v) for v in fixture_bbox_max]

    root_min = (
        center_rotation[0] - window[0],
        center_rotation[1] - window[1],
        center_rotation[2] - window[2],
    )
    root_max = (
        center_rotation[0] + window[0],
        center_rotation[1] + window[1],
        center_rotation[2] + window[2],
    )

    queue: list[
        tuple[float, int, int, tuple[float, float, float], tuple[float, float, float]]
    ] = [
        (
            -(
                (root_max[0] - root_min[0])
                * (root_max[1] - root_min[1])
                * (root_max[2] - root_min[2])
            ),
            1,
            0,
            root_min,
            root_max,
        )
    ]
    trace: list[AdaptiveCellTrace] = []
    exact_checks = 0
    cells_visited = 0
    broad_phase_rejected = 0
    subdivisions = 0
    budget_exhausted = False
    hit_found = False
    first_hit_rotation_deg: list[float] | None = None
    first_hit_exact_volume_mm3: float | None = None
    first_hit_note: str | None = None
    next_cell_id = 2

    start = time.perf_counter()

    while queue:
        if cells_visited >= max_cells:
            budget_exhausted = True
            break

        _, cell_id, depth, cell_min_deg, cell_max_deg = heapq.heappop(queue)
        cells_visited += 1
        span = _rotation_cell_span(cell_min_deg, cell_max_deg)
        center = _rotation_cell_center(cell_min_deg, cell_max_deg)
        rotation_pad_mm = _rotation_padding_mm(payload_max_radius_mm, span)

        posed_payload = _apply_pose(
            payload,
            rotation_deg=center,
            translation_mm=translation_mm,
        )
        center_bbox_min, center_bbox_max, _ = _bbox_numbers(posed_payload)
        broad_min = [value - rotation_pad_mm for value in center_bbox_min]
        broad_max = [value + rotation_pad_mm for value in center_bbox_max]

        if not _bbox_intersects(
            broad_min, broad_max, fixture_bbox_min, fixture_bbox_max
        ):
            broad_phase_rejected += 1
            trace.append(
                AdaptiveCellTrace(
                    cell_id=cell_id,
                    depth=depth,
                    min_deg=[round(float(v), 6) for v in cell_min_deg],
                    max_deg=[round(float(v), 6) for v in cell_max_deg],
                    center_deg=[round(float(v), 6) for v in center],
                    span_deg=[round(float(v), 6) for v in span],
                    rotation_pad_mm=round(float(rotation_pad_mm), 6),
                    broad_phase_bbox_min_mm=[round(float(v), 6) for v in broad_min],
                    broad_phase_bbox_max_mm=[round(float(v), 6) for v in broad_max],
                    fixture_bbox_min_mm=list(fixture_bbox_min),
                    fixture_bbox_max_mm=list(fixture_bbox_max),
                    split_axis=None,
                    status="broad_phase_rejected",
                    exact_checked=False,
                    exact_hit=None,
                    note="expanded cell envelope misses the fixture bounding box",
                )
            )
            continue

        is_leaf = depth >= max_depth or max(span) <= leaf_step_deg
        if is_leaf:
            if exact_checks >= max_exact_checks:
                budget_exhausted = True
                trace.append(
                    AdaptiveCellTrace(
                        cell_id=cell_id,
                        depth=depth,
                        min_deg=[round(float(v), 6) for v in cell_min_deg],
                        max_deg=[round(float(v), 6) for v in cell_max_deg],
                        center_deg=[round(float(v), 6) for v in center],
                        span_deg=[round(float(v), 6) for v in span],
                        rotation_pad_mm=round(float(rotation_pad_mm), 6),
                        broad_phase_bbox_min_mm=[round(float(v), 6) for v in broad_min],
                        broad_phase_bbox_max_mm=[round(float(v), 6) for v in broad_max],
                        fixture_bbox_min_mm=list(fixture_bbox_min),
                        fixture_bbox_max_mm=list(fixture_bbox_max),
                        split_axis=None,
                        status="budget_exhausted",
                        exact_checked=False,
                        exact_hit=None,
                        note="exact-check budget exhausted before sampling this leaf cell",
                    )
                )
                break

            exact_checks += 1
            intersection, exact_volume, exact_hit = _boolean_intersection(
                posed_payload,
                fixture,
            )
            if exact_hit:
                hit_found = True
                first_hit_rotation_deg = [round(float(v), 6) for v in center]
                first_hit_exact_volume_mm3 = round(float(exact_volume), 6)
                first_hit_note = "first exact collision discovered in the search window"

            trace.append(
                AdaptiveCellTrace(
                    cell_id=cell_id,
                    depth=depth,
                    min_deg=[round(float(v), 6) for v in cell_min_deg],
                    max_deg=[round(float(v), 6) for v in cell_max_deg],
                    center_deg=[round(float(v), 6) for v in center],
                    span_deg=[round(float(v), 6) for v in span],
                    rotation_pad_mm=round(float(rotation_pad_mm), 6),
                    broad_phase_bbox_min_mm=[round(float(v), 6) for v in broad_min],
                    broad_phase_bbox_max_mm=[round(float(v), 6) for v in broad_max],
                    fixture_bbox_min_mm=list(fixture_bbox_min),
                    fixture_bbox_max_mm=list(fixture_bbox_max),
                    split_axis=None,
                    status="sample_hit" if exact_hit else "sample_clear",
                    exact_checked=True,
                    exact_hit=exact_hit,
                    note=(
                        "first exact collision discovered in the search window"
                        if exact_hit
                        else "sampled exact center pose for this leaf cell"
                    ),
                )
            )
            if exact_hit:
                break
            continue

        split_axis = _widest_axis(span)
        midpoint = (cell_min_deg[split_axis] + cell_max_deg[split_axis]) / 2.0
        left_min = list(cell_min_deg)
        left_max = list(cell_max_deg)
        left_max[split_axis] = midpoint
        right_min = list(cell_min_deg)
        right_max = list(cell_max_deg)
        right_min[split_axis] = midpoint

        subdivisions += 1
        next_depth = depth + 1
        left = (left_min[0], left_min[1], left_min[2])
        left_max_t = (left_max[0], left_max[1], left_max[2])
        right = (right_min[0], right_min[1], right_min[2])
        right_max_t = (right_max[0], right_max[1], right_max[2])
        left_priority = -(
            (left_max_t[0] - left[0])
            * (left_max_t[1] - left[1])
            * (left_max_t[2] - left[2])
        )
        right_priority = -(
            (right_max_t[0] - right[0])
            * (right_max_t[1] - right[1])
            * (right_max_t[2] - right[2])
        )
        heapq.heappush(
            queue, (left_priority, next_cell_id, next_depth, left, left_max_t)
        )
        heapq.heappush(
            queue,
            (right_priority, next_cell_id + 1, next_depth, right, right_max_t),
        )
        next_cell_id += 2
        trace.append(
            AdaptiveCellTrace(
                cell_id=cell_id,
                depth=depth,
                min_deg=[round(float(v), 6) for v in cell_min_deg],
                max_deg=[round(float(v), 6) for v in cell_max_deg],
                center_deg=[round(float(v), 6) for v in center],
                span_deg=[round(float(v), 6) for v in span],
                rotation_pad_mm=round(float(rotation_pad_mm), 6),
                broad_phase_bbox_min_mm=[round(float(v), 6) for v in broad_min],
                broad_phase_bbox_max_mm=[round(float(v), 6) for v in broad_max],
                fixture_bbox_min_mm=list(fixture_bbox_min),
                fixture_bbox_max_mm=list(fixture_bbox_max),
                split_axis=split_axis,
                status="subdivided",
                exact_checked=False,
                exact_hit=None,
                note=f"split the widest rotation axis {split_axis}",
            )
        )

        if hit_found:
            break

    elapsed_sec = time.perf_counter() - start
    measurement = ModeMeasurement(
        mode="adaptive_pruning",
        scenario="",
        repetition=0,
        elapsed_sec=elapsed_sec,
        exact_checks=exact_checks,
        hit_found=hit_found,
        first_hit_rotation_deg=first_hit_rotation_deg,
        first_hit_exact_volume_mm3=first_hit_exact_volume_mm3,
        cells_visited=cells_visited,
        broad_phase_rejected=broad_phase_rejected,
        subdivisions=subdivisions,
        budget_exhausted=budget_exhausted,
        first_hit_note=first_hit_note,
    )
    return measurement, trace


SCENARIOS: dict[str, ScenarioConfig] = {
    "demo_immediate_hit": ScenarioConfig(
        name="demo_immediate_hit",
        description=(
            "Payload and fixture overlap at the nominal pose, so both modes find "
            "a collision immediately."
        ),
        payload_rotation_deg=DEFAULT_ROTATION_DEG,
        payload_translation_mm=(0.0, 0.0, 0.0),
        rotation_window_deg=DEFAULT_WINDOW_DEG,
    ),
    "demo_recursive_prune": ScenarioConfig(
        name="demo_recursive_prune",
        description=(
            "Payload is translated so the naive grid still works hard, while the "
            "adaptive search needs recursive subdivision to prove the envelope."
        ),
        payload_rotation_deg=DEFAULT_ROTATION_DEG,
        payload_translation_mm=(100.0, 0.0, 0.0),
        rotation_window_deg=DEFAULT_WINDOW_DEG,
    ),
    "demo_far_miss": ScenarioConfig(
        name="demo_far_miss",
        description=(
            "Payload is translated far enough away that the adaptive search can "
            "reject the whole rotation cell with broad-phase bounds."
        ),
        payload_rotation_deg=DEFAULT_ROTATION_DEG,
        payload_translation_mm=(180.0, 0.0, 0.0),
        rotation_window_deg=DEFAULT_WINDOW_DEG,
    ),
}


def _scenario_order(selected: str) -> list[ScenarioConfig]:
    if selected == "all":
        return list(SCENARIOS.values())
    return [SCENARIOS[selected]]


def _configure_loaded_payload_fixture(
    *,
    payload_step: Path | None,
    fixture_step: Path | None,
    center_payload: bool,
) -> tuple[object, object, str, str]:
    payload = _load_step_or_demo(payload_step, role="payload")
    if payload is None:
        payload = build_demo_payload()

    fixture = _load_step_or_demo(fixture_step, role="fixture")
    if fixture is None:
        fixture = build_demo_fixture()

    if center_payload:
        payload = _center_shape(payload)

    payload = _assign_color(payload, PAYLOAD_COLOR, "payload")
    fixture = _assign_color(fixture, FIXTURE_COLOR, "fixture")

    payload_source = _format_path(payload_step) if payload_step else "demo"
    fixture_source = _format_path(fixture_step) if fixture_step else "demo"
    return payload, fixture, payload_source, fixture_source


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"by_scenario": {}}
    scenarios = sorted({row["scenario"] for row in rows})

    for scenario in scenarios:
        scenario_rows = [row for row in rows if row["scenario"] == scenario]
        by_mode: dict[str, Any] = {}
        for mode in sorted({row["mode"] for row in scenario_rows}):
            mode_rows = [row for row in scenario_rows if row["mode"] == mode]
            elapsed = [float(row["elapsed_sec"]) for row in mode_rows]
            exact_checks = [float(row["exact_checks"]) for row in mode_rows]
            by_mode[mode] = {
                "runs": len(mode_rows),
                "mean_elapsed_sec": statistics.mean(elapsed),
                "median_elapsed_sec": statistics.median(elapsed),
                "min_elapsed_sec": min(elapsed),
                "max_elapsed_sec": max(elapsed),
                "mean_exact_checks": statistics.mean(exact_checks),
                "median_exact_checks": statistics.median(exact_checks),
                "min_exact_checks": min(exact_checks),
                "max_exact_checks": max(exact_checks),
                "runs_hit_found": sum(1 for row in mode_rows if row["hit_found"]),
                "runs_budget_exhausted": sum(
                    1 for row in mode_rows if row.get("budget_exhausted")
                ),
            }
            if mode == "adaptive_pruning":
                by_mode[mode]["mean_broad_phase_rejected"] = statistics.mean(
                    [float(row["broad_phase_rejected"]) for row in mode_rows]
                )
                by_mode[mode]["mean_subdivisions"] = statistics.mean(
                    [float(row["subdivisions"]) for row in mode_rows]
                )
                by_mode[mode]["mean_cells_visited"] = statistics.mean(
                    [float(row["cells_visited"]) for row in mode_rows]
                )
            if mode == "naive_grid":
                by_mode[mode]["mean_samples_examined"] = statistics.mean(
                    [float(row["samples_examined"]) for row in mode_rows]
                )

        scenario_naive = by_mode.get("naive_grid")
        scenario_adaptive = by_mode.get("adaptive_pruning")
        speedups: dict[str, Any] = {}
        if scenario_naive and scenario_adaptive:
            naive_elapsed = float(scenario_naive["mean_elapsed_sec"])
            adaptive_elapsed = float(scenario_adaptive["mean_elapsed_sec"])
            naive_checks = float(scenario_naive["mean_exact_checks"])
            adaptive_checks = float(scenario_adaptive["mean_exact_checks"])
            speedups["elapsed_speedup_over_naive"] = (
                naive_elapsed / adaptive_elapsed if adaptive_elapsed > 0 else None
            )
            speedups["elapsed_savings_pct"] = (
                100.0 * (naive_elapsed - adaptive_elapsed) / naive_elapsed
                if naive_elapsed > 0
                else None
            )
            speedups["exact_check_reduction_pct"] = (
                100.0 * (naive_checks - adaptive_checks) / naive_checks
                if naive_checks > 0
                else None
            )
            speedups["exact_check_ratio_naive_over_adaptive"] = (
                naive_checks / adaptive_checks if adaptive_checks > 0 else None
            )
        summary["by_scenario"][scenario] = {
            "modes": by_mode,
            "speedups": speedups,
        }

    naive_means = [
        float(
            summary["by_scenario"][scenario]["modes"]["naive_grid"]["mean_elapsed_sec"]
        )
        for scenario in scenarios
        if "naive_grid" in summary["by_scenario"][scenario]["modes"]
    ]
    adaptive_means = [
        float(
            summary["by_scenario"][scenario]["modes"]["adaptive_pruning"][
                "mean_elapsed_sec"
            ]
        )
        for scenario in scenarios
        if "adaptive_pruning" in summary["by_scenario"][scenario]["modes"]
    ]
    if naive_means and adaptive_means:
        summary["overall"] = {
            "mean_naive_elapsed_sec": statistics.mean(naive_means),
            "mean_adaptive_elapsed_sec": statistics.mean(adaptive_means),
            "elapsed_speedup_over_naive": statistics.mean(naive_means)
            / statistics.mean(adaptive_means)
            if statistics.mean(adaptive_means) > 0
            else None,
            "elapsed_savings_pct": 100.0
            * (statistics.mean(naive_means) - statistics.mean(adaptive_means))
            / statistics.mean(naive_means)
            if statistics.mean(naive_means) > 0
            else None,
        }
    return summary


def _print_human_summary(report: dict[str, Any]) -> None:
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print()
    for scenario_name, scenario_summary in report["summary"]["by_scenario"].items():
        speedups = scenario_summary.get("speedups", {})
        elapsed_speedup = speedups.get("elapsed_speedup_over_naive")
        if elapsed_speedup is not None:
            print(
                f"{scenario_name}: elapsed speedup over naive = {elapsed_speedup:.3f}x"
            )
        exact_pct = speedups.get("exact_check_reduction_pct")
        if exact_pct is not None:
            print(f"{scenario_name}: exact-check reduction vs naive = {exact_pct:.1f}%")


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    scenarios = _scenario_order(args.scenario)
    rows: list[dict[str, Any]] = []
    scenario_details: list[dict[str, Any]] = []

    for scenario in scenarios:
        setup_t0 = time.perf_counter()
        payload, fixture, payload_source, fixture_source = (
            _configure_loaded_payload_fixture(
                payload_step=args.payload_step,
                fixture_step=args.fixture_step,
                center_payload=not args.no_center_payload,
            )
        )
        payload_max_radius_mm = _max_radius_mm(payload)
        fixture_bbox_min, fixture_bbox_max, _ = _bbox_numbers(fixture)
        shared_setup_sec = time.perf_counter() - setup_t0

        payload_report = _shape_report(payload, source=payload_source)
        fixture_report = _shape_report(fixture, source=fixture_source)

        config_dict = {
            "payload_rotation_deg": list(scenario.payload_rotation_deg),
            "payload_translation_mm": list(scenario.payload_translation_mm),
            "rotation_window_deg": list(scenario.rotation_window_deg),
            "naive_step_deg": float(args.naive_step_deg),
            "adaptive_leaf_step_deg": float(args.adaptive_leaf_step_deg),
            "adaptive_max_depth": int(args.adaptive_max_depth),
            "adaptive_max_cells": int(args.adaptive_max_cells),
            "adaptive_max_exact_checks": int(args.adaptive_max_exact_checks),
            "payload_max_radius_mm": round(float(payload_max_radius_mm), 6),
            "fixture_bbox_min_mm": [round(float(v), 6) for v in fixture_bbox_min],
            "fixture_bbox_max_mm": [round(float(v), 6) for v in fixture_bbox_max],
        }

        adaptive_trace: list[AdaptiveCellTrace] = []
        naive_rows: list[ModeMeasurement] = []
        adaptive_rows: list[ModeMeasurement] = []

        for repetition in range(1, args.repetitions + 1):
            mode_order = (
                ("naive", "adaptive") if repetition % 2 == 1 else ("adaptive", "naive")
            )
            for mode in mode_order:
                if mode == "naive":
                    measurement, _ = _naive_grid_search(
                        payload,
                        fixture,
                        center_rotation_deg=scenario.payload_rotation_deg,
                        translation_mm=scenario.payload_translation_mm,
                        window_deg=scenario.rotation_window_deg,
                        step_deg=args.naive_step_deg,
                    )
                    measurement = ModeMeasurement(
                        **{
                            **asdict(measurement),
                            "scenario": scenario.name,
                            "repetition": repetition,
                        }
                    )
                    naive_rows.append(measurement)
                    rows.append(
                        {
                            "scenario": scenario.name,
                            "mode": measurement.mode,
                            "repetition": repetition,
                            "elapsed_sec": measurement.elapsed_sec,
                            "exact_checks": measurement.exact_checks,
                            "hit_found": measurement.hit_found,
                            "samples_examined": measurement.samples_examined,
                            "first_hit_rotation_deg": measurement.first_hit_rotation_deg,
                            "first_hit_exact_volume_mm3": measurement.first_hit_exact_volume_mm3,
                            "budget_exhausted": measurement.budget_exhausted,
                        }
                    )
                else:
                    measurement, trace = _adaptive_search(
                        payload,
                        fixture,
                        center_rotation_deg=scenario.payload_rotation_deg,
                        translation_mm=scenario.payload_translation_mm,
                        window_deg=scenario.rotation_window_deg,
                        leaf_step_deg=args.adaptive_leaf_step_deg,
                        max_depth=args.adaptive_max_depth,
                        max_cells=args.adaptive_max_cells,
                        max_exact_checks=args.adaptive_max_exact_checks,
                        payload_max_radius_mm=payload_max_radius_mm,
                        fixture_bbox_min=fixture_bbox_min,
                        fixture_bbox_max=fixture_bbox_max,
                    )
                    measurement = ModeMeasurement(
                        **{
                            **asdict(measurement),
                            "scenario": scenario.name,
                            "repetition": repetition,
                        }
                    )
                    adaptive_rows.append(measurement)
                    rows.append(
                        {
                            "scenario": scenario.name,
                            "mode": measurement.mode,
                            "repetition": repetition,
                            "elapsed_sec": measurement.elapsed_sec,
                            "exact_checks": measurement.exact_checks,
                            "hit_found": measurement.hit_found,
                            "cells_visited": measurement.cells_visited,
                            "broad_phase_rejected": measurement.broad_phase_rejected,
                            "subdivisions": measurement.subdivisions,
                            "budget_exhausted": measurement.budget_exhausted,
                            "first_hit_rotation_deg": measurement.first_hit_rotation_deg,
                            "first_hit_exact_volume_mm3": measurement.first_hit_exact_volume_mm3,
                        }
                    )
                    if not adaptive_trace:
                        adaptive_trace = trace

        def _mode_summary(
            mode_rows: list[ModeMeasurement], *, mode: str
        ) -> dict[str, Any]:
            elapsed = [float(row.elapsed_sec) for row in mode_rows]
            exact_checks = [float(row.exact_checks) for row in mode_rows]
            summary: dict[str, Any] = {
                "mode": mode,
                "runs": len(mode_rows),
                "mean_elapsed_sec": statistics.mean(elapsed),
                "median_elapsed_sec": statistics.median(elapsed),
                "min_elapsed_sec": min(elapsed),
                "max_elapsed_sec": max(elapsed),
                "mean_exact_checks": statistics.mean(exact_checks),
                "median_exact_checks": statistics.median(exact_checks),
                "min_exact_checks": min(exact_checks),
                "max_exact_checks": max(exact_checks),
                "runs_hit_found": sum(1 for row in mode_rows if row.hit_found),
                "runs_budget_exhausted": sum(
                    1 for row in mode_rows if bool(row.budget_exhausted)
                ),
            }
            if mode == "naive_grid":
                summary["mean_samples_examined"] = statistics.mean(
                    [float(row.samples_examined or 0) for row in mode_rows]
                )
            else:
                summary["mean_cells_visited"] = statistics.mean(
                    [float(row.cells_visited or 0) for row in mode_rows]
                )
                summary["mean_broad_phase_rejected"] = statistics.mean(
                    [float(row.broad_phase_rejected or 0) for row in mode_rows]
                )
                summary["mean_subdivisions"] = statistics.mean(
                    [float(row.subdivisions or 0) for row in mode_rows]
                )
            if any(row.first_hit_rotation_deg is not None for row in mode_rows):
                first_hit = next(
                    row for row in mode_rows if row.first_hit_rotation_deg is not None
                )
                summary["first_hit_rotation_deg"] = first_hit.first_hit_rotation_deg
                summary["first_hit_exact_volume_mm3"] = (
                    first_hit.first_hit_exact_volume_mm3
                )
            return summary

        naive_summary = _mode_summary(naive_rows, mode="naive_grid")
        adaptive_summary = _mode_summary(adaptive_rows, mode="adaptive_pruning")
        speedups = {
            "elapsed_speedup_over_naive": (
                float(naive_summary["mean_elapsed_sec"])
                / float(adaptive_summary["mean_elapsed_sec"])
                if float(adaptive_summary["mean_elapsed_sec"]) > 0
                else None
            ),
            "elapsed_savings_pct": (
                100.0
                * (
                    float(naive_summary["mean_elapsed_sec"])
                    - float(adaptive_summary["mean_elapsed_sec"])
                )
                / float(naive_summary["mean_elapsed_sec"])
                if float(naive_summary["mean_elapsed_sec"]) > 0
                else None
            ),
            "exact_check_reduction_pct": (
                100.0
                * (
                    float(naive_summary["mean_exact_checks"])
                    - float(adaptive_summary["mean_exact_checks"])
                )
                / float(naive_summary["mean_exact_checks"])
                if float(naive_summary["mean_exact_checks"]) > 0
                else None
            ),
            "exact_check_ratio_naive_over_adaptive": (
                float(naive_summary["mean_exact_checks"])
                / float(adaptive_summary["mean_exact_checks"])
                if float(adaptive_summary["mean_exact_checks"]) > 0
                else None
            ),
        }
        scenario_details.append(
            asdict(
                ScenarioSummary(
                    scenario=scenario.name,
                    description=scenario.description,
                    setup_sec=shared_setup_sec,
                    payload=payload_report,
                    fixture=fixture_report,
                    config=config_dict,
                    naive=naive_summary,
                    adaptive=adaptive_summary,
                    speedups=speedups,
                    adaptive_trace=adaptive_trace,
                )
            )
        )

    result = {
        "experiment": "payload_rotation_envelope_pruning",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "repo_root": str(ROOT),
        "metadata": {
            "hypothesis": {
                "statement": (
                    "An adaptive rotation-envelope search with conservative "
                    "broad-phase pruning and recursive subdivision should "
                    "reduce exact build123d intersection checks versus a naive "
                    "uniform grid over the same admissible rotation window."
                ),
                "baseline": (
                    "Uniform pitch/yaw/roll grid, exact intersection at every "
                    "sample, stop when the first collision is found or the grid "
                    "is exhausted."
                ),
                "candidate": (
                    "Widest-axis recursive subdivision with a bounding-box "
                    "broad phase, exact checks only at leaf cells, and hard "
                    "caps on cells, depth, and exact booleans."
                ),
                "what_to_watch": [
                    "elapsed_speedup_over_naive > 1.0 means the adaptive search is faster",
                    "exact_check_reduction_pct > 0 means the adaptive search uses fewer exact booleans",
                    "budget_exhausted = true means the proof failed closed before the search completed",
                ],
            },
            "search_contract": {
                "naive_step_deg": float(args.naive_step_deg),
                "adaptive_leaf_step_deg": float(args.adaptive_leaf_step_deg),
                "adaptive_max_depth": int(args.adaptive_max_depth),
                "adaptive_max_cells": int(args.adaptive_max_cells),
                "adaptive_max_exact_checks": int(args.adaptive_max_exact_checks),
                "window_deg": list(DEFAULT_WINDOW_DEG),
            },
            "geometry_cache_contract": {
                "payload_trimesh_loaded_once_per_scenario": True,
                "search_loop_reinitializes_trimesh": False,
                "search_loop_exports_or_imports_meshes": False,
                "search_loop_io_bound": False,
            },
        },
        "args": {
            "scenario": args.scenario,
            "repetitions": args.repetitions,
            "payload_step": _format_path(args.payload_step)
            if args.payload_step
            else "",
            "fixture_step": _format_path(args.fixture_step)
            if args.fixture_step
            else "",
            "naive_step_deg": float(args.naive_step_deg),
            "adaptive_leaf_step_deg": float(args.adaptive_leaf_step_deg),
            "adaptive_max_depth": int(args.adaptive_max_depth),
            "adaptive_max_cells": int(args.adaptive_max_cells),
            "adaptive_max_exact_checks": int(args.adaptive_max_exact_checks),
            "no_center_payload": bool(args.no_center_payload),
            "output_json": args.output_json,
        },
        "rows": rows,
        "scenarios": scenario_details,
        "summary": _summarize_rows(rows),
    }
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark a naive uniform orientation grid against an adaptive "
            "rotation-envelope search with conservative broad-phase pruning."
        )
    )
    parser.add_argument(
        "--scenario",
        choices=("all",) + tuple(SCENARIOS.keys()),
        default="all",
        help="Which synthetic scenario to run.",
    )
    parser.add_argument(
        "--payload-step",
        type=Path,
        help="Optional STEP file for the moving payload or feature.",
    )
    parser.add_argument(
        "--fixture-step",
        type=Path,
        help="Optional STEP file for the fixed obstacle or fixture.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="How many times to repeat each mode for timing summaries.",
    )
    parser.add_argument(
        "--naive-step-deg",
        type=float,
        default=DEFAULT_NAIVE_STEP_DEG,
        help="Angular step for the naive uniform grid.",
    )
    parser.add_argument(
        "--adaptive-leaf-step-deg",
        type=float,
        default=DEFAULT_LEAF_STEP_DEG,
        help="Smallest angular span that the adaptive search samples exactly.",
    )
    parser.add_argument(
        "--adaptive-max-depth",
        type=int,
        default=DEFAULT_MAX_DEPTH,
        help="Maximum subdivision depth for the adaptive search.",
    )
    parser.add_argument(
        "--adaptive-max-cells",
        type=int,
        default=DEFAULT_MAX_CELLS,
        help="Maximum adaptive cells to inspect before failing closed.",
    )
    parser.add_argument(
        "--adaptive-max-exact-checks",
        type=int,
        default=DEFAULT_MAX_EXACT_CHECKS,
        help="Maximum exact booleans the adaptive search may run.",
    )
    parser.add_argument(
        "--no-center-payload",
        action="store_true",
        help="Do not re-center the payload on its bounding-box center before applying the pose.",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional explicit output JSON path. Defaults to a timestamped file in this folder.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.repetitions < 1:
        raise ValueError("--repetitions must be at least 1")

    output_path = (
        Path(args.output_json).expanduser().resolve()
        if args.output_json.strip()
        else Path(__file__).resolve().parent
        / (f"results-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report = run_experiment(args)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _print_human_summary(report)
    print(f"\nWrote results to {output_path}")
    print(
        f"{RESULT_PREFIX}{json.dumps({'output_path': str(output_path)}, sort_keys=True)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
