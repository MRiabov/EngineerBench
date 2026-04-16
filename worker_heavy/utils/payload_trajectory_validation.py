from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import ceil, sqrt
from pathlib import Path
from typing import Any

import structlog
from build123d import Compound, Location

from shared.agents.config import PayloadTrajectoryClearanceBudget, load_agents_config
from shared.models.schemas import (
    AssemblyDefinition,
    BenchmarkDefinition,
    PayloadTrajectoryAnchor,
    PayloadTrajectoryDefinition,
)
from shared.script_contracts import BENCHMARK_SCRIPT_PATH, SOLUTION_SCRIPT_PATH
from worker_heavy.utils.validation import _shape_volume
from worker_heavy.workbenches.analysis_utils import part_to_trimesh

logger = structlog.get_logger(__name__)

ExactPoseCacheKey = tuple[float, float, float, float, float, float, bool, bool]


@dataclass(frozen=True)
class RotationCell:
    lower_deg: tuple[float, float, float]
    upper_deg: tuple[float, float, float]
    depth: int = 0

    def spans(self) -> tuple[float, float, float]:
        return tuple(self.upper_deg[i] - self.lower_deg[i] for i in range(3))

    def widest_axis(self) -> int:
        spans = self.spans()
        return max(range(3), key=lambda index: spans[index])

    def widest_span(self) -> float:
        return max(self.spans())

    def is_exact(self) -> bool:
        return all(abs(self.upper_deg[i] - self.lower_deg[i]) <= 1e-9 for i in range(3))

    def midpoint(self) -> tuple[float, float, float]:
        return tuple((self.lower_deg[i] + self.upper_deg[i]) / 2.0 for i in range(3))

    def split(self) -> tuple["RotationCell", "RotationCell"]:
        axis = self.widest_axis()
        lower = list(self.lower_deg)
        upper = list(self.upper_deg)
        midpoint = (lower[axis] + upper[axis]) / 2.0
        left_upper = list(upper)
        right_lower = list(lower)
        left_upper[axis] = midpoint
        right_lower[axis] = midpoint
        return (
            RotationCell(tuple(lower), tuple(left_upper), self.depth + 1),
            RotationCell(tuple(right_lower), tuple(upper), self.depth + 1),
        )


