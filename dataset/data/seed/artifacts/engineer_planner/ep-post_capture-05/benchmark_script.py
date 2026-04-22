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
                (-220.0, 0.0, 10.0),
                'hdpe',
            ),
            _make_box(
                'goal_capture_tray',
                (190.0, 190.0, 20.0),
                (410.0, 0.0, 10.0),
                'hdpe',
            ),
            _make_box(
                'capture_post',
                (22.0, 22.0, 80.0),
                (410.0, 0.0, 60.0),
                'steel_cold_rolled',
            ),
            _make_box(
                'goal_lip',
                (12.0, 190.0, 14.0),
                (499.0, 0.0, 27.0),
                'hdpe',
            ),
        ]
    )
    fixtures.label = 'benchmark_fixtures'
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
