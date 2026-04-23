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
                (150.0, 130.0, 20.0),
                (-275.0, -20.0, 170.0),
                "hardwood",
            ),
            _make_box(
                "upper_chute_step",
                (170.0, 108.0, 20.0),
                (-170.0, -18.0, 138.0),
                "hdpe",
            ),
            _make_box(
                "mid_chute_step",
                (180.0, 92.0, 20.0),
                (-25.0, 10.0, 102.0),
                "hdpe",
            ),
            _make_box(
                "lower_chute_step",
                (190.0, 84.0, 20.0),
                (125.0, 28.0, 64.0),
                "hdpe",
            ),
            _make_box(
                "exit_tray",
                (160.0, 104.0, 30.0),
                (275.0, 28.0, 20.0),
                "hardwood",
            ),
            _make_box(
                "left_guard_rail",
                (320.0, 16.0, 160.0),
                (-45.0, -128.0, 100.0),
                "aluminum_6061",
            ),
            _make_box(
                "right_guard_rail",
                (320.0, 16.0, 160.0),
                (-45.0, 94.0, 100.0),
                "aluminum_6061",
            ),
            _make_box(
                "decoy_tower",
                (30.0, 30.0, 140.0),
                (30.0, -160.0, 90.0),
                "hdpe",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
