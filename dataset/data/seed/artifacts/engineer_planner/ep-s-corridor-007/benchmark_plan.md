# Benchmark Plan

## 1. Learning Objective

Test whether the engineer can route `transfer_cube` through a tall, floor-bound
S corridor that climbs from the lower-left start pad to the upper-right goal
tray instead of trying to drive a straight line through blocked space.

## 2. Environment Geometry

- `corridor_floor`: thin base plate centered at `[250, 0, 3]` with size
  `[1040, 520, 6]`.
- `left_launch_pad`: box centered at `[-250, -190, 21]` with size
  `[80, 60, 30]`.
- `corridor_block_a`: box centered at `[-150, -120, 91]` with size
  `[80, 130, 170]`.
- `corridor_block_b`: box centered at `[-20, 110, 91]` with size
  `[80, 130, 170]`.
- `corridor_block_c`: box centered at `[120, -110, 91]` with size
  `[80, 130, 170]`.
- `corridor_block_d`: box centered at `[260, 115, 91]` with size
  `[80, 130, 170]`.
- `corridor_block_e`: box centered at `[400, -105, 91]` with size
  `[80, 130, 170]`.
- `corridor_block_f`: box centered at `[540, 120, 91]` with size
  `[80, 130, 170]`.
- `corridor_block_g`: box centered at `[680, -100, 91]` with size
  `[80, 130, 170]`.
- `goal_catch_tray`: box centered at `[760, 160, 21]` with size
  `[90, 60, 30]`.

The free-space route swings from the lower-left launch pad to the upper-right
goal tray, alternating below `corridor_block_a`, above `corridor_block_b`,
below `corridor_block_c`, above `corridor_block_d`, below `corridor_block_e`,
above `corridor_block_f`, and below `corridor_block_g` before climbing into
`goal_catch_tray`.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization:
  - none; the payload remains a cube for the full run
- Nominal start position: `[-250, -190, 250]`
- Runtime jitter: `[14, 14, 6]` mm

## 4. Objectives

- `goal_zone_mm`:
  - min_mm: `[725, 130, 15]`
  - max_mm: `[795, 190, 70]`
- `forbid_zones`:
  - `corridor_block_a`:
    - min_mm: `[-190, -185, 0]`
    - max_mm: `[-110, -55, 176]`
  - `corridor_block_b`:
    - min_mm: `[-60, 45, 0]`
    - max_mm: `[20, 175, 176]`
  - `corridor_block_c`:
    - min_mm: `[80, -175, 0]`
    - max_mm: `[160, -45, 176]`
  - `corridor_block_d`:
    - min_mm: `[220, 50, 0]`
    - max_mm: `[300, 180, 176]`
  - `corridor_block_e`:
    - min_mm: `[360, -170, 0]`
    - max_mm: `[440, -40, 176]`
  - `corridor_block_f`:
    - min_mm: `[500, 55, 0]`
    - max_mm: `[580, 185, 176]`
  - `corridor_block_g`:
    - min_mm: `[640, -165, 0]`
    - max_mm: `[720, -35, 176]`
- `build_zone_mm`:
  - min_mm: `[-320, -260, 0]`
  - max_mm: `[820, 260, 280]`

## 5. Simulation Bounds

- min_mm: `[-360, -300, -20]`
- max_mm: `[860, 300, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 72 USD`, `max_weight <= 1300 g`
- The benchmark has no moving fixtures.
- The challenge is the tall S-shaped free-space route, the full-width floor
  plate, and the declared jitter envelope, not a benchmark-side motor or
  latch.
- The blocker geometry uses chamfered crowns and softened vertical edges so the
  corridor reads like a machined S rather than a stack of plain boxes.

## 7. Success Criteria

- Success if the cube reaches `goal_zone_mm` without entering any forbid zone.
- Fail if the cube shortcuts through a blocked leg of the corridor or leaves
  the declared simulation bounds.

## 8. Planner Artifacts

- `todo.md` tracks the engineer-planner work for this corridor family.
- `benchmark_definition.yaml` mirrors the objective zones, payload contract,
  floor plate, and benchmark caps.
- `benchmark_assembly_definition.yaml` and `benchmark_script.py` capture the
  read-only benchmark geometry that the engineer must not modify.
- `benchmark_plan_evidence_script.py` keeps the tall S corridor legible for
  render review and downstream intake.
