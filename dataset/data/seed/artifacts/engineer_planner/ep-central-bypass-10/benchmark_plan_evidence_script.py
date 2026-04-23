from __future__ import annotations

from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata


def _make_box(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    material_id: str,
    rotation_deg: tuple[float, float, float] | None = None,
):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center, rotation_deg or (0.0, 0.0, 0.0))
    )
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, is_fixed=True)
    return part


def build() -> Compound:
    """Return the benchmark plan evidence geometry for this workspace."""

    children = [
        _make_box(
            "left_start_deck",
            (28.0, 18.0, 4.0),
            (-30.0, 0.0, 2.0),
            "aluminum_6061",
        ),
        _make_box(
            "right_goal_deck",
            (28.0, 18.0, 4.0),
            (30.0, 0.0, 2.0),
            "aluminum_6061",
        ),
        _make_box(
            "central_blocker",
            (12.0, 12.0, 40.0),
            (0.0, 2.0, 20.0),
            "hdpe",
            rotation_deg=(0.0, 0.0, 15.0),
        ),
    ]
    fixtures = Compound(children=children)
    fixtures.label = "benchmark_environment"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
