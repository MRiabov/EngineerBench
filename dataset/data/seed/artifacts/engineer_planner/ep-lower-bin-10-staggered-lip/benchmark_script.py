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
            _make_part("upper_start_ledge", (130.0, 115.0, 24.0), (-55.0, 5.0, 170.0)),
            _make_part("deflector_ramp", (170.0, 80.0, 22.0), (35.0, 10.0, 112.0)),
            _make_part(
                "direct_drop_shield",
                (95.0, 68.0, 68.0),
                (8.0, 5.0, 34.0),
            ),
            _make_part("release_lip", (24.0, 110.0, 20.0), (160.0, 5.0, 82.0)),
            _make_part("front_lip", (110.0, 16.0, 30.0), (295.0, 88.0, 35.0)),
            _make_part("lower_bin", (110.0, 90.0, 50.0), (295.0, 25.0, 30.0)),
        ]
    )
    environment_fixture.label = "benchmark_environment"
    environment_fixture.metadata = CompoundMetadata()
    return environment_fixture
