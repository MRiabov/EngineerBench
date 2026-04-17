from __future__ import annotations

import math
from itertools import pairwise

import numpy as np
import pytest
from scipy.spatial.transform import Rotation as SciPyRotation

from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus import (
    default_route_points,
)
from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.geometry import (
    box_part_specs_for_route,
    build_box_part,
    compound_from_specs,
    validate_geometry,
    validate_route_clearance,
)
from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.models import (
    PartSpec,
)
from shared.models.schemas import (
    BenchmarkDefinition,
    BenchmarkPartDefinition,
    BenchmarkPartMetadata,
    BoundingBox,
    Constraints,
    ObjectivesSection,
    Payload,
    PhysicsConfig,
)
from shared.simulation.schemas import SimulatorBackendType
from worker_heavy.workbenches.analysis_utils import part_to_trimesh

pytestmark = [
    pytest.mark.integration,
    pytest.mark.integration_p2,
    pytest.mark.xdist_group(name="physics_sims"),
]


def _point_to_segment_distance(
    point: np.ndarray, start: np.ndarray, end: np.ndarray
) -> float:
    segment = end - start
    denom = float(np.dot(segment, segment))
    if denom <= 0.0:
        return float(np.linalg.norm(point - start))
    fraction = float(np.dot(point - start, segment) / denom)
    fraction = min(max(fraction, 0.0), 1.0)
    projection = start + fraction * segment
    return float(np.linalg.norm(point - projection))


def _reference_frame(start_mm: np.ndarray, end_mm: np.ndarray) -> np.ndarray:
    x_axis = end_mm - start_mm
    x_axis = x_axis / np.linalg.norm(x_axis)
    up = np.array([0.0, 0.0, 1.0], dtype=float)
    if abs(float(np.dot(x_axis, up))) > 0.95:
        up = np.array([0.0, 1.0, 0.0], dtype=float)
    y_axis = np.cross(up, x_axis)
    y_axis = y_axis / np.linalg.norm(y_axis)
    z_axis = np.cross(x_axis, y_axis)
    z_axis = z_axis / np.linalg.norm(z_axis)
    y_axis = np.cross(z_axis, x_axis)
    y_axis = y_axis / np.linalg.norm(y_axis)
    return np.column_stack([x_axis, y_axis, z_axis])


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 0.0:
        raise ValueError("zero-length vector")
    return vector / norm


def _line_distance_to_line(
    point_a: np.ndarray, direction_a: np.ndarray, point_b: np.ndarray
) -> float:
    direction_a = _unit(direction_a)
    delta = point_b - point_a
    return float(np.linalg.norm(delta - np.dot(delta, direction_a) * direction_a))


def _axis_segment(
    center_mm: np.ndarray, axis_direction: np.ndarray, length_mm: float
) -> tuple[np.ndarray, np.ndarray]:
    half_length = _unit(axis_direction) * (float(length_mm) / 2.0)
    return center_mm - half_length, center_mm + half_length


def _assert_orthonormal(frame: np.ndarray) -> None:
    identity = np.eye(3)
    assert np.allclose(frame.T @ frame, identity, atol=1e-6), frame.tolist()


def _assert_frame_axes_match_up_to_permutation(
    actual_frame: np.ndarray, expected_frame: np.ndarray
) -> None:
    assert np.allclose(actual_frame.T @ actual_frame, np.eye(3), atol=1e-6), (
        actual_frame.tolist()
    )
    assert np.allclose(expected_frame.T @ expected_frame, np.eye(3), atol=1e-6), (
        expected_frame.tolist()
    )

    overlap = np.abs(actual_frame.T @ expected_frame)
    assert np.allclose(overlap.max(axis=0), 1.0, atol=1e-6), overlap.tolist()
    assert np.allclose(overlap.max(axis=1), 1.0, atol=1e-6), overlap.tolist()


def _projected_axis_bounds(
    vertices: np.ndarray, axis: np.ndarray
) -> tuple[float, float]:
    projections = vertices @ axis
    return float(projections.min()), float(projections.max())


