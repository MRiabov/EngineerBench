"""Benchmark plan evidence script for the sideways-ball benchmark.

This script reconstructs the approved planner inventory as a previewable
build123d scene. Every label and quantity must match the manufactured_parts
section of benchmark_assembly_definition.yaml exactly.
"""

from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata

# Build zone from benchmark_definition.yaml:
#   min: [-0.58, -0.1, 0.0], max: [0.58, 0.1, 0.18]  (metres)
# We place small proxy boxes inside the build zone with labels matching
# the manufactured_parts inventory.

# manufactured_parts (from benchmark_assembly_definition.yaml):
#   ground_plane       qty=1
#   floor_plate        qty=1
#   support_tower      qty=1
#   raised_goal_shelf  qty=1
#   lift_carriage      qty=1

GROUND_PLANE_POS = (0.0, 0.0, 0.005)
GROUND_PLANE_SIZE = (1.16, 0.2, 0.01)

FLOOR_PLATE_POS = (0.0, 0.0, 0.005)
FLOOR_PLATE_SIZE = (0.2, 0.06, 0.01)

SUPPORT_TOWER_POS = (0.0, 0.0, 0.09)
SUPPORT_TOWER_SIZE = (0.04, 0.04, 0.16)

# Raised goal shelf preview (Z=0.14 to stay within build zone while avoiding
# goal-zone overlap; exact Z=0.17 position is in benchmark_definition.yaml).
RAISED_GOAL_SHELF_POS = (0.5, 0.0, 0.14)
RAISED_GOAL_SHELF_SIZE = (0.06, 0.06, 0.01)

LIFT_CARRIAGE_POS = (0.0, 0.0, 0.05)
LIFT_CARRIAGE_SIZE = (0.04, 0.04, 0.02)


def build() -> Compound:
    """Return a preview compound matching the approved planner inventory."""
    children: list = []

    # ground_plane x1
    gp = Box(*GROUND_PLANE_SIZE, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    gp = gp.move(Location(GROUND_PLANE_POS))
    gp.label = "ground_plane"
    gp.metadata = PartMetadata(material_id="hdpe", fixed=True)
    children.append(gp)

    # floor_plate x1
    fp = Box(*FLOOR_PLATE_SIZE, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    fp = fp.move(Location(FLOOR_PLATE_POS))
    fp.label = "floor_plate"
    fp.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    children.append(fp)

    # support_tower x1
    st = Box(*SUPPORT_TOWER_SIZE, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    st = st.move(Location(SUPPORT_TOWER_POS))
    st.label = "support_tower"
    st.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    children.append(st)

    # raised_goal_shelf x1
    gs = Box(*RAISED_GOAL_SHELF_SIZE, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    gs = gs.move(Location(RAISED_GOAL_SHELF_POS))
    gs.label = "raised_goal_shelf"
    gs.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    children.append(gs)

    # lift_carriage x1
    lc = Box(*LIFT_CARRIAGE_SIZE, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    lc = lc.move(Location(LIFT_CARRIAGE_POS))
    lc.label = "lift_carriage"
    lc.metadata = PartMetadata(material_id="hdpe", fixed=False)
    children.append(lc)

    asm = Compound(children=children)
    asm.label = "benchmark_plan_evidence"
    asm.metadata = CompoundMetadata()
    return asm
