## 1. Learning Objective

Test whether an engineer can carry a `steel_ball` down a longer stepped
descent with a wider basin mouth and a five-spike staggered field while
staying within the benchmark motion contract.

## 2. Environment Geometry

- `upper_start_platform`: elevated release platform centered at `[-292, -10, 186]`
  with size `[176, 150, 28]`.
- `mid_descent_step`: intermediate shelf centered at `[-120, 0, 138]` with
  size `[150, 124, 24]`.
- `lower_descent_step`: lower shelf centered at `[40, 12, 84]` with size
  `[146, 118, 22]`.
- `goal_basin`: wider passive capture basin centered at `[160, 26, 24]` with
  size `[172, 140, 18]`.
- `spike_a` through `spike_e`: fixed spike-like obstacles spread across both
  sides of the route to make the downhill path read as a staggered field.

The route still descends from the upper platform into the basin, but the basin
is wider and the spike field uses five distinct placements rather than a short
three-spike diagonal.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-334, -10, 231]`
- Runtime jitter: `[12, 12, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[142, 0, 0]`, max_mm `[178, 52, 50]`
- `forbid_zones`:
  - `upper_descent_keepout`: min_mm `[-228, -96, 118]`, max_mm
    `[-108, 96, 214]`
  - `spike_field_keepout`: min_mm `[-220, -130, 24]`, max_mm
    `[140, 110, 166]`
- `build_zone_mm`: min_mm `[-420, -180, 0]`, max_mm `[420, 180, 260]`

## 5. Simulation Bounds

- min_mm `[-460, -200, -20]`, max_mm `[460, 200, 280]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- All benchmark-owned geometry is static; the benchmark should not imply any
  hidden actuator, moving spike, or powered descent assist.

## 7. Success Criteria

- Success if the ball ends inside `goal_zone_mm` without entering
  `spike_field_keepout`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark requires
  undeclared motion to traverse the wider descent.

## 8. Planner Artifacts

- `todo.md` captures the engineer-planner checklist for the wide basin and
  five-spike field.
- `benchmark_definition.yaml` mirrors the declared zones, shelf geometry, and
  cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark
  evidence scene.
- `submit_benchmark_plan()` persists
  `.manifests/benchmark_plan_review_manifest.json`.
