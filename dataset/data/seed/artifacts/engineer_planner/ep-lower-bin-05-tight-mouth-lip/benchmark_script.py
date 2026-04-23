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
            _make_part("upper_start_ledge", (145.0, 128.0, 24.0), (-35.0, 5.0, 165.0)),
            _make_part("deflector_ramp", (180.0, 88.0, 22.0), (60.0, 10.0, 112.0)),
            _make_part(
                "direct_drop_shield",
                (95.0, 70.0, 70.0),
                (10.0, -8.0, 35.0),
            ),
            _make_part("lower_bin", (110.0, 90.0, 46.0), (280.0, 18.0, 28.0)),
            _make_part("catch_lip", (120.0, 90.0, 12.0), (280.0, 18.0, 74.0)),
        ]
    )
    environment_fixture.label = "benchmark_environment"
    environment_fixture.metadata = CompoundMetadata()
    return environment_fixture
