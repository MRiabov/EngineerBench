from __future__ import annotations

from build123d import Align, Box, Compound, Location, Rotation

from utils.metadata import CompoundMetadata, PartMetadata


def _make_panel(
    size: tuple[float, float, float],
    center: tuple[float, float, float],
):
    panel = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center)
    )
    panel.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return panel


def _make_shell_segment(
    length: float,
    clear_width: float,
    clear_height: float,
    wall_thickness: float,
    center: tuple[float, float, float],
):
    children = [
        _make_panel(
            (length, clear_width + 2.0 * wall_thickness, wall_thickness),
            (0.0, 0.0, -(clear_height + wall_thickness) / 2.0),
        ),
        _make_panel(
            (length, clear_width + 2.0 * wall_thickness, wall_thickness),
            (0.0, 0.0, (clear_height + wall_thickness) / 2.0),
        ),
        _make_panel(
            (length, wall_thickness, clear_height + 2.0 * wall_thickness),
            (0.0, -(clear_width + wall_thickness) / 2.0, 0.0),
        ),
        _make_panel(
            (length, wall_thickness, clear_height + 2.0 * wall_thickness),
            (0.0, (clear_width + wall_thickness) / 2.0, 0.0),
        ),
    ]
    segment = Compound(children=children).move(Location(center))
    segment.metadata = CompoundMetadata(is_fixed=True)
    return segment


def build() -> Compound:
    """Return the benchmark evidence geometry for the chicane plan."""

    entry = _make_shell_segment(430.0, 64.0, 64.0, 10.0, (-290.0, 0.0, 0.0))
    elbow = Rotation(0.0, 0.0, 12.0) * _make_shell_segment(
        190.0, 60.0, 60.0, 10.0, (-55.0, 22.0, 0.0)
    )
    exit_leg = Rotation(0.0, 0.0, 4.0) * _make_shell_segment(
        360.0, 64.0, 64.0, 10.0, (180.0, 38.0, 0.0)
    )

    fixture = Compound(children=[entry, elbow, exit_leg])
    fixture.label = "environment_fixture"
    fixture.metadata = CompoundMetadata(is_fixed=True)
    return fixture


result = build()
