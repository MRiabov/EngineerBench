from build123d import Align, Box, BuildPart, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def build() -> Compound:
    with BuildPart() as part_1:
        Box(500, 170, 10, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part_1_part = part_1.part.move(Location((0, 0, 5)))
    part_1_part.label = "base_plate"
    part_1_part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)

    with BuildPart() as part_2:
        Box(190, 120, 36, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_2_part = part_2.part.move(Location((-120, 0, 10)))
    part_2_part.label = "alignment_funnel"
    part_2_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as part_3:
        Box(88, 54, 28, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_3_part = part_3.part.move(Location((30, 0, 22)))
    part_3_part.label = "throat_insert"
    part_3_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as part_4:
        Box(110, 90, 38, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_4_part = part_4.part.move(Location((170, 0, 10)))
    part_4_part.label = "goal_pocket"
    part_4_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    assembly = Compound(
        label="narrow_goal_funnel_review_seed",
        children=[part_1_part, part_2_part, part_3_part, part_4_part],
    )
    assembly.metadata = CompoundMetadata(fixed=False)
    return assembly
