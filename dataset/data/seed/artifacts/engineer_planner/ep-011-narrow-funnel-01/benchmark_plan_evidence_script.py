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
    fixture.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return fixture


def build() -> Compound:
    """Return the benchmark plan evidence geometry for this workspace."""

    fixtures = Compound(
        children=[
            _make_fixture(
                "environment_fixture",
                (480.0, 320.0, 4.0),
                (120.0, 0.0, 2.0),
            ),
        ]
    )
    fixtures.label = "benchmark_environment"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
