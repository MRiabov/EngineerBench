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
                "ballast_base",
                (420.0, 180.0, 30.0),
                (-40.0, 0.0, 15.0),
                "steel_cold_rolled",
            ),
            _make_box(
                "transfer_chute",
                (410.0, 90.0, 80.0),
                (35.0, 0.0, 70.0),
                "hdpe",
            ),
            _make_box(
                "counterweight_fin",
                (90.0, 40.0, 150.0),
                (-170.0, 0.0, 95.0),
                "steel_cold_rolled",
            ),
            _make_box(
                "goal_cradle",
                (110.0, 110.0, 35.0),
                (305.0, 0.0, 30.0),
                "hdpe",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures
