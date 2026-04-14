from build123d import Box

from shared.models.schemas import PartMetadata


def build():
    part = Box(6, 6, 2)
    part.label = "environment_fixture"
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return part
