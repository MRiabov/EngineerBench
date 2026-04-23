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
                (-292.0, -20.0, 190.0),
                "aluminum_6061",
            ),
            _make_box(
                "upper_mid_step",
                (154.0, 126.0, 24.0),
                (-128.0, -14.0, 142.0),
                "hdpe",
            ),
            _make_box(
                "lower_mid_step",
                (146.0, 120.0, 22.0),
                (44.0, -2.0, 88.0),
                "hdpe",
            ),
            _make_box(
                "goal_basin",
                (166.0, 142.0, 20.0),
                (156.0, 18.0, 20.0),
                "hardwood",
            ),
            _make_spike(
                "spike_high_left",
                16.0,
                58.0,
                (-180.0, -120.0, 172.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_high_right",
                16.0,
                58.0,
                (-82.0, 88.0, 148.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_low_left",
                16.0,
                58.0,
                (0.0, -88.0, 110.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_tail",
                16.0,
                58.0,
                (126.0, 92.0, 88.0),
                "steel_carbon",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
