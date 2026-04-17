from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus import (
    default_route_points,
)
from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.contract import (
    load_benchmark_definition,
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

pytestmark = [pytest.mark.integration, pytest.mark.integration_p2]


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


@pytest.mark.int_id("INT-281")
def test_tube_guided_synthetic_corpus_route_geometry_validates_and_fails_closed():
    route_points = default_route_points()
    benchmark_definition = load_benchmark_definition(
        Path("dataset/data/seed/artifacts/engineer_coder/ec-002-low-friction-cube")
    )
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
