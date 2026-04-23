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
                (180.0, 170.0, 66.0),
                (-228.0, -20.0, 33.0),
                "aluminum_6061",
            ),
            _make_box(
                "right_goal_deck",
                (192.0, 174.0, 78.0),
                (268.0, 18.0, 39.0),
                "aluminum_6061",
            ),
            _make_box(
                "bridge_reference_table",
                (136.0, 96.0, 24.0),
                (70.0, -8.0, 58.0),
                "aluminum_6061",
                rotation=(0.0, 0.0, -8.0),
            ),
            _make_box(
                "gap_floor_guard",
                (200.0, 300.0, 36.0),
                (12.0, 0.0, 18.0),
                "hdpe",
            ),
            _make_box(
                "left_terrace",
                (86.0, 40.0, 12.0),
                (-176.0, -150.0, 14.0),
                "hardwood",
            ),
            _make_box(
                "right_terrace",
                (86.0, 40.0, 12.0),
                (214.0, 130.0, 14.0),
                "hardwood",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
