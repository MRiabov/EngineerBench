from build123d import Align, Box, Compound, Location, Sphere

from shared.enums import ManufacturingMethod
from shared.models.schemas import CompoundMetadata, PartMetadata


def build():
    support = Box(10, 10, 0.5, align=(Align.CENTER, Align.CENTER, Align.MIN))
    support = support.move(Location((7.5, 7.5, 5.0)))
    support.label = "goal_platform"
    support.metadata = PartMetadata(
        material_id="aluminum_6061",
        is_fixed=True,
        manufacturing_method=ManufacturingMethod.THREE_DP,
    )

    projectile_ball = Sphere(1.0)
    projectile_ball = projectile_ball.move(Location((7.5, 7.5, 6.5)))
    projectile_ball.label = "projectile_ball"
    projectile_ball.metadata = PartMetadata(
        material_id="abs",
        is_fixed=False,
        manufacturing_method=ManufacturingMethod.THREE_DP,
    )

    scene = Compound(children=[support, projectile_ball])
    scene.label = "benchmark_scene"
    scene.metadata = CompoundMetadata(is_fixed=False)
    return scene
