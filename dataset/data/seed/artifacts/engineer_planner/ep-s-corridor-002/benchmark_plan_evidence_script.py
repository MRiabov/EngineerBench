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
    fixtures = Compound(
        children=[
            _make_box(
                "left_launch_pad",
                (80.0, 60.0, 30.0),
                (-240.0, -130.0, 15.0),
                "hardwood",
            ),
            _make_box(
                "corridor_block_a",
                (70.0, 70.0, 80.0),
                (-70.0, 85.0, 40.0),
                "hardwood",
            ),
            _make_box(
                "corridor_block_b",
                (70.0, 90.0, 80.0),
                (120.0, -60.0, 40.0),
                "hardwood",
            ),
            _make_box(
                "corridor_block_c",
                (70.0, 70.0, 80.0),
                (320.0, 90.0, 40.0),
                "hardwood",
            ),
            _make_box(
                "corridor_block_d",
                (70.0, 70.0, 80.0),
                (500.0, -50.0, 40.0),
                "hardwood",
            ),
            _make_box(
                "goal_catch_tray",
                (90.0, 60.0, 30.0),
                (650.0, -120.0, 15.0),
                "hardwood",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures
