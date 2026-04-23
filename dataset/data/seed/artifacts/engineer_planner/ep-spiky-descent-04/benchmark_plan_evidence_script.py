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
                (174.0, 148.0, 28.0),
                (-274.0, 2.0, 184.0),
                "aluminum_6061",
            ),
            _make_box(
                "compact_mid_step",
                (146.0, 122.0, 24.0),
                (-106.0, -6.0, 136.0),
                "hdpe",
            ),
            _make_box(
                "compact_lower_step",
                (144.0, 118.0, 22.0),
                (28.0, 8.0, 84.0),
                "hdpe",
            ),
            _make_box(
                "shallow_goal_basin",
                (148.0, 126.0, 18.0),
                (144.0, 12.0, 22.0),
                "hardwood",
            ),
            _make_spike(
                "spike_front_left",
                16.0,
                58.0,
                (-184.0, -108.0, 170.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_mid",
                16.0,
                58.0,
                (-24.0, 76.0, 110.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_low_right",
                16.0,
                58.0,
                (82.0, -72.0, 104.0),
                "steel_carbon",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
