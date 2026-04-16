from build123d import (
    Align,
    Box,
    BuildPart,
    Compound,
    Location,
    Sphere,
)

from shared.models.schemas import CompoundMetadata, PartMetadata


def build() -> Compound:
    with BuildPart() as ground:
        Box(1.4, 0.3, 0.02, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ground.part.label = "ground_plane"
    ground.part.metadata = PartMetadata(material_id="hdpe", fixed=True)

    with BuildPart() as left_platform:
        Box(0.12, 0.10, 0.08, align=(Align.CENTER, Align.CENTER, Align.MIN))
    left_platform.part = left_platform.part.move(Location((-0.5, 0.0, 0.0)))
    left_platform.part.label = "platform_left"
    left_platform.part.metadata = PartMetadata(
        material_id="aluminum_6061",
        fixed=True,
    )

    with BuildPart() as right_platform:
        Box(0.12, 0.10, 0.08, align=(Align.CENTER, Align.CENTER, Align.MIN))
    right_platform.part = right_platform.part.move(Location((0.5, 0.0, 0.0)))
    right_platform.part.label = "platform_right"
    right_platform.part.metadata = PartMetadata(
        material_id="aluminum_6061",
        fixed=True,
    )

    with BuildPart() as rail_lower:
        Box(1.0, 0.01, 0.01, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    rail_lower.part = rail_lower.part.move(Location((0.0, -0.06, 0.10)))
    rail_lower.part.label = "guide_rail_lower"
    rail_lower.part.metadata = PartMetadata(material_id="steel_cold_rolled", fixed=True)

    with BuildPart() as rail_upper:
        Box(1.0, 0.01, 0.01, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    rail_upper.part = rail_upper.part.move(Location((0.0, 0.06, 0.10)))
    rail_upper.part.label = "guide_rail_upper"
    rail_upper.part.metadata = PartMetadata(material_id="steel_cold_rolled", fixed=True)

    ball = Sphere(0.04)
    ball.label = "projectile_ball"
    ball.metadata = PartMetadata(material_id="steel_bearing", fixed=False)

    benchmark_compound = Compound(
        label="benchmark_assembly",
        children=[
            ground.part,
            left_platform.part,
            right_platform.part,
            rail_lower.part,
            rail_upper.part,
            ball,
        ],
    )
    benchmark_compound.metadata = CompoundMetadata(fixed=False)
    return benchmark_compound
