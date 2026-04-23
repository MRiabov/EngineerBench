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
                (-260.0, 5.0, 170.0),
                "hardwood",
            ),
            _make_box(
                "upper_chute_step",
                (170.0, 96.0, 20.0),
                (-165.0, 35.0, 135.0),
                "hdpe",
            ),
            _make_box(
                "first_bend_diverter",
                (44.0, 28.0, 70.0),
                (-35.0, 92.0, 96.0),
                "hdpe",
            ),
            _make_box(
                "second_bend_diverter",
                (44.0, 28.0, 70.0),
                (77.0, -18.0, 66.0),
                "hdpe",
            ),
            _make_box(
                "lower_chute_step",
                (180.0, 102.0, 20.0),
                (190.0, -50.0, 55.0),
                "hardwood",
            ),
            _make_box(
                "exit_tray",
                (170.0, 122.0, 30.0),
                (270.0, -50.0, 20.0),
                "hardwood",
            ),
            _make_box(
                "inner_guard_rail",
                (300.0, 18.0, 160.0),
                (40.0, -140.0, 100.0),
                "aluminum_6061",
            ),
            _make_box(
                "outer_guard_rail",
                (300.0, 18.0, 160.0),
                (40.0, 118.0, 100.0),
                "aluminum_6061",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
