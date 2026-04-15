from __future__ import annotations

from build123d import Compound

from utils.metadata import CompoundMetadata


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace.

    The payload (moved_object) is spawned by the simulator from
    benchmark_definition.yaml and is not returned from build().
    """
    environment = Compound(children=[])
    environment.label = "benchmark_environment"
    environment.metadata = CompoundMetadata()
    return environment


result = build()