def _zone_body_from_bounds(bounds: Any, *, inflation_mm: float = 0.0) -> Any:
    from build123d import Align, Box

    min_xyz = tuple(float(value) for value in bounds.min)
    max_xyz = tuple(float(value) for value in bounds.max)
    size = tuple(
        max(max_xyz[i] - min_xyz[i] + 2.0 * inflation_mm, 0.0) for i in range(3)
    )
    center = tuple((min_xyz[i] + max_xyz[i]) / 2.0 for i in range(3))
    zone = Box(
        size[0],
        size[1],
        size[2],
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    if any(abs(value) > 1e-12 for value in center):
        zone = zone.move(Location(center))
    return zone


def _shape_list(component: Any) -> list[Any]:
    children = getattr(component, "children", None)
    if children:
        leaves: list[Any] = []
        for child in children:
            leaves.extend(_shape_list(child))
        if leaves:
            return leaves
    return [component]


def _shape_label(shape: Any) -> str:
    label = getattr(shape, "label", None)
    text = str(label or "").strip()
    return text


def _labelled_solids(component: Any, *, artifact_name: str) -> list[Any]:
    solids = _shape_list(component)
    if not solids:
        raise ValueError(f"{artifact_name}: component contains no solids")

    component_label = _shape_label(component)
    labels: list[str] = []
    cleaned: list[Any] = []
    for index, solid in enumerate(solids):
        label = _shape_label(solid)
        if not label and len(solids) == 1 and component_label:
            label = component_label
            try:
                solid.label = label
            except Exception:
                pass
        if not label:
            raise ValueError(
                f"{artifact_name}: solid[{index}] is missing a stable label"
            )
        if label in labels:
            raise ValueError(
                f"{artifact_name}: duplicate solid label '{label}' prevents "
                "unambiguous swept-clearance validation"
            )
        labels.append(label)
        cleaned.append(solid)
    return cleaned


def _shape_bbox(
    shape: Any,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    bbox = shape.bounding_box()
    return tuple(float(v) for v in bbox.min), tuple(float(v) for v in bbox.max)


def _bbox_intersects(
    left_min: tuple[float, float, float],
    left_max: tuple[float, float, float],
    right_min: tuple[float, float, float],
    right_max: tuple[float, float, float],
) -> bool:
    return all(
        left_min[index] <= right_max[index] and right_min[index] <= left_max[index]
        for index in range(3)
    )


def _bbox_within_bounds(
    inner_min: tuple[float, float, float],
    inner_max: tuple[float, float, float],
    outer_min: tuple[float, float, float],
    outer_max: tuple[float, float, float],
) -> bool:
    return all(
        outer_min[index] <= inner_min[index] <= inner_max[index] <= outer_max[index]
        for index in range(3)
    )


def _shape_radius_from_origin(component: Any) -> float:
    mesh = part_to_trimesh(component)
    vertices = getattr(mesh, "vertices", None)
    if vertices is None or len(vertices) == 0:
        return 0.0
    return max(
        sqrt(float(vertex[0]) ** 2 + float(vertex[1]) ** 2 + float(vertex[2]) ** 2)
        for vertex in vertices
    )


def _collect_motion_names(assembly_definition: AssemblyDefinition | None) -> set[str]:
    if assembly_definition is None:
        return set()
    return {
        part.part_name.strip()
        for part in assembly_definition.moving_parts
        if part.part_name.strip()
    }


def _combine_shapes(shapes: list[Any], *, artifact_name: str) -> Any:
    if not shapes:
        raise ValueError(f"{artifact_name}: no shapes available for validation")
    if len(shapes) == 1:
        return shapes[0]
    combined = Compound(children=shapes)
    combined.label = f"{artifact_name}_compound"
    return combined


def _make_transform(
    *,
    sample_pos_mm: tuple[float, float, float],
    sample_rot_deg: tuple[float, float, float],
    initial_pose_pos_mm: tuple[float, float, float],
    initial_pose_rot_deg: tuple[float, float, float],
) -> Location:
    sample_location = Location(
        tuple(float(value) for value in sample_pos_mm),
        tuple(float(value) for value in sample_rot_deg),
    )
    initial_location = Location(
        tuple(float(value) for value in initial_pose_pos_mm),
        tuple(float(value) for value in initial_pose_rot_deg),
    )
    return sample_location * initial_location.inverse()


def _lerp_tuple3d(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    fraction: float,
) -> tuple[float, float, float]:
    return tuple(
        start[index] + (end[index] - start[index]) * fraction for index in range(3)
    )


def _segment_interval_count(
    *,
    duration_s: float | None = None,
    start_pos_mm: tuple[float, float, float] | None = None,
    end_pos_mm: tuple[float, float, float] | None = None,
    sample_stride_s: float | None,
    moving_radius: float | None = None,
) -> int:
    if duration_s is not None:
        if duration_s <= 0.0 or sample_stride_s is None:
            return 0
        return max(2, int(ceil((2.0 * duration_s) / max(sample_stride_s, 1e-9))))

    if start_pos_mm is None or end_pos_mm is None:
        return 0

    delta = tuple(end_pos_mm[index] - start_pos_mm[index] for index in range(3))
    distance_mm = sqrt(sum(component * component for component in delta))
    if distance_mm <= 0.0:
        return 0

    return max(
        2,
        int(
            ceil(
                distance_mm / max((moving_radius or 1.0) * 0.5, 1.0),
            )
        ),
    )


def _validate_sampled_pose(
    *,
    sample_label: str,
    sample_pos_mm: tuple[float, float, float],
    sample_rot_deg: tuple[float, float, float],
    initial_pose_pos_mm: tuple[float, float, float],
    initial_pose_rot_deg: tuple[float, float, float],
    moving_component: Any,
    fixed_component: Any | None,
    benchmark_definition: BenchmarkDefinition,
    allow_goal_zone_overlap: bool,
    require_goal_zone_overlap: bool,
) -> list[str]:
    transform = _make_transform(
        sample_pos_mm=sample_pos_mm,
        sample_rot_deg=sample_rot_deg,
        initial_pose_pos_mm=initial_pose_pos_mm,
        initial_pose_rot_deg=initial_pose_rot_deg,
    )
    return _exact_pose_checks(
        moving_component=moving_component,
        transform=transform,
        fixed_component=fixed_component,
        benchmark_definition=benchmark_definition,
        allow_goal_zone_overlap=allow_goal_zone_overlap,
        require_goal_zone_overlap=require_goal_zone_overlap,
        sample_point_label=sample_label,
    )


def _exact_pose_cache_key(
    *,
    sample_pos_mm: tuple[float, float, float],
    sample_rot_deg: tuple[float, float, float],
    allow_goal_zone_overlap: bool,
    require_goal_zone_overlap: bool,
) -> ExactPoseCacheKey:
    return (
        round(sample_pos_mm[0], 6),
        round(sample_pos_mm[1], 6),
        round(sample_pos_mm[2], 6),
        round(sample_rot_deg[0], 6),
        round(sample_rot_deg[1], 6),
        round(sample_rot_deg[2], 6),
        allow_goal_zone_overlap,
        require_goal_zone_overlap,
    )


def _anchor_sample_points(
    anchor: PayloadTrajectoryAnchor,
    *,
    max_exact_checks: int,
) -> list[tuple[float, float, float]]:
    if anchor.rotation_tolerance_deg is None:
        return [tuple(float(value) for value in anchor.rot_deg)]

    lower = tuple(
        float(anchor.rot_deg[index]) - float(anchor.rotation_tolerance_deg[index])
        for index in range(3)
    )
    upper = tuple(
        float(anchor.rot_deg[index]) + float(anchor.rotation_tolerance_deg[index])
        for index in range(3)
    )
    corners = [
        (x, y, z)
        for x in (lower[0], upper[0])
        for y in (lower[1], upper[1])
        for z in (lower[2], upper[2])
    ]
    samples = list(dict.fromkeys(corners + [anchor.rot_deg]))
    if len(samples) > max_exact_checks:
        raise ValueError(
            "payload_trajectory_definition.yaml: exact orientation sampling "
            "budget is too small for the declared rotation envelope"
        )
    return [tuple(float(value) for value in sample) for sample in samples]


def _pose_sphere_is_obviously_clear(
    *,
    center_pos_mm: tuple[float, float, float],
    radius_mm: float,
    forbidden_bodies: list[Any],
    fixed_bounds: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
    simulation_bounds: tuple[tuple[float, float, float], tuple[float, float, float]]
    | None,
) -> bool:
    center_min = tuple(float(value) - radius_mm for value in center_pos_mm)
    center_max = tuple(float(value) + radius_mm for value in center_pos_mm)

    if simulation_bounds is not None and not _bbox_within_bounds(
        center_min, center_max, simulation_bounds[0], simulation_bounds[1]
    ):
        return False

    for fixed_min, fixed_max in fixed_bounds:
        if _bbox_intersects(center_min, center_max, fixed_min, fixed_max):
            return False

    for body in forbidden_bodies:
        body_min, body_max = _shape_bbox(body)
        if _bbox_intersects(center_min, center_max, body_min, body_max):
            return False

    return True


def _exact_pose_checks(
    *,
    moving_component: Any,
    transform: Location,
    fixed_component: Any | None,
    benchmark_definition: BenchmarkDefinition,
    allow_goal_zone_overlap: bool,
    require_goal_zone_overlap: bool,
    sample_point_label: str,
) -> list[str]:
    moved = moving_component.move(transform)
    moved_min, moved_max = _shape_bbox(moved)
    sim_min, sim_max = _shape_bbox(
        _zone_body_from_bounds(benchmark_definition.simulation_bounds)
    )
    if not _bbox_within_bounds(moved_min, moved_max, sim_min, sim_max):
        return [
            f"{sample_point_label}: moved payload leaves benchmark_definition.simulation_bounds"
        ]

    for zone in benchmark_definition.objectives.forbid_zones:
        zone_body = _zone_body_from_bounds(zone, inflation_mm=1e-6)
        try:
            intersection = moved.intersect(zone_body)
        except Exception as exc:
            return [
                f"{sample_point_label}: unable to evaluate forbid-zone overlap: {exc}"
            ]
        if _shape_volume(intersection) > 0.0:
            return [
                f"{sample_point_label}: moved payload intersects forbid zone '{zone.name}'"
            ]

    if require_goal_zone_overlap:
        goal_zone_body = _zone_body_from_bounds(
            benchmark_definition.objectives.goal_zone, inflation_mm=1e-6
        )
        try:
            goal_intersection = moved.intersect(goal_zone_body)
        except Exception as exc:
            return [
                f"{sample_point_label}: unable to evaluate goal-zone overlap: {exc}"
            ]
        if _shape_volume(goal_intersection) <= 0.0:
            return [f"{sample_point_label}: terminal pose does not enter goal_zone"]
    elif not allow_goal_zone_overlap:
        goal_zone_body = _zone_body_from_bounds(
            benchmark_definition.objectives.goal_zone, inflation_mm=1e-6
        )
        try:
            goal_intersection = moved.intersect(goal_zone_body)
        except Exception as exc:
            return [
                f"{sample_point_label}: unable to evaluate goal-zone overlap: {exc}"
            ]
        if _shape_volume(goal_intersection) > 0.0:
            return [
                f"{sample_point_label}: non-terminal pose unexpectedly intersects goal_zone"
            ]

    if fixed_component is not None:
        try:
            intersection = moved.intersect(fixed_component)
        except Exception as exc:
            return [
                f"{sample_point_label}: unable to evaluate fixed-geometry overlap: {exc}"
            ]
        if _shape_volume(intersection) > 0.0:
            return [f"{sample_point_label}: moved payload intersects fixed geometry"]

    return []


def _validate_cell(
    *,
    cell: RotationCell,
    anchor: PayloadTrajectoryAnchor,
    initial_pose: Any,
    moving_component: Any,
    fixed_component: Any | None,
    benchmark_definition: BenchmarkDefinition,
    fixed_bounds: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
    forbidden_bodies: list[Any],
    moving_radius: float,
    budget: PayloadTrajectoryClearanceBudget,
    exact_pose_cache: dict[ExactPoseCacheKey, list[str]],
    accepted_cells: list[RotationCell],
    terminal_goal_proof: bool,
) -> list[str] | None:
    if len(accepted_cells) >= budget.max_orientation_cells:
        return [
            "payload_trajectory_definition.yaml: orientation cell budget exhausted "
            "before proof completed"
        ]

    sample_pos_mm = tuple(float(value) for value in anchor.pos_mm)
    if cell.widest_span() <= max(budget.leaf_span_deg) or cell.is_exact():
        sample_rotations = _anchor_sample_points(
            anchor=model_anchor_for_cell(anchor, cell),
            max_exact_checks=budget.max_exact_checks,
        )
        if len(sample_rotations) > budget.max_exact_checks:
            return [
                "payload_trajectory_definition.yaml: exact orientation sampling "
                "budget exhausted before proof completed"
            ]
        for sample_rot_deg in sample_rotations:
            allow_goal_zone_overlap = terminal_goal_proof
            require_goal_zone_overlap = terminal_goal_proof
            cache_key = _exact_pose_cache_key(
                sample_pos_mm=sample_pos_mm,
                sample_rot_deg=sample_rot_deg,
                allow_goal_zone_overlap=allow_goal_zone_overlap,
                require_goal_zone_overlap=require_goal_zone_overlap,
            )
            if cache_key not in exact_pose_cache:
                transform = _make_transform(
                    sample_pos_mm=sample_pos_mm,
                    sample_rot_deg=sample_rot_deg,
                    initial_pose_pos_mm=tuple(float(v) for v in initial_pose.pos_mm),
                    initial_pose_rot_deg=tuple(float(v) for v in initial_pose.rot_deg),
                )
                exact_pose_cache[cache_key] = _exact_pose_checks(
                    moving_component=moving_component,
                    transform=transform,
                    fixed_component=fixed_component,
                    benchmark_definition=benchmark_definition,
                    allow_goal_zone_overlap=allow_goal_zone_overlap,
                    require_goal_zone_overlap=require_goal_zone_overlap,
                    sample_point_label=(
                        f"payload_trajectory_definition.yaml anchors[{anchor.t_s:.3f}s]"
                    ),
                )
            if exact_pose_cache[cache_key]:
                return exact_pose_cache[cache_key]

        accepted_cells.append(cell)
        return None

    center_rot = cell.midpoint()
    transform = _make_transform(
        sample_pos_mm=sample_pos_mm,
        sample_rot_deg=center_rot,
        initial_pose_pos_mm=tuple(float(v) for v in initial_pose.pos_mm),
        initial_pose_rot_deg=tuple(float(v) for v in initial_pose.rot_deg),
    )
    if (
        _pose_sphere_is_obviously_clear(
            center_pos_mm=sample_pos_mm,
            radius_mm=moving_radius,
            forbidden_bodies=forbidden_bodies,
            fixed_bounds=fixed_bounds,
            simulation_bounds=_shape_bbox(
                _zone_body_from_bounds(benchmark_definition.simulation_bounds)
            ),
        )
        and not terminal_goal_proof
    ):
        accepted_cells.append(cell)
        return None

    # Ambiguous cells are subdivided along the widest remaining angular span.
    left, right = cell.split()
    if (
        left.depth > budget.max_recursion_depth
        or right.depth > budget.max_recursion_depth
    ):
        return [
            "payload_trajectory_definition.yaml: rotation envelope could not be "
            "proven within the recursion budget"
        ]

    left_result = _validate_cell(
        cell=left,
        anchor=anchor,
        initial_pose=initial_pose,
        moving_component=moving_component,
        fixed_component=fixed_component,
        benchmark_definition=benchmark_definition,
        fixed_bounds=fixed_bounds,
        forbidden_bodies=forbidden_bodies,
        moving_radius=moving_radius,
        budget=budget,
        exact_pose_cache=exact_pose_cache,
        accepted_cells=accepted_cells,
        terminal_goal_proof=terminal_goal_proof,
    )
    if left_result:
        return left_result
    return _validate_cell(
        cell=right,
        anchor=anchor,
        initial_pose=initial_pose,
        moving_component=moving_component,
        fixed_component=fixed_component,
        benchmark_definition=benchmark_definition,
        fixed_bounds=fixed_bounds,
        forbidden_bodies=forbidden_bodies,
        moving_radius=moving_radius,
        budget=budget,
        exact_pose_cache=exact_pose_cache,
        accepted_cells=accepted_cells,
        terminal_goal_proof=terminal_goal_proof,
    )


def model_anchor_for_cell(
    anchor: PayloadTrajectoryAnchor, cell: RotationCell
) -> PayloadTrajectoryAnchor:
    if cell.is_exact():
        return anchor
    return anchor.model_copy(
        update={
            "rot_deg": cell.midpoint(),
            "rotation_tolerance_deg": tuple(
                (cell.upper_deg[index] - cell.lower_deg[index]) / 2.0
                for index in range(3)
            ),
        }
    )


def validate_payload_trajectory_swept_clearance(
    *,
    workspace_root: Path,
    benchmark_definition: BenchmarkDefinition,
    payload_definition: PayloadTrajectoryDefinition,
    assembly_definition: AssemblyDefinition | None = None,
    benchmark_assembly_definition: AssemblyDefinition | None = None,
    fixed_script_path: str | Path = BENCHMARK_SCRIPT_PATH,
    moving_script_path: str | Path = SOLUTION_SCRIPT_PATH,
    session_id: str | None = None,
) -> list[str]:
    budget = load_agents_config().payload_trajectory_clearance
    if not budget.enabled:
        return []

    errors: list[str] = []
    workspace_root = Path(workspace_root)
    fixed_script_path = Path(fixed_script_path)
    moving_script_path = Path(moving_script_path)
    benchmark_script_path = workspace_root / fixed_script_path
    solution_script_path = workspace_root / moving_script_path

    if not benchmark_script_path.exists():
        errors.append(
            "payload_trajectory_definition.yaml: "
            f"{fixed_script_path.as_posix()} is required "
            "to validate fixed geometry"
        )
    if not solution_script_path.exists():
        errors.append(
            "payload_trajectory_definition.yaml: "
            f"{moving_script_path.as_posix()} is required "
            "to validate moving geometry"
        )
    if errors:
        return errors

    from shared.workers.loader import load_component_from_script

    try:
        benchmark_component = load_component_from_script(
            script_path=benchmark_script_path,
            session_root=workspace_root,
        )
        solution_component = load_component_from_script(
            script_path=solution_script_path,
            session_root=workspace_root,
        )
    except Exception as exc:
        return [
            "payload_trajectory_definition.yaml: unable to load workspace "
            f"geometry: {exc}"
        ]

    benchmark_solids = _labelled_solids(
        benchmark_component, artifact_name=fixed_script_path.as_posix()
    )
    solution_solids = _labelled_solids(
        solution_component, artifact_name=moving_script_path.as_posix()
    )

    label_counts = Counter(
        _shape_label(shape) for shape in benchmark_solids + solution_solids
    )
    duplicate_labels = sorted(
        label for label, count in label_counts.items() if count > 1
    )
    if duplicate_labels:
        return [
            "payload_trajectory_definition.yaml: duplicate solid labels across "
            f"workspace geometry: {duplicate_labels}"
        ]

    payload_labels = set(payload_definition.payload_part_names)
    payload_labels.update(_collect_motion_names(assembly_definition))
    payload_labels.update(_collect_motion_names(benchmark_assembly_definition))

    all_solids = benchmark_solids + solution_solids
    payload_solids = [
        solid for solid in all_solids if _shape_label(solid) in payload_labels
    ]
    fixed_solids = [
        solid for solid in all_solids if _shape_label(solid) not in payload_labels
    ]

    if not payload_solids:
        return [
            "payload_trajectory_definition.yaml: no solids match the declared "
            "payload_part_names"
        ]
    try:
        moving_component = _combine_shapes(
            payload_solids, artifact_name="moving_payload"
        )
        fixed_component = (
            _combine_shapes(fixed_solids, artifact_name="fixed_scene")
            if fixed_solids
            else None
        )
    except Exception as exc:
        return [f"payload_trajectory_definition.yaml: {exc}"]

    moving_radius = _shape_radius_from_origin(moving_component)
    if moving_radius <= 0.0:
        return [
            "payload_trajectory_definition.yaml: unable to derive a moving "
            "geometry broad-phase radius"
        ]

    fixed_bounds = [_shape_bbox(shape) for shape in fixed_solids]
    forbidden_bodies = [
        _zone_body_from_bounds(zone, inflation_mm=1e-6)
        for zone in benchmark_definition.objectives.forbid_zones
    ]

    first_anchor = payload_definition.anchors[0]
    exact_pose_cache: dict[ExactPoseCacheKey, list[str]] = {}
    accepted_cells: list[RotationCell] = []

    if (
        first_anchor.reference_point != payload_definition.initial_pose.reference_point
        or first_anchor.pos_mm != payload_definition.initial_pose.pos_mm
        or first_anchor.rot_deg != payload_definition.initial_pose.rot_deg
    ):
        errors.append(
            "payload_trajectory_definition.yaml: initial_pose must match the "
            "first anchor pose and reference_point"
        )

    for index, anchor in enumerate(payload_definition.anchors):
        terminal_goal_proof = (
            index == len(payload_definition.anchors) - 1
            and payload_definition.terminal_event is None
            and bool(anchor.goal_zone_contact or anchor.goal_zone_entry)
        )
        if anchor.rotation_tolerance_deg is None:
            cell = RotationCell(tuple(anchor.rot_deg), tuple(anchor.rot_deg), 0)
        else:
            cell = RotationCell(
                tuple(
                    float(anchor.rot_deg[i]) - float(anchor.rotation_tolerance_deg[i])
                    for i in range(3)
                ),
                tuple(
                    float(anchor.rot_deg[i]) + float(anchor.rotation_tolerance_deg[i])
                    for i in range(3)
                ),
                0,
            )

        cell_error = _validate_cell(
            cell=cell,
            anchor=anchor,
            initial_pose=payload_definition.initial_pose,
            moving_component=moving_component,
            fixed_component=fixed_component,
            benchmark_definition=benchmark_definition,
            fixed_bounds=fixed_bounds,
            forbidden_bodies=forbidden_bodies,
            moving_radius=moving_radius,
            budget=budget,
            exact_pose_cache=exact_pose_cache,
            accepted_cells=accepted_cells,
            terminal_goal_proof=terminal_goal_proof,
        )
        if cell_error:
            return cell_error

    for index, (start_anchor, end_anchor) in enumerate(
        zip(payload_definition.anchors, payload_definition.anchors[1:])
    ):
        interval_count = _segment_interval_count(
            duration_s=float(end_anchor.t_s) - float(start_anchor.t_s),
            sample_stride_s=float(payload_definition.sample_stride_s),
        )
        if interval_count <= 0:
            continue

        start_rot = tuple(float(value) for value in start_anchor.rot_deg)
        end_rot = tuple(float(value) for value in end_anchor.rot_deg)
        start_pos = tuple(float(value) for value in start_anchor.pos_mm)
        end_pos = tuple(float(value) for value in end_anchor.pos_mm)
        start_time = float(start_anchor.t_s)
        end_time = float(end_anchor.t_s)

        for step_index in range(1, interval_count):
            fraction = step_index / interval_count
            sample_pos_mm = _lerp_tuple3d(start_pos, end_pos, fraction)
            sample_rot_deg = _lerp_tuple3d(start_rot, end_rot, fraction)
            sample_time_s = start_time + (end_time - start_time) * fraction
            cache_key = _exact_pose_cache_key(
                sample_pos_mm=sample_pos_mm,
                sample_rot_deg=sample_rot_deg,
                allow_goal_zone_overlap=False,
                require_goal_zone_overlap=False,
            )
            if cache_key not in exact_pose_cache:
                exact_pose_cache[cache_key] = _validate_sampled_pose(
                    sample_label=(
                        "payload_trajectory_definition.yaml segment["
                        f"{index}->{index + 1}] t={sample_time_s:.3f}s"
                    ),
                    sample_pos_mm=sample_pos_mm,
                    sample_rot_deg=sample_rot_deg,
                    initial_pose_pos_mm=tuple(
                        float(v) for v in payload_definition.initial_pose.pos_mm
                    ),
                    initial_pose_rot_deg=tuple(
                        float(v) for v in payload_definition.initial_pose.rot_deg
                    ),
                    moving_component=moving_component,
                    fixed_component=fixed_component,
                    benchmark_definition=benchmark_definition,
                    allow_goal_zone_overlap=False,
                    require_goal_zone_overlap=False,
                )
            if exact_pose_cache[cache_key]:
                return exact_pose_cache[cache_key]

    if payload_definition.terminal_event is not None:
        terminal_start_anchor = payload_definition.anchors[-1]
        terminal_end_pos = tuple(
            float(value) for value in payload_definition.terminal_event.pos_mm
        )
        terminal_interval_count = _segment_interval_count(
            start_pos_mm=tuple(float(value) for value in terminal_start_anchor.pos_mm),
            end_pos_mm=terminal_end_pos,
            sample_stride_s=None,
            moving_radius=moving_radius,
        )
        if terminal_interval_count > 0:
            terminal_start_pos = tuple(
                float(value) for value in terminal_start_anchor.pos_mm
            )
            terminal_rot_deg = tuple(
                float(value) for value in terminal_start_anchor.rot_deg
            )
            for step_index in range(1, terminal_interval_count):
                fraction = step_index / terminal_interval_count
                sample_pos_mm = _lerp_tuple3d(
                    terminal_start_pos, terminal_end_pos, fraction
                )
                cache_key = _exact_pose_cache_key(
                    sample_pos_mm=sample_pos_mm,
                    sample_rot_deg=terminal_rot_deg,
                    allow_goal_zone_overlap=False,
                    require_goal_zone_overlap=False,
                )
                if cache_key not in exact_pose_cache:
                    exact_pose_cache[cache_key] = _validate_sampled_pose(
                        sample_label=(
                            "payload_trajectory_definition.yaml "
                            f"terminal_segment[{step_index}/{terminal_interval_count}]"
                        ),
                        sample_pos_mm=sample_pos_mm,
                        sample_rot_deg=terminal_rot_deg,
                        initial_pose_pos_mm=tuple(
                            float(v) for v in payload_definition.initial_pose.pos_mm
                        ),
                        initial_pose_rot_deg=tuple(
                            float(v) for v in payload_definition.initial_pose.rot_deg
                        ),
                        moving_component=moving_component,
                        fixed_component=fixed_component,
                        benchmark_definition=benchmark_definition,
                        allow_goal_zone_overlap=False,
                        require_goal_zone_overlap=False,
                    )
                if exact_pose_cache[cache_key]:
                    return exact_pose_cache[cache_key]

        terminal_transform = _make_transform(
            sample_pos_mm=terminal_end_pos,
            sample_rot_deg=tuple(
                float(value) for value in payload_definition.anchors[-1].rot_deg
            ),
            initial_pose_pos_mm=tuple(
                float(v) for v in payload_definition.initial_pose.pos_mm
            ),
            initial_pose_rot_deg=tuple(
                float(v) for v in payload_definition.initial_pose.rot_deg
            ),
        )
        terminal_errors = _exact_pose_checks(
            moving_component=moving_component,
            transform=terminal_transform,
            fixed_component=fixed_component,
            benchmark_definition=benchmark_definition,
            allow_goal_zone_overlap=True,
            require_goal_zone_overlap=True,
            sample_point_label="payload_trajectory_definition.yaml terminal_event",
        )
        if terminal_errors:
            return terminal_errors

    logger.info(
        "payload_trajectory_swept_clearance_valid",
        session_id=session_id,
        cells=len(accepted_cells),
    )
    return []
