from __future__ import annotations

from build123d import Align, Box, Compound, Cylinder, Location

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


def _make_spike(
    label: str,
    radius: float,
    height: float,
    center: tuple[float, float, float],
    material_id: str,
):
    part = Cylinder(
        radius=radius,
        height=height,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    ).move(Location(center))
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, is_fixed=True)
    return part


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

    fixtures = Compound(
        children=[
            _make_box(
                "upper_start_platform",
                (178.0, 150.0, 28.0),
                (-298.0, 18.0, 188.0),
                "aluminum_6061",
            ),
            _make_box(
                "upper_mid_step",
                (150.0, 124.0, 24.0),
                (-126.0, 16.0, 140.0),
                "hdpe",
            ),
            _make_box(
                "lower_mid_step",
                (146.0, 118.0, 22.0),
                (44.0, 20.0, 86.0),
                "hdpe",
            ),
            _make_box(
                "offset_goal_basin",
                (160.0, 136.0, 18.0),
                (160.0, 34.0, 24.0),
                "hardwood",
            ),
            _make_spike(
                "spike_nw",
                16.0,
                58.0,
                (-404.0, 82.0, 170.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_ne",
                16.0,
                58.0,
                (-84.0, -78.0, 162.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_center",
                16.0,
                58.0,
                (-12.0, 88.0, 130.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_sw",
                16.0,
                58.0,
                (58.0, -70.0, 104.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_tail_left",
                16.0,
                58.0,
                (122.0, 116.0, 92.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_tail_right",
                16.0,
                58.0,
                (136.0, -82.0, 80.0),
                "steel_carbon",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
