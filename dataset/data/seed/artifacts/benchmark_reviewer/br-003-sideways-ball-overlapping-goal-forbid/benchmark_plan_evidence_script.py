from build123d import Align, Box, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def _make_box(label: str, size: tuple[float, float, float], center: tuple[float, float, float]):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center)
    )
    part.label = label
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return part

def build():
    fixtures = Compound(
        children=[
            _make_box("left_start_deck", (28.0, 18.0, 4.0), (-30.0, 0.0, 2.0)),
            _make_box("right_goal_deck", (28.0, 18.0, 4.0), (30.0, 0.0, 2.0)),
            _make_box("bridge_reference_table", (8.0, 8.0, 18.0), (0.0, 0.0, 9.0)),
            _make_box("gap_floor_guard", (18.0, 4.0, 6.0), (0.0, -14.0, 3.0)),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures
