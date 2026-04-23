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
                (160.0, 160.0, 20.0),
                (-275.0, 0.0, 184.0),
                "hardwood",
            ),
            _make_box(
                "upper_chute_step",
                (190.0, 128.0, 20.0),
                (-150.0, 0.0, 146.0),
                "hdpe",
            ),
            _make_box(
                "mid_chute_step",
                (200.0, 128.0, 20.0),
                (-10.0, 0.0, 106.0),
                "hdpe",
            ),
            _make_box(
                "lower_chute_step",
                (200.0, 128.0, 20.0),
                (140.0, 35.0, 66.0),
                "hdpe",
            ),
            _make_box(
                "exit_tray",
                (190.0, 160.0, 30.0),
                (305.0, 55.0, 24.0),
                "hardwood",
            ),
            _make_box(
                "left_guard_rail",
                (350.0, 18.0, 170.0),
                (20.0, -110.0, 104.0),
                "aluminum_6061",
            ),
            _make_box(
                "right_guard_rail",
                (350.0, 18.0, 170.0),
                (20.0, 110.0, 104.0),
                "aluminum_6061",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
