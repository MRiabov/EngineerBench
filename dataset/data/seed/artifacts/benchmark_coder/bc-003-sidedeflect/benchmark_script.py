from __future__ import annotations

from build123d import (
    Align,
    Box,
    Compound,
    Location,
)

from utils.metadata import CompoundMetadata, PartMetadata


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace.

    Benchmark fixtures (all fixed):
    - `base_plate`: 300x200x10 mm floor plate at [0, 0, 5] mm.
    - `deflector_ramp`: 120x160x15 mm ramp tilted 30 degrees, centered at [40, 0, 60] mm.
    - `side_goal_wall`: vertical wall at goal zone near [170, 0, 50] mm.
    - `catch_bin`: goal bin at [170, 0, 15] mm, 60x70x20 mm.
    """
    # NOTE: Do NOT include the payload here -- the simulation system spawns
    # `benchmark_payload__projectile_ball` independently from `benchmark_definition.yaml`.
    # Returning it from build() creates a duplicate body that collides with the spawned ball,
    # causing instant OUT_OF_BOUNDS.
    children = []

    # base_plate: 300x200x10, centered at [0, 0, 5]
    base_plate = Box(
        300.0,
        200.0,
        10.0,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    ).move(Location((0.0, 0.0, 5.0)))
    base_plate.label = "base_plate"
    base_plate.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    children.append(base_plate)

    # deflector_ramp: 120x160x15, tilted 30 degrees about Y axis, centered at [40, 0, 60]
    # The ramp surface must angle downward toward +X so the ball deflects sideways into the goal.
    ramp_width = 120.0  # X dimension
    ramp_depth = 160.0  # Y dimension
    ramp_thick = 15.0  # Z dimension
    ramp_angle_deg = 30.0

    ramp_body = Box(
        ramp_width,
        ramp_depth,
        ramp_thick,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    # Tilt the ramp about the Y axis so the +X edge is lower than the -X edge.
    # Rotation order: (RX, RY, RZ) - we rotate about Y by 30 degrees.
    ramp_body = ramp_body.rotate(
        center=(0.0, 0.0, 0.0),
        rotation=(0.0, ramp_angle_deg, 0.0),
    )
    # Position the ramp center at [40, 0, 60].
    ramp_body = ramp_body.move(Location((40.0, 0.0, 60.0)))
    ramp_body.label = "deflector_ramp"
    ramp_body.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    children.append(ramp_body)

    # side_goal_wall: vertical wall forming the goal bin back wall.
    # Goal zone is [140, -35, 5] to [200, 35, 25], so center is [170, 0, 15].
    # We make a U-shaped wall: back wall + two side walls.
    goal_center_x = 170.0
    goal_center_y = 0.0
    goal_center_z = 15.0
    wall_thick = 8.0
    wall_height = 40.0

    # Back wall: 60x8x40 at [170, -35, wall_height/2]
    back_wall = Box(
        60.0,
        wall_thick,
        wall_height,
        align=(Align.CENTER, Align.CENTER, Align.BOTTOM),
    ).move(
        Location((goal_center_x, goal_center_y - 35.0 + wall_thick / 2, goal_center_z))
    )
    back_wall.label = "side_goal_wall_back"
    back_wall.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    children.append(back_wall)

    # Left wall: 8x70x40
    left_wall = Box(
        wall_thick,
        70.0,
        wall_height,
        align=(Align.CENTER, Align.CENTER, Align.BOTTOM),
    ).move(
        Location((goal_center_x - 30.0 + wall_thick / 2, goal_center_y, goal_center_z))
    )
    left_wall.label = "side_goal_wall_left"
    left_wall.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    children.append(left_wall)

    # Right wall: 8x70x40
    right_wall = Box(
        wall_thick,
        70.0,
        wall_height,
        align=(Align.CENTER, Align.CENTER, Align.BOTTOM),
    ).move(
        Location((goal_center_x + 30.0 - wall_thick / 2, goal_center_y, goal_center_z))
    )
    right_wall.label = "side_goal_wall_right"
    right_wall.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    children.append(right_wall)

    # catch_bin: floor of the goal bin, 60x70x5 at [170, 0, 5]
    catch_bin = Box(
        60.0,
        70.0,
        5.0,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    ).move(Location((goal_center_x, goal_center_y, 5.0)))
    catch_bin.label = "catch_bin"
    catch_bin.metadata = PartMetadata(material_id="hdpe", fixed=True)
    children.append(catch_bin)

    environment = Compound(children=children)
    environment.label = "benchmark_environment"
    environment.metadata = CompoundMetadata()
    return environment


result = build()
