"""Sideways-ball benchmark implementation.

Implements the approved planner handoff for a benchmark where a 40mm-radius
steel sphere is moved 1m sideways using a lift carriage mechanism.

Inventory (exact match with planner handoff):
- ground_plane x1 (hdpe, fixed)
- floor_plate x1 (aluminum_6061, fixed)
- support_tower x1 (aluminum_6061, fixed)
- raised_goal_shelf x1 (aluminum_6061, fixed)
- lift_carriage x1 (hdpe, slide_z axis)
"""

from __future__ import annotations

from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata


def _build_ground_plane() -> Box:
    """Build the fixed ground plane."""
    part = Box(1400.0, 300.0, 10.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part.label = "ground_plane"
    part.metadata = PartMetadata(material_id="hdpe", fixed=True)
    return part


def _build_floor_plate() -> Box:
    """Build the fixed base floor plate."""
    part = Box(560.0, 180.0, 20.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = part.move(Location((0.0, 0.0, 10.0)))
    part.label = "floor_plate"
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return part


def _build_support_tower() -> Box:
    """Build the fixed vertical support tower."""
    part = Box(80.0, 120.0, 210.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = part.move(Location((0.0, 0.0, 30.0)))
    part.label = "support_tower"
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return part


def _build_raised_goal_shelf() -> Box:
    """Build the fixed raised goal shelf."""
    part = Box(150.0, 120.0, 30.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = part.move(Location((0.0, 0.0, 110.0)))
    part.label = "raised_goal_shelf"
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return part


def _build_lift_carriage() -> Box:
    """Build the moving lift carriage with a single slide_z DOF."""
    part = Box(120.0, 110.0, 18.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part = part.move(Location((0.0, 0.0, 60.0)))
    part.label = "lift_carriage"
    part.metadata = PartMetadata(material_id="hdpe", fixed=False)
    return part


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace.

    Every top-level child must have a unique label that is not
    ``environment``, does not start with ``zone_``, and does not start with
    ``benchmark_payload__`` because the simulator reserves those names.
    """
    # NOTE: Do NOT include the payload here — the simulation system spawns
    # `benchmark_payload__projectile_ball` independently from
    # `benchmark_definition.yaml`. Returning it from build() creates a duplicate
    # body that collides with the spawned ball, causing instant OUT_OF_BOUNDS.
    children = [
        _build_ground_plane(),
        _build_floor_plate(),
        _build_support_tower(),
        _build_raised_goal_shelf(),
        _build_lift_carriage(),
    ]
    environment = Compound(children=children)
    environment.label = "benchmark_environment"
    environment.metadata = CompoundMetadata()
    return environment


result = build()
