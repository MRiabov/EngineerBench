from build123d import Align, Box, BuildPart, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def build() -> Compound:
    with BuildPart() as part_1:
        Box(720, 180, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_1_part = part_1.part.move(Location((0, 0, 0)))
    part_1_part.label = "base_plate"
    part_1_part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)

    with BuildPart() as part_2:
        Box(300, 20, 45, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_2_part = part_2.part.move(Location((-150, 62, 10)))
    part_2_part.label = "outer_guide_left"
    part_2_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as part_3:
        Box(300, 20, 45, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_3_part = part_3.part.move(Location((150, -62, 10)))
    part_3_part.label = "outer_guide_right"
    part_3_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as part_4:
        Box(150, 130, 35, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part_4_part = part_4.part.move(Location((380, -18, 10)))
    part_4_part.label = "goal_cradle"
    part_4_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    assembly = Compound(
        label="central_forbid_route_review_seed",
        children=[part_1_part, part_2_part, part_3_part, part_4_part],
    )
    assembly.metadata = CompoundMetadata(fixed=False)
    return assembly
