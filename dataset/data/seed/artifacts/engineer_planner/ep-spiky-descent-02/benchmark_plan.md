## 1. Learning Objective

Test whether an engineer can carry a `steel_ball` down a stepped descent with
a denser spike field and a tighter basin opening while avoiding hidden
benchmark motion.

## 2. Environment Geometry

- `upper_start_platform`: elevated release platform centered at `[-280, 0, 174]`
  with size `[180, 150, 28]`.
- `mid_descent_step`: intermediate descent shelf centered at `[-90, 0, 126]`
  with size `[150, 130, 24]`.
- `lower_descent_step`: lower shelf centered at `[95, 0, 72]` with size
  `[150, 130, 22]`.
- `goal_basin`: narrower passive capture basin centered at `[300, 0, 26]` with
  size `[150, 138, 20]`.
- `spike_a` through `spike_e`: fixed spike-like obstacles arranged in a tighter
  sequence across the descent channel to compress the downhill route.

The route still descends from the upper platform toward the basin, but the
spike spacing is tighter and the basin mouth is smaller than the baseline
variant.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-322, 0, 220]`
- Runtime jitter: `[12, 12, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[278, -60, 12]`, max_mm `[350, 60, 58]`
- `forbid_zones`:
  - `upper_descent_keepout`: min_mm `[-230, -100, 118]`, max_mm
    `[-120, 100, 214]`
  - `spike_field_keepout`: min_mm `[-140, -82, 28]`, max_mm
    `[190, 82, 174]`
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
  undeclared motion to traverse the tighter descent.

## 8. Planner Artifacts

- `todo.md` captures the engineer-planner checklist for the dense spike field.
- `benchmark_definition.yaml` mirrors the declared zones, shelf geometry, and
  cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark
  evidence scene.
- `submit_benchmark_plan()` persists
  `.manifests/benchmark_plan_review_manifest.json`.
