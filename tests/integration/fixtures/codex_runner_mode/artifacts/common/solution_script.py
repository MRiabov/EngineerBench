from __future__ import annotations

from build123d import Align, Box, BuildPart, Compound

from shared.models.schemas import CompoundMetadata, PartMetadata


def build() -> Compound:
    with BuildPart() as part_builder:
        Box(10.0, 10.0, 10.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = part_builder.part
    part.label = "fixture_box"
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)

    assembly = Compound(children=[part], label="fixture_assembly")
    assembly.metadata = CompoundMetadata(is_fixed=True)
    return assembly


result = build()
