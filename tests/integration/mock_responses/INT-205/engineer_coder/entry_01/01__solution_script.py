from build123d import Box

from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod


def build():
    part = Box(1, 1, 1).translate((8, 0, 0.5))
    part.label = "projectile_ball"
    part.metadata = PartMetadata(
        material_id="abs",
        fixed=False,
        manufacturing_method=ManufacturingMethod.THREE_DP,
    )
    return part
