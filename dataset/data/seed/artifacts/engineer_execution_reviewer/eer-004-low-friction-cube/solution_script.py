from build123d import Align, Box, BuildPart, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def build() -> Compound:
    with BuildPart() as part_1:
        Box(620, 180, 12, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part_1_part = part_1.part.move(Location((0, 0, 6)))
    part_1_part.label = "base_plate"
    part_1_part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)

    with BuildPart() as part_2:
        Box(420, 76, 24, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_2_part = part_2.part.move(Location((-30, 0, 12)))
    part_2_part.label = "guide_channel"
    part_2_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as part_3:
        Box(30, 110, 48, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_3_part = part_3.part.move(Location((160, 95, 12)))
    part_3_part.label = "brake_fence"
    part_3_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as part_4:
        Box(150, 120, 38, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_4_part = part_4.part.move(Location((340, 0, 12)))
    part_4_part.label = "capture_bin"
    part_4_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    assembly = Compound(
        label="low_friction_cube_review_seed",
        children=[part_1_part, part_2_part, part_3_part, part_4_part],
    )
    assembly.metadata = CompoundMetadata(fixed=False)
    return assembly
