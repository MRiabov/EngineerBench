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
    """Return the benchmark geometry for this workspace."""

    fixtures = Compound(
        children=[
            _make_box(
                "upper_inlet_frame",
                (150.0, 150.0, 20.0),
                (-260.0, 0.0, 170.0),
                "hardwood",
            ),
            _make_box(
                "upper_chute_step",
                (180.0, 140.0, 20.0),
                (-150.0, 0.0, 135.0),
                "hdpe",
            ),
            _make_box(
                "mid_chute_step",
                (190.0, 140.0, 20.0),
                (-20.0, 0.0, 95.0),
                "hdpe",
            ),
            _make_box(
                "lower_chute_step",
                (190.0, 140.0, 20.0),
                (120.0, 0.0, 55.0),
                "hdpe",
            ),
            _make_box(
                "exit_tray",
                (170.0, 150.0, 30.0),
                (265.0, 0.0, 20.0),
                "hardwood",
            ),
            _make_box(
                "left_guard_rail",
                (320.0, 20.0, 160.0),
                (-60.0, -85.0, 100.0),
                "aluminum_6061",
            ),
            _make_box(
                "right_guard_rail",
                (320.0, 20.0, 160.0),
                (-60.0, 85.0, 100.0),
                "aluminum_6061",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
