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
                (180.0, 148.0, 30.0),
                (-306.0, -22.0, 196.0),
                "aluminum_6061",
            ),
            _make_box(
                "upper_mid_step",
                (158.0, 126.0, 24.0),
                (-150.0, -18.0, 152.0),
                "hdpe",
            ),
            _make_box(
                "lower_mid_step",
                (146.0, 116.0, 22.0),
                (22.0, -12.0, 98.0),
                "hdpe",
            ),
            _make_box(
                "goal_basin",
                (152.0, 128.0, 18.0),
                (140.0, 4.0, 18.0),
                "hardwood",
            ),
            _make_spike(
                "spike_front_left",
                16.0,
                58.0,
                (-206.0, 108.0, 176.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_front_right",
                16.0,
                58.0,
                (-102.0, -108.0, 154.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_mid_center",
                16.0,
                58.0,
                (-16.0, 106.0, 126.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_tail_left",
                16.0,
                58.0,
                (74.0, -108.0, 92.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_tail_right",
                16.0,
                58.0,
                (132.0, 104.0, 80.0),
                "steel_carbon",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
