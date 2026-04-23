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
            _make_part("upper_start_ledge", (140.0, 120.0, 24.0), (-30.0, 0.0, 170.0)),
            _make_part("deflector_ramp", (185.0, 85.0, 22.0), (55.0, 0.0, 120.0)),
            _make_part(
                "direct_drop_shield",
                (95.0, 70.0, 70.0),
                (12.0, 0.0, 35.0),
            ),
            _make_part("entry_channel_left", (120.0, 10.0, 70.0), (290.0, -55.0, 35.0)),
            _make_part("entry_channel_right", (120.0, 10.0, 70.0), (290.0, 55.0, 35.0)),
            _make_part("lower_bin", (110.0, 90.0, 50.0), (290.0, 0.0, 30.0)),
        ]
    )
    environment_fixture.label = "benchmark_environment"
    environment_fixture.metadata = CompoundMetadata()
    return environment_fixture
