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
                (160.0, 150.0, 22.0),
                (300.0, 0.0, 28.0),
                "hardwood",
            ),
            _make_spike(
                "spike_left",
                18.0,
                58.0,
                (-120.0, -32.0, 168.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_center",
                18.0,
                58.0,
                (-25.0, 0.0, 168.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_right",
                18.0,
                58.0,
                (70.0, 32.0, 113.0),
                "steel_carbon",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
