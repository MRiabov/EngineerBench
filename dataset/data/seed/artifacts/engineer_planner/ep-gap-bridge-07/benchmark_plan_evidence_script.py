from __future__ import annotations

from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata


def _make_box(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    material_id: str,
    rotation: tuple[float, float, float] | None = None,
):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center, rotation or (0.0, 0.0, 0.0))
    )
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, is_fixed=True)
    return part


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

    fixtures = Compound(
        children=[
            _make_box(
                "left_start_deck",
                (184.0, 172.0, 72.0),
                (-236.0, -12.0, 36.0),
                "aluminum_6061",
            ),
            _make_box(
                "right_goal_deck",
                (196.0, 168.0, 72.0),
                (274.0, 12.0, 36.0),
                "aluminum_6061",
            ),
            _make_box(
                "bridge_reference_table",
                (156.0, 108.0, 30.0),
                (78.0, 6.0, 56.0),
                "aluminum_6061",
                rotation=(0.0, 0.0, 6.0),
            ),
            _make_box(
                "gap_floor_guard",
                (188.0, 320.0, 38.0),
                (18.0, 0.0, 19.0),
                "hdpe",
            ),
            _make_box(
                "left_noise_wall",
                (20.0, 40.0, 88.0),
                (-120.0, -96.0, 44.0),
                "hdpe",
            ),
            _make_box(
                "right_noise_wall",
                (20.0, 40.0, 88.0),
                (150.0, 160.0, 44.0),
                "hdpe",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
