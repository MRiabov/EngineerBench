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


def _make_frame(
    label: str,
    outer_size: tuple[float, float, float],
    inner_size: tuple[float, float, float],
    center: tuple[float, float, float],
    material_id: str,
):
    part = (
        Box(*outer_size, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        - Box(*inner_size, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    ).move(Location(center))
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, is_fixed=True)
    return part


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

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
                (-75.0, 74.0, 36.0),
                "hardwood",
            ),
            _make_box(
                "funnel_right_outer",
                (110.0, 16.0, 72.0),
                (-75.0, -74.0, 36.0),
                "hardwood",
            ),
            _make_box(
                "funnel_left_mid",
                (135.0, 16.0, 72.0),
                (95.0, 62.0, 36.0),
                "hardwood",
            ),
            _make_box(
                "funnel_right_mid",
                (135.0, 16.0, 72.0),
                (95.0, -54.0, 36.0),
                "hardwood",
            ),
            _make_box(
                "funnel_left_inner",
                (125.0, 16.0, 72.0),
                (245.0, 34.0, 36.0),
                "hardwood",
            ),
            _make_box(
                "funnel_right_inner",
                (125.0, 16.0, 72.0),
                (245.0, -30.0, 36.0),
                "hardwood",
            ),
            _make_frame(
                "goal_throat_frame",
                (20.0, 96.0, 84.0),
                (24.0, 46.0, 64.0),
                (345.0, 6.0, 42.0),
                "hardwood",
            ),
            _make_box(
                "right_goal_pad",
                (110.0, 120.0, 16.0),
                (415.0, 6.0, 8.0),
                "hardwood",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