def _assert_adjacent_break_sections_are_contiguous(
    *,
    prev_name: str,
    prev_vertices: np.ndarray,
    next_name: str,
    next_vertices: np.ndarray,
    axis: np.ndarray,
    tolerance_mm: float = 1e-3,
) -> None:
    prev_min, prev_max = _projected_axis_bounds(prev_vertices, axis)
    next_min, next_max = _projected_axis_bounds(next_vertices, axis)
    gap_mm = next_min - prev_max

    assert np.isfinite(prev_min) and np.isfinite(prev_max)
    assert np.isfinite(next_min) and np.isfinite(next_max)
    assert gap_mm <= tolerance_mm, (
        prev_name,
        next_name,
        gap_mm,
        prev_min,
        prev_max,
        next_min,
        next_max,
        axis.tolist(),
    )


def _benchmark_definition(route_points: list) -> BenchmarkDefinition:
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


@pytest.mark.int_id("INT-281")
def test_tube_guided_synthetic_corpus_route_geometry_validates_and_fails_closed():
    route_points = default_route_points()
    benchmark_definition = _benchmark_definition(route_points)
    tube_radius_mm = 10.0
    clearance_mm = 2.0
    wall_thickness_mm = 2.0
    max_segment_mm = 32.0

    route_clearance_errors = validate_route_clearance(
        route_points=route_points,
        benchmark_definition=benchmark_definition,
        pipe_radius_mm=17.0,
        clearance_mm=clearance_mm,
    )
    assert route_clearance_errors == [], route_clearance_errors

    specs = box_part_specs_for_route(
        route_points,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=clearance_mm,
        wall_thickness_mm=wall_thickness_mm,
        max_segment_mm=max_segment_mm,
        seed=11,
        material_id="aluminum_6061",
    )
    compound = compound_from_specs(specs, "synthetic_route")

    route_xyz = np.asarray([point.pos_mm for point in route_points], dtype=float)
    allowed_vertex_distance_mm = math.hypot(
        tube_radius_mm + clearance_mm - wall_thickness_mm,
        tube_radius_mm + clearance_mm,
    )

    validate_geometry(compound)

    assert len(getattr(compound, "children", [])) == len(specs)
    for child, spec in zip(compound.children, specs, strict=True):
        vertices = list(child.vertices())
        assert vertices, spec.name
        actual_frame = SciPyRotation.from_euler(
            "xyz", spec.euler_deg, degrees=True
        ).as_matrix()
        segment_start = route_xyz[spec.segment_index]
        segment_end = route_xyz[spec.segment_index + 1]
        expected_frame = _reference_frame(segment_start, segment_end)
        assert np.allclose(actual_frame, expected_frame, atol=1e-6), (
            spec.name,
            spec.euler_deg,
            actual_frame.tolist(),
            expected_frame.tolist(),
        )
        for vertex in vertices:
            point = np.asarray([vertex.X, vertex.Y, vertex.Z], dtype=float)
            nearest_distance = min(
                _point_to_segment_distance(point, route_xyz[idx], route_xyz[idx + 1])
                for idx in range(len(route_xyz) - 1)
            )
            assert nearest_distance <= allowed_vertex_distance_mm + 1e-6, (
                spec.name,
                nearest_distance,
                allowed_vertex_distance_mm,
                point.tolist(),
            )

    overlapping_specs = [
        PartSpec(
            name="seg_00_split_00_floor",
            segment_index=0,
            split_index=0,
            side="floor",
            dims_mm=(12.0, 12.0, 12.0),
            center_mm=(0.0, 0.0, 0.0),
            euler_deg=(0.0, 0.0, 0.0),
            material_id="aluminum_6061",
            is_fixed=True,
        ),
        PartSpec(
            name="seg_02_split_00_floor",
            segment_index=2,
            split_index=0,
            side="floor",
            dims_mm=(12.0, 12.0, 12.0),
            center_mm=(0.0, 0.0, 0.0),
            euler_deg=(0.0, 0.0, 0.0),
            material_id="aluminum_6061",
            is_fixed=True,
        ),
    ]
    overlapping_compound = compound_from_specs(overlapping_specs, "overlap_case")
    with pytest.raises(ValueError, match="self-intersects"):
        validate_geometry(overlapping_compound)


