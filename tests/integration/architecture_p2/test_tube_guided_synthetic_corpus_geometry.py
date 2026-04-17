from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.spatial.transform import Rotation as SciPyRotation

from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus import (
    default_route_points,
)
from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.geometry import (
    box_part_specs_for_route,
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
