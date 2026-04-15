from __future__ import annotations

from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata


def _make_fixture(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
):
    fixture = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center)
    )
    fixture.label = label
    fixture.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return fixture


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

    # Do NOT include the payload here. The simulator spawns `slider_cube`
    # from `benchmark_definition.yaml`.
    environment_fixture = _make_fixture(
        "environment_fixture",
        (600.0, 120.0, 4.0),
        (0.0, 0.0, 2.0),
    )
    environment = Compound(children=[environment_fixture])
    environment.label = "benchmark_environment"
    environment.metadata = CompoundMetadata()
    return environment


result = build()
