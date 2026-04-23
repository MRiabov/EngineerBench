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
                (176.0, 150.0, 28.0),
                (-292.0, -10.0, 186.0),
                "aluminum_6061",
            ),
            _make_box(
                "mid_descent_step",
                (150.0, 124.0, 24.0),
                (-120.0, 0.0, 138.0),
                "hdpe",
            ),
            _make_box(
                "lower_descent_step",
                (146.0, 118.0, 22.0),
                (40.0, 12.0, 84.0),
                "hdpe",
            ),
            _make_box(
                "goal_basin",
                (172.0, 140.0, 18.0),
                (160.0, 26.0, 24.0),
                "hardwood",
            ),
            _make_spike(
                "spike_a",
                16.0,
                58.0,
                (-198.0, -122.0, 170.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_b",
                16.0,
                58.0,
                (-68.0, 88.0, 144.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_c",
                16.0,
                58.0,
                (4.0, -78.0, 110.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_d",
                16.0,
                58.0,
                (92.0, 88.0, 96.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_e",
                16.0,
                58.0,
                (136.0, -86.0, 84.0),
                "steel_carbon",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
