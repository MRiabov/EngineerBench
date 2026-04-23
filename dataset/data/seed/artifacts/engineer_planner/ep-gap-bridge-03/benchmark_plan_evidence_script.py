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
                (184.0, 184.0, 66.0),
                (-236.0, 0.0, 33.0),
                "aluminum_6061",
            ),
            _make_box(
                "right_goal_deck",
                (200.0, 180.0, 76.0),
                (266.0, 0.0, 44.0),
                "aluminum_6061",
            ),
            _make_box(
                "bridge_reference_table",
                (144.0, 116.0, 26.0),
                (78.0, 0.0, 57.0),
                "aluminum_6061",
            ),
            _make_box(
                "gap_floor_guard",
                (172.0, 300.0, 36.0),
                (12.0, 0.0, 18.0),
                "hdpe",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
