from __future__ import annotations

from build123d import Align, Box, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


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
                (-224.0, -10.0, 35.0),
                "aluminum_6061",
            ),
            _make_box(
                "right_goal_deck",
                (200.0, 180.0, 70.0),
                (252.0, 10.0, 35.0),
                "aluminum_6061",
            ),
            _make_box(
                "bridge_reference_table",
                (146.0, 120.0, 28.0),
                (68.0, 0.0, 54.0),
                "aluminum_6061",
            ),
            _make_box(
                "gap_floor_guard",
                (168.0, 300.0, 36.0),
                (12.0, 0.0, 18.0),
                "hdpe",
            ),
            _make_box(
                "false_bridge_block",
                (24.0, 24.0, 10.0),
                (18.0, 82.0, 42.0),
                "abs",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
