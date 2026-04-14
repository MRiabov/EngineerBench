from build123d import Compound, Location, Sphere

from shared.enums import ManufacturingMethod
from utils.metadata import CompoundMetadata, PartMetadata
from utils.submission import simulate_engineering, submit_solution_for_review, validate_engineering


def build():
    projectile_ball = Sphere(1.0)
    projectile_ball = projectile_ball.move(Location((8.0, 0.0, 1.0)))
    projectile_ball.label = "projectile_ball"
    projectile_ball.metadata = PartMetadata(
        material_id="abs",
        fixed=False,
        manufacturing_method=ManufacturingMethod.THREE_DP,
    )
    scene = Compound(children=[projectile_ball])
    scene.label = "benchmark_scene"
    scene.metadata = CompoundMetadata(fixed=False)
    return scene


result = build()
validate_ok, validate_message = validate_engineering(result)
print(validate_ok)
print(validate_message)
sim_result = simulate_engineering(result)
print(sim_result.success)
print(sim_result.message)
if validate_ok and sim_result.success:
    print(submit_solution_for_review(result))
