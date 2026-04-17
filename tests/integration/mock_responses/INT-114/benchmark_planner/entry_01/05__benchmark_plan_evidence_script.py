from build123d import Box, Location

from shared.models.schemas import PartMetadata


def build():
    part = Box(16, 8, 4).move(Location((-20.0, 0.0, 2.0)))
    part.label = "environment_fixture"
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return part
