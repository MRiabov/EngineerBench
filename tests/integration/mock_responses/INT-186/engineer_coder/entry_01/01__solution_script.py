from build123d import Box

from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod


def build():
    part = Box(0.2, 0.2, 0.2)
    part.label = "obj"
    part.metadata = PartMetadata(
        material_id="abs",
        is_fixed=False,
        manufacturing_method=ManufacturingMethod.THREE_DP,
    )
    return part
