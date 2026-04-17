from __future__ import annotations

from pathlib import Path

import pytest

import dataset.synthetic.tube_guided_synthetic_rigid_body_corpus as package
import notebooks.tube_guided_synthetic_rigid_body_corpus as notebook_wrapper
from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.size_guard import (
    assert_generator_tree_line_limits,
)
from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus import (
    ContactHit,
    PartSpec,
    RoutePoint,
    ScenarioConfig,
    SegmentSpan,
    default_route_points,
    main,
    synthesize,
)

pytestmark = [pytest.mark.integration, pytest.mark.integration_p2]


@pytest.mark.int_id("INT-279")
def test_tube_guided_synthetic_corpus_package_and_wrapper_exports_remain_stable():
    route_points = default_route_points()

    assert len(route_points) == 6
    assert [point.name for point in route_points] == [
        "build_zone_start",
        "left_capture_lane",
        "bypass_corner",
        "goal_lane_entry",
        "goal_approach",
        "goal_zone_contact",
    ]
    assert all(isinstance(point, RoutePoint) for point in route_points)

    assert package.__all__ == notebook_wrapper.__all__
    assert package.ContactHit is ContactHit
    assert package.PartSpec is PartSpec
    assert package.RoutePoint is RoutePoint
    assert package.ScenarioConfig is ScenarioConfig
    assert package.SegmentSpan is SegmentSpan
    assert package.default_route_points is notebook_wrapper.default_route_points
    assert package.main is notebook_wrapper.main
    assert package.synthesize is notebook_wrapper.synthesize
    assert main is notebook_wrapper.main
    assert synthesize is notebook_wrapper.synthesize


@pytest.mark.int_id("INT-280")
def test_tube_guided_synthetic_corpus_size_guard_enforces_line_cap(
    tmp_path: Path,
):
    package_root = (
        Path(__file__).resolve().parents[3]
        / "dataset"
        / "synthetic"
        / "tube_guided_synthetic_rigid_body_corpus"
    )

    assert_generator_tree_line_limits(package_root)

    oversized_root = tmp_path / "generator_tree"
    oversized_root.mkdir()
    oversized_file = oversized_root / "oversized.py"
    oversized_file.write_text("x = 1\n" * 801, encoding="utf-8")

    with pytest.raises(RuntimeError, match="file-size cap of 800 lines"):
        assert_generator_tree_line_limits(oversized_root)
