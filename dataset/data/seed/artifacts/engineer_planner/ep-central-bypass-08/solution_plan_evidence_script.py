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
                "starter_stub_block",
                (5.0, 5.0, 5.0),
                (0.0, 0.0, 0.0),
                "aluminum_6061",
            ),
        ]
    )
    assembly.label = "starter_stub_assembly"
    assembly.metadata = CompoundMetadata()
    return assembly


result = build()
