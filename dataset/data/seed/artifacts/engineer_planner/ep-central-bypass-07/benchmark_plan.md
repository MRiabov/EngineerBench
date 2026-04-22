# Benchmark Plan

## 1. Learning Objective

Test whether the engineer can plan around a single central blocker by taking a
clean bypass on the positive-Y side instead of forcing a straight-line route
through the middle.

## 2. Environment Geometry

- `left_start_pad`: box centered at `[-180, 0, 10]` with size `[80, 60, 20]`.
- `central_blocker`: box centered at `[0, 0, 25]` with size `[60, 80, 50]`.
- `right_goal_pad`: box centered at `[180, 80, 10]` with size `[80, 60, 20]`.

The `central_blocker` occupies the middle lane and pushes the route toward the
positive-Y side before the payload can reach `right_goal_pad`.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization: none beyond the declared cube shape
- Nominal start position: `[-210, 0, 50]`
- Runtime jitter: `[8, 8, 5]` mm

## 4. Objectives

- `goal_zone_mm`:
  - min_mm: `[140, 60, 10]`
  - max_mm: `[220, 120, 70]`
- `forbid_zones`:
  - `central_blocker`:
    - min_mm: `[-30, -40, 0]`
    - max_mm: `[30, 40, 50]`
- `build_zone_mm`:
  - min_mm: `[-280, -160, 0]`
  - max_mm: `[320, 200, 180]`

## 5. Simulation Bounds

- min_mm: `[-320, -200, -20]`
- max_mm: `[360, 220, 220]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 72 USD`, `max_weight <= 1300 g`
- The benchmark has no moving fixtures.
- The engineer should preserve the read-only blocker geometry and choose a
  passive bypass strategy on the positive-Y side.

## 7. Success Criteria

- Success if `transfer_cube` reaches `goal_zone_mm` without entering the
  `central_blocker` forbid zone.
- Fail if the payload leaves `simulation_bounds_mm` or if the design assumes
  benchmark-side motion that is not present.

## 8. Planner Artifacts

- `todo.md` carries the engineer-planner checklist for grounding and drafting.
- `benchmark_definition.yaml` mirrors the obstacle, goal shift, and runtime
  jitter contract.
- `benchmark_assembly_definition.yaml` and `benchmark_script.py` preserve the
  benchmark-owned fixture inventory as read-only context.
- `benchmark_plan_evidence_script.py` keeps the benchmark geometry legible for
  downstream intake.
