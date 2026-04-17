from build123d import Box

from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod


def build():
    panel = Box(1, 1, 0.2)
    panel.label = "door_panel"
    panel.metadata = PartMetadata(
        material_id="abs",
        is_fixed=False,
        manufacturing_method=ManufacturingMethod.THREE_DP,
    )
    return panel
