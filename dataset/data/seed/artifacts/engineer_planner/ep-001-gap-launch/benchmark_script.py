from __future__ import annotations

from build123d import Align, Box, Compound

from utils.metadata import CompoundMetadata, PartMetadata


def _environment_fixture():
    fixture = Box(
        320.0,
        180.0,
        24.0,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    fixture.label = "environment_fixture"
    fixture.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return fixture


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

    environment = Compound(children=[_environment_fixture()])
    environment.label = "benchmark_environment"
    environment.metadata = CompoundMetadata()
    return environment


result = build()
