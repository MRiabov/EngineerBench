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
    """Return the benchmark assembly geometry for this workspace."""

    fixtures = Compound(
        children=[
            _make_box(
                "left_start_deck",
                (180.0, 180.0, 70.0),
                (-230.0, 0.0, 35.0),
                "aluminum_6061",
            ),
            _make_box(
                "right_goal_deck",
                (200.0, 180.0, 70.0),
                (270.0, 0.0, 35.0),
                "aluminum_6061",
            ),
            _make_box(
                "bridge_reference_table",
                (140.0, 120.0, 30.0),
                (90.0, 0.0, 55.0),
                "aluminum_6061",
            ),
            _make_box(
                "gap_floor_guard",
                (160.0, 300.0, 40.0),
                (20.0, 0.0, 20.0),
                "hdpe",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
