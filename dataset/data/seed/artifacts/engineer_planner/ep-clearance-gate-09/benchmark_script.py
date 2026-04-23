from __future__ import annotations

from build123d import Align, Box, Compound, Location, Rotation

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

    gate_wall = Rotation(0.0, 0.0, 12.0) * (
        Box(22.0, 128.0, 128.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        - Box(26.0, 58.0, 94.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    )
    gate_wall = gate_wall.move(Location((0.0, 6.0, 66.0)))
    gate_wall.label = "gate_wall"
    gate_wall.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)

    upper_shroud = Rotation(0.0, 0.0, -10.0) * Box(
        92.0, 10.0, 18.0, align=(Align.CENTER, Align.CENTER, Align.CENTER)
    )
    upper_shroud = upper_shroud.move(Location((24.0, 28.0, 142.0)))
    upper_shroud.label = "upper_shroud"
    upper_shroud.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)

    fixtures = Compound(
        children=[
            _make_box(
                "left_start_pad",
                (150.0, 130.0, 16.0),
                (-225.0, 0.0, 8.0),
                "aluminum_6061",
            ),
            gate_wall,
            upper_shroud,
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
