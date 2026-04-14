from build123d import Align, Box, BuildPart, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def build() -> Compound:
    with BuildPart() as part_1:
        Box(540, 190, 12, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part_1_part = part_1.part.move(Location((0, 0, 6)))
    part_1_part.label = "base_frame"
    part_1_part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)

    with BuildPart() as part_2:
        Box(180, 140, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_2_part = part_2.part.move(Location((-120, 0, 130)))
    part_2_part.label = "catch_plate"
    part_2_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as part_3:
        Box(260, 14, 52, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_3_part = part_3.part.move(Location((40, 80, 130)))
    part_3_part.label = "transfer_fence"
    part_3_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as part_4:
        Box(170, 130, 42, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_4_part = part_4.part.move(Location((200, 0, 78)))
    part_4_part.label = "exit_funnel"
    part_4_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    assembly = Compound(
        label="lift_platform_handoff_review_seed",
        children=[part_1_part, part_2_part, part_3_part, part_4_part],
    )
    assembly.metadata = CompoundMetadata(fixed=False)
    return assembly
