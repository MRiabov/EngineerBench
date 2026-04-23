from __future__ import annotations

from build123d import Align, Box, Compound, Location

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


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

    gate_wall = (
        Box(24.0, 132.0, 120.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        - Box(28.0, 72.0, 84.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    ).move(Location((0.0, 10.0, 68.0)))
    gate_wall.label = "gate_wall"
    gate_wall.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)

    fixtures = Compound(
        children=[
            _make_box(
                "left_start_pad",
                (150.0, 130.0, 16.0),
                (-225.0, 0.0, 8.0),
                "aluminum_6061",
            ),
            gate_wall,
            _make_box(
                "right_goal_pad",
                (150.0, 130.0, 16.0),
                (225.0, 0.0, 8.0),
                "aluminum_6061",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
