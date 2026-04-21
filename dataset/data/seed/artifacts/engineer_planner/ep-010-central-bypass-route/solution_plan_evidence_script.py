from build123d import Location, Box

from utils.metadata import PartMetadata


def build():
    part = Box(4, 4, 4).move(Location((-30.0, 0.0, 24.0)))
    part.label = "solution_plan_evidence"
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return part