@pytest.mark.int_id("INT-284")
def test_tube_guided_synthetic_corpus_box_axis_lines_are_parallel_perpendicular_and_non_intersecting():
    route_points = default_route_points()
    tube_radius_mm = 10.0
    clearance_mm = 2.0
    wall_thickness_mm = 2.0
    max_segment_mm = 32.0

    specs = box_part_specs_for_route(
        route_points,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=clearance_mm,
        wall_thickness_mm=wall_thickness_mm,
        max_segment_mm=max_segment_mm,
        seed=11,
        material_id="aluminum_6061",
    )
    compound = compound_from_specs(specs, "synthetic_route")
    validate_geometry(compound)

    route_xyz = np.asarray([point.pos_mm for point in route_points], dtype=float)
    route_directions = [
        _unit(route_xyz[index + 1] - route_xyz[index])
        for index in range(len(route_xyz) - 1)
    ]
    corridor_width_mm = 2.0 * tube_radius_mm + 2.0 * clearance_mm
    corridor_height_mm = 2.0 * tube_radius_mm + 2.0 * clearance_mm
    side_offsets = {
        "floor": np.array(
            [0.0, 0.0, -corridor_height_mm / 2.0 + wall_thickness_mm / 2.0]
        ),
        "roof": np.array(
            [0.0, 0.0, corridor_height_mm / 2.0 - wall_thickness_mm / 2.0]
        ),
        "left_wall": np.array(
            [0.0, -corridor_width_mm / 2.0 + wall_thickness_mm / 2.0, 0.0]
        ),
        "right_wall": np.array(
            [0.0, corridor_width_mm / 2.0 - wall_thickness_mm / 2.0, 0.0]
        ),
    }

    specs_by_segment_and_split: dict[tuple[int, int], list[PartSpec]] = {}
    specs_by_segment_and_side: dict[tuple[int, str], list[PartSpec]] = {}
    for spec in specs:
        specs_by_segment_and_split.setdefault(
            (spec.segment_index, spec.split_index), []
        ).append(spec)
        specs_by_segment_and_side.setdefault(
            (spec.segment_index, spec.side), []
        ).append(spec)

    for spec in specs:
        frame = SciPyRotation.from_euler(
            "xyz", spec.euler_deg, degrees=True
        ).as_matrix()
        _assert_orthonormal(frame)

        x_axis = frame[:, 0]
        y_axis = frame[:, 1]
        z_axis = frame[:, 2]
        route_direction = route_directions[spec.segment_index]
        center = np.asarray(spec.center_mm, dtype=float)
        expected_offset = frame @ side_offsets[spec.side]

        assert np.isclose(abs(float(np.dot(x_axis, route_direction))), 1.0, atol=1e-6)
        assert np.isclose(float(np.dot(x_axis, y_axis)), 0.0, atol=1e-6)
        assert np.isclose(float(np.dot(x_axis, z_axis)), 0.0, atol=1e-6)
        assert np.isclose(float(np.dot(y_axis, z_axis)), 0.0, atol=1e-6)

        axis_start, axis_end = _axis_segment(center, x_axis, float(spec.dims_mm[0]))
        assert np.isfinite(axis_start).all()
        assert np.isfinite(axis_end).all()

        route_distance = _line_distance_to_line(
            center, x_axis, route_xyz[spec.segment_index]
        )
        assert np.isclose(
            route_distance, float(np.linalg.norm(expected_offset)), atol=1e-6
        ), (spec.name, route_distance, expected_offset.tolist())

    for (
        _segment_index,
        _split_index,
    ), split_specs in specs_by_segment_and_split.items():
        split_specs.sort(key=lambda spec: spec.side)

        for left_index, left_spec in enumerate(split_specs):
            left_frame = SciPyRotation.from_euler(
                "xyz", left_spec.euler_deg, degrees=True
            ).as_matrix()
            left_axis = left_frame[:, 0]
            left_center = np.asarray(left_spec.center_mm, dtype=float)
            left_offset = side_offsets[left_spec.side]

            for right_spec in split_specs[left_index + 1 :]:
                right_frame = SciPyRotation.from_euler(
                    "xyz", right_spec.euler_deg, degrees=True
                ).as_matrix()
                right_axis = right_frame[:, 0]
                right_center = np.asarray(right_spec.center_mm, dtype=float)
                right_offset = side_offsets[right_spec.side]

                assert np.isclose(
                    abs(float(np.dot(left_axis, right_axis))), 1.0, atol=1e-6
                )

                actual_distance = _line_distance_to_line(
                    left_center, left_axis, right_center
                )
                expected_distance = float(np.linalg.norm(right_offset - left_offset))
                assert np.isclose(actual_distance, expected_distance, atol=1e-6), (
                    left_spec.name,
                    right_spec.name,
                    actual_distance,
                    expected_distance,
                )
                assert actual_distance > 1e-6, (
                    left_spec.name,
                    right_spec.name,
                    actual_distance,
                )

    for (_segment_index, side), side_specs in specs_by_segment_and_side.items():
        side_specs.sort(key=lambda spec: spec.split_index)
        for prev_spec, next_spec in pairwise(side_specs):
            prev_frame = SciPyRotation.from_euler(
                "xyz", prev_spec.euler_deg, degrees=True
            ).as_matrix()
            next_frame = SciPyRotation.from_euler(
                "xyz", next_spec.euler_deg, degrees=True
            ).as_matrix()
            prev_axis = prev_frame[:, 0]
            next_axis = next_frame[:, 0]
            prev_center = np.asarray(prev_spec.center_mm, dtype=float)
            next_center = np.asarray(next_spec.center_mm, dtype=float)
            prev_start, prev_end = _axis_segment(
                prev_center, prev_axis, float(prev_spec.dims_mm[0])
            )
            next_start, next_end = _axis_segment(
                next_center, next_axis, float(next_spec.dims_mm[0])
            )

            assert np.isclose(abs(float(np.dot(prev_axis, next_axis))), 1.0, atol=1e-6)
            assert np.linalg.norm(prev_end - next_start) <= 1e-6, (
                prev_spec.name,
                next_spec.name,
                prev_end.tolist(),
                next_start.tolist(),
            )
            assert _line_distance_to_line(prev_start, prev_axis, next_start) <= 1e-6


