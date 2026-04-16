from __future__ import annotations

from build123d import Align, Box, Compound

from utils.metadata import CompoundMetadata, PartMetadata


def _build_environment_fixture() -> Box:
    """Build the seeded environment fixture declared in benchmark_definition.yaml."""
    part = Box(200.0, 200.0, 20.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part.label = "environment_fixture"
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return part


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

    # Add authored benchmark fixtures to this children list.
    # Every top-level child you add here must have a unique label, and that label
    # must not be `environment`, start with `zone_`, or start with
    # `benchmark_payload__` because the simulator reserves those names for the
    # scene root and generated objective bodies.
    children = [_build_environment_fixture()]
    environment = Compound(children=children)
    environment.label = "benchmark_environment"
    environment.metadata = CompoundMetadata()
    return environment


result = build()
