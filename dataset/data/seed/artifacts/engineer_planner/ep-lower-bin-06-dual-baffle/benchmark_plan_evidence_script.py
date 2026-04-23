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
            _make_part("upper_start_ledge", (140.0, 125.0, 24.0), (-45.0, -5.0, 180.0)),
            _make_part("deflector_ramp", (185.0, 85.0, 22.0), (55.0, -5.0, 125.0)),
            _make_part(
                "direct_drop_shield",
                (100.0, 80.0, 70.0),
                (15.0, -20.0, 35.0),
            ),
            _make_part("midway_baffle_left", (30.0, 60.0, 70.0), (165.0, -60.0, 35.0)),
            _make_part("midway_baffle_right", (30.0, 60.0, 70.0), (165.0, 20.0, 35.0)),
            _make_part("lower_bin", (125.0, 105.0, 48.0), (290.0, -25.0, 32.0)),
        ]
    )
    environment_fixture.label = "benchmark_environment"
    environment_fixture.metadata = CompoundMetadata()
    return environment_fixture
