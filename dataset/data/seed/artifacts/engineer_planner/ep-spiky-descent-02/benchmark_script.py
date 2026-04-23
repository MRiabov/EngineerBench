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
                (180.0, 150.0, 28.0),
                (-280.0, 0.0, 174.0),
                "aluminum_6061",
            ),
            _make_box(
                "mid_descent_step",
                (150.0, 130.0, 24.0),
                (-90.0, 0.0, 126.0),
                "hdpe",
            ),
            _make_box(
                "lower_descent_step",
                (150.0, 130.0, 22.0),
                (95.0, 0.0, 72.0),
                "hdpe",
            ),
            _make_box(
                "goal_basin",
                (150.0, 138.0, 20.0),
                (300.0, 0.0, 26.0),
                "hardwood",
            ),
            _make_spike(
                "spike_a",
                18.0,
                58.0,
                (-145.0, -40.0, 168.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_b",
                18.0,
                58.0,
                (-96.0, -10.0, 168.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_c",
                18.0,
                58.0,
                (-42.0, 20.0, 168.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_d",
                18.0,
                58.0,
                (22.0, -16.0, 113.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_e",
                18.0,
                58.0,
                (102.0, 28.0, 113.0),
                "steel_carbon",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
