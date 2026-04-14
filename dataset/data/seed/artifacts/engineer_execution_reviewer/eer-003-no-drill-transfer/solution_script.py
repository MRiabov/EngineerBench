from build123d import Align, Box, BuildPart, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def build() -> Compound:
    with BuildPart() as part_1:
        Box(760, 210, 18, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part_1_part = part_1.part.move(Location((0, 0, 9)))
    part_1_part.label = "ballast_base"
    part_1_part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)

    with BuildPart() as part_2:
        Box(240, 120, 40, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_2_part = part_2.part.move(Location((-210, 0, 18)))
    part_2_part.label = "entry_ramp"
    part_2_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as part_3:
        Box(430, 80, 18, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_3_part = part_3.part.move(Location((45, 0, 63)))
    part_3_part.label = "transfer_lane"
    part_3_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as part_4:
        Box(160, 110, 45, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_4_part = part_4.part.move(Location((280, 0, 18)))
    part_4_part.label = "goal_catcher"
    part_4_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    assembly = Compound(
        label="no_drill_transfer_review_seed",
        children=[part_1_part, part_2_part, part_3_part, part_4_part],
    )
    assembly.metadata = CompoundMetadata(fixed=False)
    return assembly
