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
            _make_part("upper_start_ledge", (0.14, 0.12, 0.02), (-0.03, 0.0, 0.14)),
            _make_part("deflector_ramp", (0.18, 0.08, 0.02), (0.03, 0.0, 0.10)),
            _make_part(
                "direct_drop_shield",
                (0.08, 0.08, 0.12),
                (0.08, 0.0, 0.12),
            ),
            _make_part("lower_bin", (0.12, 0.10, 0.04), (0.26, 0.0, 0.02)),
        ]
    )
    environment_fixture.label = "benchmark_environment"
    environment_fixture.metadata = CompoundMetadata()
    return environment_fixture
