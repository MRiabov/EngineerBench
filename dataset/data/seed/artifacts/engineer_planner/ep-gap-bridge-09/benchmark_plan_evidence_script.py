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
                (186.0, 170.0, 70.0),
                (-242.0, -24.0, 35.0),
                "aluminum_6061",
            ),
            _make_box(
                "right_goal_deck",
                (202.0, 176.0, 70.0),
                (286.0, 20.0, 35.0),
                "aluminum_6061",
            ),
            _make_box(
                "bridge_reference_table",
                (150.0, 100.0, 30.0),
                (88.0, -10.0, 56.0),
                "aluminum_6061",
                rotation=(0.0, 0.0, 12.0),
            ),
            _make_box(
                "gap_floor_guard",
                (192.0, 312.0, 38.0),
                (24.0, 0.0, 19.0),
                "hdpe",
            ),
            _make_box(
                "center_divider",
                (40.0, 80.0, 44.0),
                (220.0, 150.0, 22.0),
                "hardwood",
            ),
            _make_box(
                "canted_mid_beam",
                (36.0, 22.0, 68.0),
                (152.0, 170.0, 48.0),
                "hardwood",
                rotation=(0.0, 0.0, 28.0),
            ),
            _make_box(
                "false_bridge_block",
                (58.0, 44.0, 18.0),
                (150.0, -58.0, 13.0),
                "hdpe",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