@pytest.mark.int_id("INT-285")
def test_tube_guided_synthetic_corpus_trimesh_export_preserves_representative_box_frames():
    route_points = default_route_points()
    tube_radius_mm = 10.0
    clearance_mm = 2.0
    wall_thickness_mm = 2.0
    max_segment_mm = 32.0

    specs = box_part_specs_for_route(
        route_points,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=clearance_mm,
        wall_thickness_mm=wall_thickness_mm,
        max_segment_mm=max_segment_mm,
        seed=11,
        material_id="aluminum_6061",
    )

    route_xyz = np.asarray([point.pos_mm for point in route_points], dtype=float)
    representative_specs = [
        next(
            spec
            for spec in specs
            if spec.segment_index == segment_index
            and spec.split_index == 0
            and spec.side == "floor"
        )
        for segment_index in (0, 1, 3)
    ]

    for spec in representative_specs:
        mesh = part_to_trimesh(build_box_part(spec))
        assert mesh.is_watertight, spec.name
        assert mesh.vertices.shape[0] > 0, spec.name

        expected_center = np.asarray(spec.center_mm, dtype=float)
        assert np.allclose(mesh.centroid, expected_center, atol=1e-3), (
            spec.name,
            mesh.centroid.tolist(),
            expected_center.tolist(),
        )

        actual_frame = mesh.bounding_box_oriented.primitive.transform[:3, :3]
        expected_frame = _reference_frame(
            route_xyz[spec.segment_index], route_xyz[spec.segment_index + 1]
        )
        _assert_frame_axes_match_up_to_permutation(
            actual_frame=actual_frame,
            expected_frame=expected_frame,
        )


