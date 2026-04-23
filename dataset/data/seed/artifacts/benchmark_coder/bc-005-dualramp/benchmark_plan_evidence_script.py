"""Benchmark plan evidence script for the dual-ramp benchmark.

This script reconstructs the approved planner inventory as a previewable
build123d scene. Every label and quantity must match the planner handoff exactly:

- base_plate x1 (aluminum_6061, fixed)
- primary_ramp x1 (aluminum_6061, fixed)
- secondary_ramp x1 (aluminum_6061, fixed)
- splitter_wall x1 (aluminum_6061, fixed)
- goal_wall x1 (aluminum_6061, fixed)
- catch_bin x1 (hdpe, fixed)
"""

from build123d import Align, Box, Compound, Location, Rotation

from utils.metadata import CompoundMetadata, PartMetadata

# Positions from benchmark_definition.yaml and benchmark_plan.md

BASE_PLATE_POS = (0.0, 0.0, 5.0)
BASE_PLATE_SIZE = (340.0, 240.0, 10.0)

PRIMARY_RAMP_POS = (30.0, -18.0, 60.0)
PRIMARY_RAMP_SIZE = (120.0, 150.0, 15.0)

SECONDARY_RAMP_POS = (118.0, 34.0, 38.0)
SECONDARY_RAMP_SIZE = (110.0, 130.0, 12.0)

SPLITTER_WALL_POS = (68.0, 0.0, 34.0)
SPLITTER_WALL_SIZE = (12.0, 120.0, 70.0)

GOAL_WALL_POS = (220.0, 85.0, 52.0)
GOAL_WALL_SIZE = (60.0, 50.0, 60.0)

CATCH_BIN_POS = (220.0, 80.0, 16.5)
CATCH_BIN_SIZE = (60.0, 50.0, 23.0)


def build() -> Compound:
    """Return a preview compound matching the approved planner inventory."""
    children: list = []

    # base_plate x1
    bp = Box(*BASE_PLATE_SIZE, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    bp = bp.move(Location(BASE_PLATE_POS))
    bp.label = "base_plate"
    bp.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    children.append(bp)

    # primary_ramp x1
    pr = Rotation(0.0, 26.0, -12.0) * Box(
        *PRIMARY_RAMP_SIZE,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    pr = pr.move(Location(PRIMARY_RAMP_POS))
    pr.label = "primary_ramp"
    pr.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    children.append(pr)

    # secondary_ramp x1
    sr = Rotation(0.0, -18.0, 18.0) * Box(
        *SECONDARY_RAMP_SIZE,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    sr = sr.move(Location(SECONDARY_RAMP_POS))
    sr.label = "secondary_ramp"
    sr.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    children.append(sr)

    # splitter_wall x1
    sw = Box(*SPLITTER_WALL_SIZE, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    sw = sw.move(Location(SPLITTER_WALL_POS))
    sw.label = "splitter_wall"
    sw.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    children.append(sw)

    # goal_wall x1
    gw = Box(*GOAL_WALL_SIZE, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    gw = gw.move(Location(GOAL_WALL_POS))
    gw.label = "goal_wall"
    gw.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    children.append(gw)

    # catch_bin x1
    cb = Box(*CATCH_BIN_SIZE, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    cb = cb.move(Location(CATCH_BIN_POS))
    cb.label = "catch_bin"
    cb.metadata = PartMetadata(material_id="hdpe", is_fixed=True)
    children.append(cb)

    asm = Compound(children=children)
    asm.label = "benchmark_plan_evidence"
    asm.metadata = CompoundMetadata()
    return asm
