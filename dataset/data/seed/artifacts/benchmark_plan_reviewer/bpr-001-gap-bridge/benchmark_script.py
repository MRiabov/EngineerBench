"""Gap-bridge benchmark evidence geometry.

This seed only needs to materialize the benchmark-owned static fixtures that
the reviewer stage inspects. The payload is declared separately in
benchmark_definition.yaml and is not spawned from this script.
"""

from __future__ import annotations

from build123d import Align, Box, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def _build_box(
    *,
    label: str,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    material_id: str,
) -> Box:
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part = part.move(Location(center))
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, fixed=True)
    return part


def build() -> Compound:
    """Return the benchmark-owned gap-bridge environment geometry."""

    children = [
        _build_box(
            label="left_start_deck",
            center=(-220.0, 0.0, 35.0),
            size=(180.0, 180.0, 70.0),
            material_id="aluminum_6061",
        ),
        _build_box(
            label="right_goal_deck",
            center=(250.0, 0.0, 35.0),
            size=(200.0, 180.0, 70.0),
            material_id="aluminum_6061",
        ),
        _build_box(
            label="bridge_reference_table",
            center=(70.0, 0.0, 55.0),
            size=(140.0, 120.0, 30.0),
            material_id="hdpe",
        ),
        _build_box(
            label="gap_floor_guard",
            center=(10.0, 0.0, 20.0),
            size=(160.0, 300.0, 40.0),
            material_id="aluminum_6061",
        ),
    ]
    environment = Compound(children=children)
    environment.label = "benchmark_environment"
    environment.metadata = CompoundMetadata()
    return environment


result = build()
