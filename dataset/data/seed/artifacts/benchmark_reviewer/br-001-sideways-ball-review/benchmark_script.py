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
            _make_part("ground_plane", (1.4, 0.3, 0.02), (0.0, 0.0, 0.0)),
            _make_part("platform_left", (0.12, 0.10, 0.08), (-0.5, 0.0, 0.0)),
            _make_part("platform_right", (0.12, 0.10, 0.08), (0.5, 0.0, 0.0)),
            _make_part("guide_rail_lower", (1.0, 0.01, 0.01), (0.0, -0.06, 0.10)),
            _make_part("guide_rail_upper", (1.0, 0.01, 0.01), (0.0, 0.06, 0.10)),
        ]
    )
    environment_fixture.label = "benchmark_environment"
    environment_fixture.metadata = CompoundMetadata()
    return environment_fixture
