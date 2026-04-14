from build123d import Align, Box, BuildPart, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def build() -> Compound:
    # Keep the support mass outside the floor-gap keep-out while preserving the
    # approved overall footprint and a visible bridge-like silhouette.
    with BuildPart() as left_support:
        Box(40, 180, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))
    left_support_part = left_support.part.move(Location((-260, 0, 0)))
    left_support_part.label = "base_frame_left_support"
    left_support_part.metadata = PartMetadata(
        material_id="aluminum_6061",
        fixed=True,
    )

    with BuildPart() as right_support:
        Box(40, 180, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))
    right_support_part = right_support.part.move(Location((260, 0, 0)))
    right_support_part.label = "base_frame_right_support"
    right_support_part.metadata = PartMetadata(
        material_id="aluminum_6061",
        fixed=True,
    )

    with BuildPart() as top_bridge:
        Box(60, 40, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))
    top_bridge_part = top_bridge.part.move(Location((0, 0, 60)))
    top_bridge_part.label = "base_frame_top_bridge"
    top_bridge_part.metadata = PartMetadata(
        material_id="aluminum_6061",
        fixed=True,
    )

    base_frame = Compound(
        label="base_frame",
        children=[left_support_part, right_support_part, top_bridge_part],
    )
    base_frame.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)

    with BuildPart() as bridge_deck:
        Box(300, 95, 8, align=(Align.CENTER, Align.CENTER, Align.MIN))
    bridge_deck_part = bridge_deck.part.move(Location((70, 0, 60)))
    bridge_deck_part.label = "bridge_deck"
    bridge_deck_part.metadata = PartMetadata(
        material_id="aluminum_6061",
        fixed=True,
    )

    with BuildPart() as left_fence:
        Box(300, 20, 35, align=(Align.CENTER, Align.CENTER, Align.MIN))
    left_fence_part = left_fence.part.move(Location((70, -47.5, 68)))
    left_fence_part.label = "left_fence"
    left_fence_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as right_fence:
        Box(300, 20, 35, align=(Align.CENTER, Align.CENTER, Align.MIN))
    right_fence_part = right_fence.part.move(Location((70, 47.5, 68)))
    right_fence_part.label = "right_fence"
    right_fence_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as landing_pocket:
        Box(130, 110, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
    landing_pocket_part = landing_pocket.part.move(Location((255, 0, 60)))
    landing_pocket_part.label = "landing_pocket"
    landing_pocket_part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    assembly = Compound(
        label="gap_bridge_review_seed",
        children=[
            base_frame,
            bridge_deck_part,
            left_fence_part,
            right_fence_part,
            landing_pocket_part,
        ],
    )
    assembly.metadata = CompoundMetadata(fixed=False)
    return assembly
