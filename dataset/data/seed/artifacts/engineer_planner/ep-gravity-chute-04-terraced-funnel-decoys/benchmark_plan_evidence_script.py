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
                (150.0, 150.0, 20.0),
                (-270.0, 10.0, 176.0),
                "hardwood",
            ),
            _make_box(
                "terrace_a",
                (160.0, 100.0, 20.0),
                (-190.0, -10.0, 144.0),
                "hdpe",
            ),
            _make_box(
                "terrace_b",
                (150.0, 92.0, 20.0),
                (-95.0, 24.0, 114.0),
                "hdpe",
            ),
            _make_box(
                "terrace_c",
                (140.0, 84.0, 20.0),
                (30.0, 8.0, 84.0),
                "hdpe",
            ),
            _make_box(
                "exit_tray",
                (160.0, 96.0, 30.0),
                (275.0, 18.0, 20.0),
                "hardwood",
            ),
            _make_box(
                "left_guard_rail",
                (320.0, 16.0, 160.0),
                (-45.0, -120.0, 100.0),
                "aluminum_6061",
            ),
            _make_box(
                "right_guard_rail",
                (320.0, 16.0, 160.0),
                (-45.0, 104.0, 100.0),
                "aluminum_6061",
            ),
            _make_box(
                "false_baffle_a",
                (28.0, 24.0, 90.0),
                (80.0, -150.0, 92.0),
                "hdpe",
            ),
            _make_box(
                "false_baffle_b",
                (24.0, 24.0, 80.0),
                (105.0, 140.0, 72.0),
                "hdpe",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
