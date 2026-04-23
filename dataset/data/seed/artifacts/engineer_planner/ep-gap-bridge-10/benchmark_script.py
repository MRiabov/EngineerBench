from __future__ import annotations

from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata


def _make_box(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    material_id: str,
    rotation: tuple[float, float, float] | None = None,
):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center, rotation or (0.0, 0.0, 0.0))
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
                "bridge_reference_table",
                (8.0, 8.0, 18.0),
                (0.0, 0.0, 9.0),
                "aluminum_6061",
                rotation=(0.0, 0.0, 10.0),
            ),
            _make_box(
                "gap_floor_guard",
                (18.0, 4.0, 6.0),
                (0.0, -14.0, 3.0),
                "hdpe",
            ),
            _make_box(
                "left_guide_rail",
                (4.0, 16.0, 6.0),
                (-10.0, 0.0, 4.0),
                "hdpe",
            ),
            _make_box(
                "right_guide_rail",
                (4.0, 16.0, 6.0),
                (10.0, 6.0, 4.0),
                "hdpe",
            ),
            _make_box(
                "center_pylon",
                (6.0, 6.0, 10.0),
                (0.0, 12.0, 6.0),
                "hdpe",
            ),
            _make_box(
                "goal_lip",
                (10.0, 4.0, 4.0),
                (50.0, 0.0, 4.0),
                "hardwood",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