@pytest.mark.int_id("INT-286")
def test_tube_guided_synthetic_corpus_build123d_break_sections_remain_contiguous():
    route_points = default_route_points()
    tube_radius_mm = 10.0
    clearance_mm = 2.0
    wall_thickness_mm = 2.0
    max_segment_mm = 32.0

    specs = box_part_specs_for_route(
        route_points,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=clearance_mm,
        wall_thickness_mm=wall_thickness_mm,
        max_segment_mm=max_segment_mm,
        seed=11,
        material_id="aluminum_6061",
    )

    specs_by_segment_and_side: dict[tuple[int, str], list[PartSpec]] = {}
    for spec in specs:
        specs_by_segment_and_side.setdefault(
            (spec.segment_index, spec.side), []
        ).append(spec)

    for (_segment_index, side), side_specs in specs_by_segment_and_side.items():
        side_specs.sort(key=lambda spec: spec.split_index)
        for prev_spec, next_spec in pairwise(side_specs):
            prev_part = build_box_part(prev_spec)
            next_part = build_box_part(next_spec)
            prev_vertices = np.asarray(
                [[vertex.X, vertex.Y, vertex.Z] for vertex in prev_part.vertices()],
                dtype=float,
            )
            next_vertices = np.asarray(
                [[vertex.X, vertex.Y, vertex.Z] for vertex in next_part.vertices()],
                dtype=float,
            )
            axis = SciPyRotation.from_euler(
                "xyz", prev_spec.euler_deg, degrees=True
            ).as_matrix()[:, 0]

            _assert_adjacent_break_sections_are_contiguous(
                prev_name=prev_spec.name,
                prev_vertices=prev_vertices,
                next_name=next_spec.name,
                next_vertices=next_vertices,
                axis=axis,
            )


@pytest.mark.int_id("INT-287")
def test_tube_guided_synthetic_corpus_trimesh_break_sections_remain_contiguous():
    route_points = default_route_points()
    tube_radius_mm = 10.0
    clearance_mm = 2.0
    wall_thickness_mm = 2.0
    max_segment_mm = 32.0

    specs = box_part_specs_for_route(
        route_points,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=clearance_mm,
        wall_thickness_mm=wall_thickness_mm,
        max_segment_mm=max_segment_mm,
        seed=11,
        material_id="aluminum_6061",
    )

    segment_counts: dict[int, int] = {}
    for spec in specs:
        segment_counts[spec.segment_index] = (
            segment_counts.get(spec.segment_index, 0) + 1
        )
    chosen_segment_index = max(segment_counts, key=segment_counts.get)
    segment_specs = [
        spec for spec in specs if spec.segment_index == chosen_segment_index
    ]
    segment_specs_by_side: dict[str, list[PartSpec]] = {}
    for spec in segment_specs:
        segment_specs_by_side.setdefault(spec.side, []).append(spec)

    mesh_by_spec_name = {
        spec.name: part_to_trimesh(build_box_part(spec)) for spec in segment_specs
    }

    for side, side_specs in segment_specs_by_side.items():
        side_specs.sort(key=lambda spec: spec.split_index)
        for prev_spec, next_spec in pairwise(side_specs):
            prev_mesh = mesh_by_spec_name[prev_spec.name]
            next_mesh = mesh_by_spec_name[next_spec.name]
            axis = SciPyRotation.from_euler(
                "xyz", prev_spec.euler_deg, degrees=True
            ).as_matrix()[:, 0]

            _assert_adjacent_break_sections_are_contiguous(
                prev_name=prev_spec.name,
                prev_vertices=np.asarray(prev_mesh.vertices, dtype=float),
                next_name=next_spec.name,
                next_vertices=np.asarray(next_mesh.vertices, dtype=float),
                axis=axis,
            )
