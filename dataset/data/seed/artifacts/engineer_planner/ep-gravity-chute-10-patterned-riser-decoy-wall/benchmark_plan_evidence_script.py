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
    """Return the benchmark geometry evidence scene for this workspace."""

    fixtures = Compound(
        children=[
            _make_box(
                "upper_inlet_frame",
                (160.0, 140.0, 20.0),
                (-255.0, -15.0, 174.0),
                "hardwood",
            ),
            _make_box(
                "upper_chute_step",
                (175.0, 120.0, 20.0),
                (-155.0, -15.0, 140.0),
                "hdpe",
            ),
            _make_box(
                "riser_a",
                (60.0, 35.0, 40.0),
                (-35.0, 15.0, 108.0),
                "hdpe",
            ),
            _make_box(
                "riser_b",
                (80.0, 25.0, 40.0),
                (25.0, -20.0, 78.0),
                "hdpe",
            ),
            _make_box(
                "riser_c",
                (60.0, 35.0, 40.0),
                (100.0, 8.0, 54.0),
                "hdpe",
            ),
            _make_box(
                "lower_chute_step",
                (190.0, 120.0, 20.0),
                (230.0, 0.0, 42.0),
                "hdpe",
            ),
            _make_box(
                "exit_tray",
                (170.0, 130.0, 30.0),
                (270.0, 0.0, 15.0),
                "hardwood",
            ),
            _make_box(
                "left_guard_rail",
                (300.0, 18.0, 160.0),
                (20.0, -130.0, 100.0),
                "aluminum_6061",
            ),
            _make_box(
                "right_guard_rail",
                (300.0, 18.0, 160.0),
                (20.0, 130.0, 100.0),
                "aluminum_6061",
            ),
            _make_box(
                "decoy_wall",
                (80.0, 16.0, 120.0),
                (45.0, 75.0, 88.0),
                "aluminum_6061",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
