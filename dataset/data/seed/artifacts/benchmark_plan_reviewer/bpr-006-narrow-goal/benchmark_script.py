from build123d import Align, Box, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def _make_box(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    material_id: str,
):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center)
    )
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, is_fixed=True)
    return part


def build():
    fixtures = Compound(
        children=[
            _make_box(
                "capture_bowl",
                (260.0, 180.0, 80.0),
                (120.0, 0.0, 120.0),
                "hdpe",
            ),
            _make_box(
                "throat_left",
                (180.0, 12.0, 70.0),
                (420.0, 22.0, 35.0),
                "aluminum_6061",
            ),
            _make_box(
                "throat_right",
                (180.0, 12.0, 70.0),
                (420.0, -22.0, 35.0),
                "aluminum_6061",
            ),
            _make_box(
                "goal_sleeve",
                (36.0, 36.0, 70.0),
                (515.0, 0.0, 35.0),
                "hdpe",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures
