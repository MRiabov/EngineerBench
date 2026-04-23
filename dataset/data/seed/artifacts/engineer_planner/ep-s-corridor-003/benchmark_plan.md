# Benchmark Plan

## 1. Learning Objective

Test whether the engineer can route `transfer_cube` through a corridor with a
pinch point and a dead-end spur instead of trying to drive a straight line
through blocked space.

## 2. Environment Geometry

- `left_launch_pad`: box centered at `[-220, -95, 15]` with size `[80, 60, 30]`.
- `corridor_block_a`: box centered at `[-50, 70, 40]` with size `[60, 90, 80]`.
- `corridor_block_b`: box centered at `[150, -45, 40]` with size `[50, 110, 80]`.
- `corridor_deadend_block`: box centered at `[250, -155, 40]` with size `[70, 50, 80]`.
- `corridor_block_c`: box centered at `[340, 80, 40]` with size `[60, 90, 80]`.
- `goal_catch_tray`: box centered at `[560, 35, 15]` with size `[80, 60, 30]`.

The free-space route alternates below `corridor_block_a`, above
`corridor_block_b`, and below `corridor_block_c` while ignoring the
dead-end spur before entering `goal_catch_tray`.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization:
  - none; the payload remains a cube for the full run
- Nominal start position: `[-220, -95, 188]`
- Runtime jitter: `[10, 14, 5]` mm

## 4. Objectives

- `goal_zone_mm`:
  - min_mm: `[525, 5, 15]`
  - max_mm: `[595, 65, 70]`
- `forbid_zones`:
  - `corridor_block_a`:
    - min_mm: `[-80, 25, 0]`
    - max_mm: `[-20, 115, 80]`
  - `corridor_block_b`:
    - min_mm: `[125, -100, 0]`
    - max_mm: `[175, 10, 80]`
  - `corridor_block_c`:
    - min_mm: `[310, 35, 0]`
    - max_mm: `[370, 125, 80]`
  - `corridor_deadend_block`:
    - min_mm: `[215, -180, 0]`
    - max_mm: `[285, -130, 80]`
- `build_zone_mm`:
  - min_mm: `[-300, -220, 0]`
  - max_mm: `[640, 220, 260]`

## 5. Simulation Bounds

- min_mm: `[-340, -260, -20]`
- max_mm: `[700, 260, 300]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 72 USD`, `max_weight <= 1300 g`
- The benchmark has no moving fixtures.
- The challenge is the S-shaped free-space route plus the declared jitter
  envelope and the dead-end spur, not a benchmark-side motor or latch.

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
