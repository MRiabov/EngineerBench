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
                "upper_start_ledge",
                (120.0, 120.0, 24.0),
                (-20.0, 0.0, 220.0),
                "aluminum_6061",
            ),
            _make_box(
                "deflector_ramp",
                (180.0, 100.0, 90.0),
                (110.0, 0.0, 145.0),
                "hdpe",
            ),
            _make_box(
                "direct_drop_shield",
                (120.0, 90.0, 130.0),
                (0.0, 0.0, 65.0),
                "aluminum_6061",
            ),
            _make_box(
                "lower_bin",
                (130.0, 110.0, 60.0),
                (270.0, 0.0, 40.0),
                "hdpe",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures
