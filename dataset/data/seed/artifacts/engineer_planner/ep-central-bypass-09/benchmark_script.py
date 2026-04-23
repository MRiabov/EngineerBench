from __future__ import annotations

from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata


def _make_box(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    material_id: str,
):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center)
    )
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, is_fixed=True)
    return part


def _build_static_fixtures() -> Compound:
    children = [
        _make_box(
            "left_start_deck",
            (28.0, 18.0, 4.0),
            (-30.0, 0.0, 2.0),
            "aluminum_6061",
        ),
        _make_box(
            "right_goal_deck",
            (28.0, 18.0, 4.0),
            (30.0, 0.0, 2.0),
            "aluminum_6061",
        ),
        _make_box(
            "central_blocker",
            (14.0, 18.0, 38.0),
            (0.0, 0.0, 19.0),
            "hdpe",
        ),
    ]
    fixtures = Compound(children=children)
    fixtures.label = "benchmark_environment"
    fixtures.metadata = CompoundMetadata()
    return fixtures


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

    return _build_static_fixtures()


result = build()
