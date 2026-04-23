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


def _make_frame(
    label: str,
    outer_size: tuple[float, float, float],
    inner_size: tuple[float, float, float],
    center: tuple[float, float, float],
    material_id: str,
    rotation: tuple[float, float, float] | None = None,
):
    part = (
        Box(*outer_size, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        - Box(*inner_size, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    ).move(Location(center, rotation or (0.0, 0.0, 0.0)))
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, is_fixed=True)
    return part


def build() -> Compound:
    """Return the approved benchmark geometry for this workspace."""

    fixtures = Compound(
        children=[
            _make_box(
                "left_start_pad",
                (160.0, 140.0, 16.0),
                (-245.0, 0.0, 8.0),
                "hardwood",
            ),
            _make_box(
                "funnel_left_outer",
                (110.0, 16.0, 72.0),
                (-78.0, 82.0, 36.0),
                "hardwood",
                rotation=(0.0, 0.0, 6.0),
            ),
            _make_box(
                "funnel_right_outer",
                (110.0, 16.0, 72.0),
                (-78.0, -78.0, 36.0),
                "hardwood",
                rotation=(0.0, 0.0, -6.0),
            ),
            _make_box(
                "funnel_left_mid",
                (138.0, 16.0, 72.0),
                (98.0, 64.0, 36.0),
                "hardwood",
                rotation=(0.0, 0.0, 3.0),
            ),
            _make_box(
                "funnel_right_mid",
                (138.0, 16.0, 72.0),
                (98.0, -58.0, 36.0),
                "hardwood",
                rotation=(0.0, 0.0, -3.0),
            ),
            _make_box(
                "funnel_left_inner",
                (126.0, 16.0, 72.0),
                (246.0, 36.0, 36.0),
                "hardwood",
                rotation=(0.0, 0.0, 2.0),
            ),
            _make_box(
                "funnel_right_inner",
                (126.0, 16.0, 72.0),
                (246.0, -32.0, 36.0),
                "hardwood",
                rotation=(0.0, 0.0, -2.0),
            ),
            _make_frame(
                "goal_throat_frame",
                (20.0, 98.0, 84.0),
                (24.0, 44.0, 62.0),
                (350.0, 3.0, 42.0),
                "hardwood",
                rotation=(0.0, 0.0, 4.0),
            ),
            _make_box(
                "right_goal_pad",
                (110.0, 120.0, 16.0),
                (420.0, 3.0, 8.0),
                "hardwood",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
