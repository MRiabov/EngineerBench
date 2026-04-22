# Benchmark Plan

## 1. Learning Objective

Test whether the engineer can route `transfer_cube` through a bent corridor
formed by offset benchmark obstacles instead of trying to drive a straight line
through blocked space.

## 2. Environment Geometry

- `left_launch_pad`: box centered at `[-220, -110, 15]` with size `[80, 60, 30]`.
- `corridor_block_a`: box centered at `[-20, 60, 40]` with size `[60, 80, 80]`.
- `corridor_block_b`: box centered at `[190, -60, 40]` with size `[60, 80, 80]`.
- `corridor_block_c`: box centered at `[400, 60, 40]` with size `[60, 80, 80]`.
- `goal_catch_tray`: box centered at `[560, -110, 15]` with size `[80, 60, 30]`.

The free-space route alternates below `corridor_block_a`, above
`corridor_block_b`, and below `corridor_block_c` before entering
`goal_catch_tray`.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization:
  - none; the payload remains a cube for the full run
- Nominal start position: `[-220, -110, 65]`
- Runtime jitter: `[10, 10, 5]` mm

## 4. Objectives

- `goal_zone_mm`:
  - min_mm: `[530, -140, 15]`
  - max_mm: `[590, -80, 70]`
- `forbid_zones`:
  - `corridor_block_a`:
    - min_mm: `[-50, 20, 0]`
    - max_mm: `[10, 100, 80]`
  - `corridor_block_b`:
    - min_mm: `[160, -100, 0]`
    - max_mm: `[220, -20, 80]`
  - `corridor_block_c`:
    - min_mm: `[370, 20, 0]`
    - max_mm: `[430, 100, 80]`
- `build_zone_mm`:
  - min_mm: `[-320, -220, 0]`
  - max_mm: `[660, 220, 260]`

## 5. Simulation Bounds

- min_mm: `[-360, -260, -20]`
- max_mm: `[700, 260, 300]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 72 USD`, `max_weight <= 1300 g`
- The benchmark has no moving fixtures.
- The challenge is the S-shaped free-space route plus the declared jitter
  envelope, not a benchmark-side motor or latch.

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
