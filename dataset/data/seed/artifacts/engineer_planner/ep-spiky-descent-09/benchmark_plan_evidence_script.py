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
                (182.0, 150.0, 30.0),
                (-310.0, -18.0, 200.0),
                "aluminum_6061",
            ),
            _make_box(
                "upper_mid_step",
                (160.0, 126.0, 24.0),
                (-150.0, -12.0, 154.0),
                "hdpe",
            ),
            _make_box(
                "lower_mid_step",
                (150.0, 120.0, 22.0),
                (30.0, -6.0, 100.0),
                "hdpe",
            ),
            _make_box(
                "goal_basin",
                (158.0, 132.0, 22.0),
                (154.0, -24.0, 14.0),
                "hardwood",
            ),
            _make_spike(
                "spike_west_high",
                16.0,
                58.0,
                (-206.0, 108.0, 178.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_west_low",
                16.0,
                58.0,
                (-102.0, -108.0, 154.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_center_high",
                16.0,
                58.0,
                (-14.0, 106.0, 130.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_center_low",
                16.0,
                58.0,
                (64.0, -106.0, 108.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_tail_left",
                16.0,
                58.0,
                (124.0, 104.0, 84.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_tail_right",
                16.0,
                58.0,
                (170.0, -104.0, 68.0),
                "steel_carbon",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
