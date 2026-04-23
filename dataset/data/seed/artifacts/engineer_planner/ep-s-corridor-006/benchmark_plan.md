# Benchmark Plan

## 1. Learning Objective

Test whether the engineer can route `transfer_cube` through a corridor with a
dead-end spur and a negative-Y goal tray instead of trying to drive a straight
line through blocked space.

## 2. Environment Geometry

- `left_launch_pad`: box centered at `[-230, -120, 15]` with size `[80, 60, 30]`.
- `corridor_block_a`: box centered at `[-90, 80, 40]` with size `[60, 70, 80]`.
- `corridor_block_b`: box centered at `[80, -60, 40]` with size `[60, 70, 80]`.
- `corridor_deadend_block`: box centered at `[170, 145, 40]` with size `[70, 50, 80]`.
- `corridor_block_c`: box centered at `[250, 75, 40]` with size `[60, 70, 80]`.
- `corridor_block_d`: box centered at `[410, -60, 40]` with size `[60, 70, 80]`.
- `corridor_block_e`: box centered at `[570, 80, 40]` with size `[60, 70, 80]`.
- `goal_catch_tray`: box centered at `[650, -120, 15]` with size `[90, 60, 30]`.

The free-space route alternates below `corridor_block_a`, above
`corridor_block_b`, below `corridor_block_c`, above `corridor_block_d`, and
below `corridor_block_e` while ignoring the dead-end spur before entering
`goal_catch_tray`.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization:
  - none; the payload remains a cube for the full run
- Nominal start position: `[-230, -120, 65]`
- Runtime jitter: `[12, 10, 5]` mm

## 4. Objectives

- `goal_zone_mm`:
  - min_mm: `[615, -150, 15]`
  - max_mm: `[685, -90, 70]`
- `forbid_zones`:
  - `corridor_block_a`:
    - min_mm: `[-120, 45, 0]`
    - max_mm: `[-60, 115, 80]`
  - `corridor_block_b`:
    - min_mm: `[50, -95, 0]`
    - max_mm: `[110, -25, 80]`
  - `corridor_deadend_block`:
    - min_mm: `[135, 120, 0]`
    - max_mm: `[205, 170, 80]`
  - `corridor_block_c`:
    - min_mm: `[220, 40, 0]`
    - max_mm: `[280, 110, 80]`
  - `corridor_block_d`:
    - min_mm: `[380, -95, 0]`
    - max_mm: `[440, -25, 80]`
  - `corridor_block_e`:
    - min_mm: `[540, 45, 0]`
    - max_mm: `[600, 115, 80]`
- `build_zone_mm`:
  - min_mm: `[-300, -240, 0]`
  - max_mm: `[695, 240, 260]`

## 5. Simulation Bounds

- min_mm: `[-340, -280, -20]`
- max_mm: `[735, 280, 300]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 72 USD`, `max_weight <= 1300 g`
- The benchmark has no moving fixtures.
- The challenge is the corridor route plus the declared jitter envelope and
  the dead-end spur, not a benchmark-side motor or latch.

## 7. Success Criteria

- Success if the cube reaches `goal_zone_mm` without entering any forbid zone.
- Fail if the cube shortcuts through a blocked leg of the corridor or leaves
  the declared simulation bounds.

## 8. Planner Artifacts

- `todo.md` tracks the engineer-planner work for this corridor family.
- `benchmark_definition.yaml` mirrors the objective zones, payload contract,
  and benchmark caps.
- `benchmark_assembly_definition.yaml` and `benchmark_script.py` capture the
  read-only benchmark geometry that the engineer must not modify.
- `benchmark_plan_evidence_script.py` keeps the corridor geometry legible for
  render review and downstream intake.
