# ruff: noqa
from build123d import *  # noqa: F403, F405

from shared.models.schemas import CompoundMetadata, PartMetadata
from shared.workers.workbench_models import ManufacturingMethod
from utils.submission import simulate_engineering, submit_solution_for_review, validate_engineering


def build():
    p = Box(0.2, 0.2, 0.2)
    p = p.moved(Location((6, 6, 6)))
    p.label = "obj"
    p.metadata = PartMetadata(
        material_id="abs",
        is_fixed=True,
        manufacturing_method=ManufacturingMethod.THREE_DP,
    )
    scene = Compound(children=[p])
    scene.label = "obj_scene"
    scene.metadata = CompoundMetadata(is_fixed=False)
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
