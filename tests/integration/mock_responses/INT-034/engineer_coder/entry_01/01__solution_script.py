from build123d import Box, Compound
from shared.models.schemas import CompoundMetadata


def build():
    fixture = Box(10, 10, 10)
    fixture.label = "review_fixture"
    assembly = Compound(children=[fixture], label="review_fixture")
    assembly.metadata = CompoundMetadata()
    return assembly
