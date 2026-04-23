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
                (-300.0, -18.0, 182.0),
                "aluminum_6061",
            ),
            _make_box(
                "upper_mid_step",
                (160.0, 128.0, 24.0),
                (-120.0, -6.0, 132.0),
                "hdpe",
            ),
            _make_box(
                "lower_mid_step",
                (150.0, 120.0, 22.0),
                (60.0, 18.0, 78.0),
                "hdpe",
            ),
            _make_box(
                "offset_goal_basin",
                (150.0, 132.0, 20.0),
                (312.0, 34.0, 24.0),
                "hardwood",
            ),
            _make_spike(
                "north_spike",
                18.0,
                58.0,
                (-150.0, 30.0, 174.0),
                "steel_carbon",
            ),
            _make_spike(
                "south_spike",
                18.0,
                58.0,
                (-60.0, -22.0, 174.0),
                "steel_carbon",
            ),
            _make_spike(
                "center_spike",
                18.0,
                58.0,
                (34.0, 18.0, 119.0),
                "steel_carbon",
            ),
            _make_spike(
                "tail_spike",
                18.0,
                58.0,
                (130.0, -18.0, 119.0),
                "steel_carbon",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
