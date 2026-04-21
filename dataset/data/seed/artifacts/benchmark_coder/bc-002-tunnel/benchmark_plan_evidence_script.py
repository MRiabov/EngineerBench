from __future__ import annotations

from build123d import Align, Box, Compound, Location

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


def build() -> Compound:
    """Return the benchmark evidence geometry for the tunnel plan."""

    # The evidence scene should show a single benchmark-owned tunnel shell.
    tunnel_length = 1020.0
    tunnel_clear_width = 60.0
    tunnel_clear_height = 60.0
    wall_thickness = 10.0

    children = [
        _make_panel(
            (tunnel_length, tunnel_clear_width + 2.0 * wall_thickness, wall_thickness),
            (0.0, 0.0, -(tunnel_clear_height + wall_thickness) / 2.0),
        ),
        _make_panel(
            (tunnel_length, tunnel_clear_width + 2.0 * wall_thickness, wall_thickness),
            (0.0, 0.0, (tunnel_clear_height + wall_thickness) / 2.0),
        ),
        _make_panel(
            (tunnel_length, wall_thickness, tunnel_clear_height + 2.0 * wall_thickness),
            (0.0, -(tunnel_clear_width + wall_thickness) / 2.0, 0.0),
        ),
        _make_panel(
            (tunnel_length, wall_thickness, tunnel_clear_height + 2.0 * wall_thickness),
            (0.0, (tunnel_clear_width + wall_thickness) / 2.0, 0.0),
        ),
    ]

    fixture = Compound(children=children)
    fixture.label = "environment_fixture"
    fixture.metadata = CompoundMetadata(is_fixed=True)
    return fixture


result = build()
