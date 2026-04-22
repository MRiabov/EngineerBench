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
    fixtures = Compound(
        children=[
            _make_box(
                'left_start_pad',
                (140.0, 120.0, 20.0),
                (-225.0, 0.0, 10.0),
                'hdpe',
            ),
            _make_box(
                'goal_capture_tray',
                (160.0, 160.0, 20.0),
                (450.0, 0.0, 10.0),
                'hdpe',
            ),
            _make_box(
                'capture_post',
                (16.0, 16.0, 70.0),
                (450.0, 0.0, 55.0),
                'steel_cold_rolled',
            ),
            _make_box(
                'goal_lip',
                (10.0, 160.0, 12.0),
                (525.0, 0.0, 26.0),
                'hdpe',
            ),
        ]
    )
    fixtures.label = 'benchmark_fixtures'
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
