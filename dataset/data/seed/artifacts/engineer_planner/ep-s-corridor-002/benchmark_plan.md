# Benchmark Plan

## 1. Learning Objective

Test whether the engineer can route `transfer_cube` through a longer
four-turn corridor formed by offset benchmark obstacles instead of trying to
drive a straight line through blocked space.

## 2. Environment Geometry

- `left_launch_pad`: box centered at `[-240, -130, 15]` with size `[80, 60, 30]`.
- `corridor_block_a`: box centered at `[-70, 85, 40]` with size `[70, 70, 80]`.
- `corridor_block_b`: box centered at `[120, -60, 40]` with size `[70, 90, 80]`.
- `corridor_block_c`: box centered at `[320, 90, 40]` with size `[70, 70, 80]`.
- `corridor_block_d`: box centered at `[500, -50, 40]` with size `[70, 70, 80]`.
- `goal_catch_tray`: box centered at `[650, -120, 15]` with size `[90, 60, 30]`.

The free-space route alternates below `corridor_block_a`, above
`corridor_block_b`, below `corridor_block_c`, and above `corridor_block_d`
before entering `goal_catch_tray`.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization:
  - none; the payload remains a cube for the full run
- Nominal start position: `[-240, -130, 65]`
- Runtime jitter: `[12, 12, 5]` mm

## 4. Objectives

- `goal_zone_mm`:
  - min_mm: `[610, -150, 15]`
  - max_mm: `[690, -90, 70]`
- `forbid_zones`:
  - `corridor_block_a`:
    - min_mm: `[-105, 50, 0]`
    - max_mm: `[-35, 120, 80]`
  - `corridor_block_b`:
    - min_mm: `[85, -105, 0]`
    - max_mm: `[155, -15, 80]`
  - `corridor_block_c`:
    - min_mm: `[285, 55, 0]`
    - max_mm: `[355, 125, 80]`
  - `corridor_block_d`:
    - min_mm: `[465, -85, 0]`
    - max_mm: `[535, -15, 80]`
- `build_zone_mm`:
  - min_mm: `[-320, -240, 0]`
  - max_mm: `[720, 240, 260]`

## 5. Simulation Bounds

- min_mm: `[-360, -280, -20]`
- max_mm: `[760, 280, 300]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 72 USD`, `max_weight <= 1300 g`
- The benchmark has no moving fixtures.
- The challenge is the longer S-shaped free-space route plus the declared
  jitter envelope, not a benchmark-side motor or latch.

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
