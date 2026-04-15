from build123d import Align, Box, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def _make_box(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center)
    )
    part.label = label
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return part


def build():
    fixtures = Compound(
        children=[
            _make_box("fixture_box", (10.0, 10.0, 10.0), (0.0, 0.0, 5.0)),
        ]
    )
    fixtures.label = "solution_assembly"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
