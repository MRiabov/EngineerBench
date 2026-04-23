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
            _make_part("upper_start_ledge", (140.0, 125.0, 24.0), (-40.0, -5.0, 175.0)),
            _make_part("deflector_ramp", (175.0, 85.0, 22.0), (55.0, -8.0, 118.0)),
            _make_part(
                "direct_drop_shield",
                (110.0, 82.0, 70.0),
                (10.0, -2.0, 35.0),
            ),
            _make_part("lower_bin", (120.0, 100.0, 48.0), (280.0, -18.0, 31.0)),
        ]
    )
    environment_fixture.label = "benchmark_environment"
    environment_fixture.metadata = CompoundMetadata()
    return environment_fixture
