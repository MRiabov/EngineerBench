from __future__ import annotations

from build123d import Compound

from utils.metadata import CompoundMetadata


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

    # Do NOT include the payload here. The simulator spawns
    # `benchmark_payload__slider_cube` from `benchmark_definition.yaml`.
    environment = Compound(children=[])
    environment.label = "benchmark_environment"
    environment.metadata = CompoundMetadata()
    return environment


result = build()
