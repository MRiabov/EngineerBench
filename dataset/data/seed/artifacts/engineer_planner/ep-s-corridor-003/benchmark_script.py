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
                "left_launch_pad",
                (80.0, 60.0, 30.0),
                (-220.0, -95.0, 15.0),
                "hardwood",
            ),
            _make_box(
                "corridor_block_a",
                (60.0, 90.0, 80.0),
                (-50.0, 70.0, 40.0),
                "hardwood",
            ),
            _make_box(
                "corridor_block_b",
                (50.0, 110.0, 80.0),
                (150.0, -45.0, 40.0),
                "hardwood",
            ),
            _make_box(
                "corridor_deadend_block",
                (70.0, 50.0, 80.0),
                (250.0, -155.0, 40.0),
                "hardwood",
            ),
            _make_box(
                "corridor_block_c",
                (60.0, 90.0, 80.0),
                (340.0, 80.0, 40.0),
                "hardwood",
            ),
            _make_box(
                "goal_catch_tray",
                (80.0, 60.0, 30.0),
                (560.0, 35.0, 15.0),
                "hardwood",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
