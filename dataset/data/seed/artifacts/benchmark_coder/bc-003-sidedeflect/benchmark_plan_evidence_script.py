"""Benchmark plan evidence script for the side-deflect ramp benchmark.

This script reconstructs the approved planner inventory as a previewable
build123d scene. Every label and quantity must match the planner handoff exactly:

- base_plate x1 (aluminum_6061, fixed)
- deflector_ramp x1 (aluminum_6061, fixed)
- side_goal_wall x1 (aluminum_6061, fixed)
- catch_bin x1 (hdpe, fixed)
"""

from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata

# Positions from benchmark_definition.yaml and benchmark_plan.md

BASE_PLATE_POS = (0.0, 0.0, 5.0)
BASE_PLATE_SIZE = (300.0, 200.0, 10.0)

DEFLECTOR_RAMP_POS = (40.0, 0.0, 60.0)
DEFLECTOR_RAMP_SIZE = (120.0, 160.0, 15.0)

SIDE_GOAL_WALL_POS = (170.0, 0.0, 50.0)
SIDE_GOAL_WALL_SIZE = (60.0, 80.0, 60.0)

CATCH_BIN_POS = (170.0, 0.0, 12.5)
CATCH_BIN_SIZE = (60.0, 70.0, 5.0)


def build() -> Compound:
    """Return a preview compound matching the approved planner inventory."""
    children: list = []

    # base_plate x1
    bp = Box(*BASE_PLATE_SIZE, align=(Align.CENTER, Align.CENTER, Align.MIN))
    bp = bp.move(Location(BASE_PLATE_POS))
    bp.label = "base_plate"
    bp.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    children.append(bp)

    # deflector_ramp x1
    dr = Box(*DEFLECTOR_RAMP_SIZE, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    dr = dr.move(Location(DEFLECTOR_RAMP_POS))
    dr.label = "deflector_ramp"
    dr.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    children.append(dr)

    # side_goal_wall x1
    sgw = Box(*SIDE_GOAL_WALL_SIZE, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    sgw = sgw.move(Location(SIDE_GOAL_WALL_POS))
    sgw.label = "side_goal_wall"
    sgw.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    children.append(sgw)

    # catch_bin x1
    cb = Box(*CATCH_BIN_SIZE, align=(Align.CENTER, Align.CENTER, Align.MIN))
    cb = cb.move(Location(CATCH_BIN_POS))
    cb.label = "catch_bin"
    cb.metadata = PartMetadata(material_id="hdpe", fixed=True)
    children.append(cb)

    asm = Compound(children=children)
    asm.label = "benchmark_plan_evidence"
    asm.metadata = CompoundMetadata()
    return asm
