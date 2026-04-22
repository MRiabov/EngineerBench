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
    assembly = Compound(
        children=[
            _make_box(
                "bridge_deck",
                (300.0, 95.0, 8.0),
                (10.0, 0.0, 74.0),
                "aluminum_6061",
            ),
            _make_box(
                "left_support",
                (24.0, 95.0, 18.0),
                (-128.0, 0.0, 61.0),
                "aluminum_6061",
            ),
            _make_box(
                "right_support",
                (24.0, 95.0, 18.0),
                (148.0, 0.0, 61.0),
                "aluminum_6061",
            ),
            _make_box(
                "stop_lip",
                (8.0, 95.0, 12.0),
                (156.0, 0.0, 84.0),
                "aluminum_6061",
            ),
        ]
    )
    assembly.label = "solution_plan_evidence"
    assembly.metadata = CompoundMetadata()
    return assembly


result = build()
