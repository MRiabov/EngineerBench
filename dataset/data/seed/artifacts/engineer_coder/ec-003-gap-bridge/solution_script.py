from build123d import Align, Box, BuildPart, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def build() -> Compound:
    with BuildPart() as builder:
        Box(10, 10, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = builder.part.move(Location((-330.0, 0.0, 80.0)))
    part.label = "transfer_cube"
    part.metadata = PartMetadata(material_id="abs", is_fixed=False)
    assembly = Compound(children=[part], label="transfer_cube")
    assembly.metadata = CompoundMetadata(is_fixed=False)
    return assembly
