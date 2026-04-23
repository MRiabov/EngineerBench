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

    front_gate_wall = Rotation(0.0, 0.0, 8.0) * (
        Box(20.0, 88.0, 96.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        - Box(24.0, 48.0, 70.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    )
    front_gate_wall = front_gate_wall.move(Location((0.0, -6.0, 58.0)))
    front_gate_wall.label = "front_gate_wall"
    front_gate_wall.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)

    step_plinth = Box(
        104.0, 14.0, 12.0, align=(Align.CENTER, Align.CENTER, Align.CENTER)
    )
    step_plinth = step_plinth.move(Location((38.0, -60.0, 18.0)))
    step_plinth.label = "step_plinth"
    step_plinth.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)

    rear_gate_wall = Rotation(0.0, 0.0, -6.0) * (
        Box(20.0, 94.0, 104.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        - Box(24.0, 52.0, 78.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    )
    rear_gate_wall = rear_gate_wall.move(Location((74.0, 8.0, 72.0)))
    rear_gate_wall.label = "rear_gate_wall"
    rear_gate_wall.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)

    fixtures = Compound(
        children=[
            _make_box(
                "left_start_pad",
                (150.0, 130.0, 16.0),
                (-225.0, 0.0, 8.0),
                "aluminum_6061",
            ),
            front_gate_wall,
            step_plinth,
            rear_gate_wall,
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
