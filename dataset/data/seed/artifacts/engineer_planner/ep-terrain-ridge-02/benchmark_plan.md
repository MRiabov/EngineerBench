## 1. Learning Objective

Test whether an engineer can carry a 25 mm-radius steel ball over a
flat-topped step ridge without relying on hidden benchmark motion or a
frictionless flat push.

## 2. Environment Geometry

- `terrain_base`: flat route slab centered at `[0, 0, 6]` with size
  `[720, 180, 12]`.
- `terrain_ridge`: flat-topped step centered at `[0, 0, 19]` with size
  `[150, 180, 14]`; this is the benchmark-side terrain discontinuity, not an
  actuator.
- `goal_catch_tray`: passive capture tray centered at `[330, 0, 24]` with size
  `[160, 180, 12]`.

The route runs from left to right across the slab, and the ridge sits midway
between the start and goal zones.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-350, 0, 164]`
- Runtime jitter: `[12, 12, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[320, -90, 25]`, max_mm `[390, 90, 90]`
- `forbid_zones`:
  - `ridge_keepout`: min_mm `[-80, -130, 12]`, max_mm `[80, 130, 34]`
- `build_zone_mm`: min_mm `[-420, -160, 0]`, max_mm `[420, 160, 220]`

## 5. Simulation Bounds

- min_mm `[-460, -200, -20]`, max_mm `[460, 200, 260]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- All benchmark-owned geometry is static; the benchmark should not imply any
  hidden powered cradle, moving ridge, or actuator.

## 7. Success Criteria

- Success if the ball ends inside `goal_zone_mm` without entering
  `ridge_keepout`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark requires
  undeclared motion to cross the step ridge.

## 8. Planner Artifacts

- `todo.md` captures the engineer-planner checklist for the ridge-crossing
  guide solution.
- `benchmark_definition.yaml` mirrors the declared zones, ridge geometry, and
  cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured
  parts and confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark
  evidence scene.
- `submit_benchmark_plan()` persists
  `.manifests/benchmark_plan_review_manifest.json`.
