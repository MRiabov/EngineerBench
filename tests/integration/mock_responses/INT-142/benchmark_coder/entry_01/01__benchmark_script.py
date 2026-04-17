# ruff: noqa
from build123d import *  # noqa: F403, F405

from shared.workers.workbench_models import ManufacturingMethod
from utils.metadata import PartMetadata
from utils.submission import simulate_benchmark, submit_benchmark_for_review, validate_benchmark


def build():
    p = Box(10, 10, 10)
    p.label = "box"
    p.metadata = PartMetadata(
        material_id="abs", is_fixed=True, manufacturing_method=ManufacturingMethod.THREE_DP
    )
    return p


result = build()
validate_ok, validate_message = validate_benchmark(result)
print(validate_ok)
print(validate_message)
sim_result = simulate_benchmark(result)
print(sim_result.success)
print(sim_result.message)
if validate_ok and sim_result.success:
    print(submit_benchmark_for_review(result))
