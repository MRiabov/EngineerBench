from build123d import Box

from shared.models.schemas import PartMetadata


def build():
    part = Box(4, 4, 4)
    part.label = "solution_plan_evidence"
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return part
