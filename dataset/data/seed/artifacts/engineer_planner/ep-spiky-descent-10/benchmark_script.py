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
                (-304.0, -20.0, 202.0),
                "aluminum_6061",
            ),
            _make_box(
                "upper_mid_step",
                (158.0, 126.0, 24.0),
                (-146.0, -14.0, 152.0),
                "hdpe",
            ),
            _make_box(
                "lower_mid_step",
                (148.0, 120.0, 22.0),
                (20.0, -8.0, 96.0),
                "hdpe",
            ),
            _make_box(
                "goal_basin",
                (146.0, 124.0, 18.0),
                (154.0, 12.0, 18.0),
                "hardwood",
            ),
            _make_spike(
                "spike_row_left_1",
                16.0,
                58.0,
                (-206.0, 100.0, 176.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_row_right_1",
                16.0,
                58.0,
                (-172.0, -100.0, 170.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_row_left_2",
                16.0,
                58.0,
                (-94.0, 98.0, 146.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_row_right_2",
                16.0,
                58.0,
                (-60.0, -98.0, 140.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_row_left_3",
                16.0,
                58.0,
                (20.0, 96.0, 112.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_row_right_3",
                16.0,
                58.0,
                (56.0, -96.0, 104.0),
                "steel_carbon",
            ),
            _make_spike(
                "spike_tail",
                16.0,
                58.0,
                (132.0, 0.0, 84.0),
                "steel_carbon",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
