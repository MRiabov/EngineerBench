# Benchmark Plan

## 1. Learning Objective

Test whether the engineer can route `transfer_cube` through a mirrored S
corridor inside a fully walled arena with a long center divider and extra
clutter instead of trying to drive a straight line through blocked space.

## 2. Environment Geometry

- `corridor_floor`: thin base plate centered at `[250, 0, 3]` with size
  `[1120, 560, 6]`.
- `perimeter_wall_north`: long wall centered at `[250, 287, 96]` with size
  `[1120, 14, 180]`.
- `perimeter_wall_south`: long wall centered at `[250, -287, 96]` with size
  `[1120, 14, 180]`.
- `perimeter_wall_west`: side wall centered at `[-314, 0, 96]` with size
  `[14, 560, 180]`.
- `perimeter_wall_east`: side wall centered at `[814, 0, 96]` with size
  `[14, 560, 180]`.
- `left_launch_pad`: box centered at `[-250, 190, 21]` with size
  `[80, 60, 30]`.
- `corridor_block_a`: box centered at `[-170, 120, 91]` with size
  `[80, 130, 170]`.
- `corridor_block_b`: box centered at `[-20, -110, 91]` with size
  `[80, 130, 170]`.
- `corridor_block_c`: box centered at `[130, 120, 91]` with size
  `[80, 130, 170]`.
- `center_divider`: tall divider centered at `[350, 0, 96]` with size
  `[40, 420, 180]`.
- `noise_pillar_a`: square pillar centered at `[40, 0, 66]` with size
  `[42, 42, 120]`.
- `corridor_block_d`: box centered at `[280, -115, 91]` with size
  `[80, 130, 170]`.
- `noise_beam_a`: overhead beam centered at `[350, 0, 220]` with size
  `[220, 30, 24]`.
- `corridor_block_e`: box centered at `[430, 110, 91]` with size
  `[80, 130, 170]`.
- `noise_pillar_b`: square pillar centered at `[610, 0, 66]` with size
  `[42, 42, 120]`.
- `corridor_block_f`: box centered at `[570, -120, 91]` with size
  `[80, 130, 170]`.
- `goal_catch_tray`: box centered at `[760, -190, 21]` with size
  `[90, 60, 30]`.

The free-space route swings from the upper-left launch pad to the lower-right
goal tray, alternating below `corridor_block_a`, above `corridor_block_b`,
below `corridor_block_c`, above `corridor_block_d`, below `corridor_block_e`,
and above `corridor_block_f`, while the center divider and extra clutter force
the route to read as a mirrored maze rather than a simple open channel.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization:
  - none; the payload remains a cube for the full run
- Nominal start position: `[-250, 190, 65]`
- Runtime jitter: `[14, 14, 6]` mm

## 4. Objectives

- `goal_zone_mm`:
  - min_mm: `[725, -220, 15]`
  - max_mm: `[795, -160, 70]`
- `forbid_zones`:
  - `perimeter_wall_north`:
    - min_mm: `[-310, 280, 6]`
    - max_mm: `[810, 294, 186]`
  - `perimeter_wall_south`:
    - min_mm: `[-310, -294, 6]`
    - max_mm: `[810, -280, 186]`
  - `perimeter_wall_west`:
    - min_mm: `[-321, -280, 6]`
    - max_mm: `[-307, 280, 186]`
  - `perimeter_wall_east`:
    - min_mm: `[807, -280, 6]`
    - max_mm: `[821, 280, 186]`
  - `corridor_block_a`:
    - min_mm: `[-210, 55, 0]`
    - max_mm: `[-130, 185, 176]`
  - `corridor_block_b`:
    - min_mm: `[-60, -175, 0]`
    - max_mm: `[20, -45, 176]`
  - `corridor_block_c`:
    - min_mm: `[90, 55, 0]`
    - max_mm: `[170, 185, 176]`
  - `center_divider`:
    - min_mm: `[330, -210, 6]`
    - max_mm: `[370, 210, 186]`
  - `noise_pillar_a`:
    - min_mm: `[19, -21, 6]`
    - max_mm: `[61, 21, 126]`
  - `corridor_block_d`:
    - min_mm: `[240, -180, 0]`
    - max_mm: `[320, -50, 176]`
  - `noise_beam_a`:
    - min_mm: `[240, -15, 208]`
    - max_mm: `[460, 15, 232]`
  - `corridor_block_e`:
    - min_mm: `[390, 45, 0]`
    - max_mm: `[470, 175, 176]`
  - `noise_pillar_b`:
    - min_mm: `[589, -21, 6]`
    - max_mm: `[631, 21, 126]`
  - `corridor_block_f`:
    - min_mm: `[530, -185, 0]`
    - max_mm: `[610, -55, 176]`
- `build_zone_mm`:
  - min_mm: `[-330, -300, 0]`
  - max_mm: `[840, 300, 280]`

## 5. Simulation Bounds

- min_mm: `[-360, -320, -20]`
- max_mm: `[860, 320, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 72 USD`, `max_weight <= 1300 g`
- The benchmark has no moving fixtures.
- The challenge is the mirrored S-shaped route inside a fully walled arena
  plus the long divider, ceiling beam, and scattered clutter pieces.
- The corridor remains a path-planning problem, but the noise makes the arena
  feel much less rectilinear.

## 7. Success Criteria

- Success if the cube reaches `goal_zone_mm` without entering any forbid zone.
- Fail if the cube shortcuts through a blocked leg of the corridor or leaves
  the declared simulation bounds.

## 8. Planner Artifacts

- `todo.md` tracks the engineer-planner work for this corridor family.
- `benchmark_definition.yaml` mirrors the objective zones, payload contract,
  arena walls, divider, and benchmark caps.
- `benchmark_assembly_definition.yaml` and `benchmark_script.py` capture the
  read-only benchmark geometry that the engineer must not modify.
- `benchmark_plan_evidence_script.py` keeps the mirrored maze legible for
  render review and downstream intake.
