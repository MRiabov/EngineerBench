from build123d import Align, Box, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def _make_part(
    label: str, size: tuple[float, float, float], center: tuple[float, float, float]
):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center)
    )
    part.label = label
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return part


def build() -> Compound:
    environment_fixture = Compound(
        children=[
            _make_part("upper_start_ledge", (145.0, 130.0, 24.0), (-35.0, 8.0, 170.0)),
            _make_part("deflector_ramp", (180.0, 90.0, 22.0), (70.0, 18.0, 115.0)),
            _make_part(
                "direct_drop_shield",
                (105.0, 86.0, 70.0),
                (18.0, 6.0, 35.0),
            ),
            _make_part("lower_bin", (130.0, 110.0, 50.0), (285.0, 35.0, 30.0)),
        ]
    )
    environment_fixture.label = "benchmark_environment"
    environment_fixture.metadata = CompoundMetadata()
    return environment_fixture
