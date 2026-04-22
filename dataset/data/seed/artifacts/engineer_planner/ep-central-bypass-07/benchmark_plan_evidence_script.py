from __future__ import annotations

from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata


def _make_box(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center)
    )
    part.label = label
    part.metadata = PartMetadata(material_id="hardwood", is_fixed=True)
    return part


def build() -> Compound:
    fixtures = Compound(
        children=[
            _make_box("left_start_pad", (80.0, 60.0, 20.0), (-180.0, 0.0, 10.0)),
            _make_box("central_blocker", (60.0, 80.0, 50.0), (0.0, 0.0, 25.0)),
            _make_box("right_goal_pad", (80.0, 60.0, 20.0), (180.0, 80.0, 10.0)),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
