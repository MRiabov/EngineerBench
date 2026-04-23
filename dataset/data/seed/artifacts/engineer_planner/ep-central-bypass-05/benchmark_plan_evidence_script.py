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


def build() -> Compound:
    """Return the benchmark plan evidence geometry for this workspace."""

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
            (10.0, 14.0, 32.0),
            (0.0, 3.0, 16.0),
            "hdpe",
        ),
    ]
    fixtures = Compound(children=children)
    fixtures.label = "benchmark_environment"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
