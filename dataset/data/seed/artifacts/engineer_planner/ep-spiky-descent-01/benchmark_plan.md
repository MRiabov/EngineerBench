## 1. Learning Objective

Test whether an engineer can carry a `steel_ball` down a stepped descent that
threads around spike-like obstacles and settles into a lower basin without
relying on hidden benchmark motion.

## 2. Environment Geometry

- `upper_start_platform`: elevated release platform centered at `[-280, 0, 174]`
  with size `[180, 150, 28]`.
- `mid_descent_step`: intermediate descent shelf centered at `[-90, 0, 126]`
  with size `[150, 130, 24]`.
- `lower_descent_step`: lower shelf centered at `[95, 0, 72]` with size
  `[150, 130, 22]`.
- `goal_basin`: passive capture basin centered at `[300, 0, 28]` with size
  `[160, 150, 22]`.
- `spike_left`, `spike_center`, `spike_right`: fixed spike-like obstacles
  placed across the descent channel to force a narrow downhill route rather
  than a straight drop.

The route descends from the upper platform toward the lower basin, with the
spike trio interrupting the direct line of travel.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-320, 0, 220]`
- Runtime jitter: `[12, 12, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[272, -78, 12]`, max_mm `[360, 78, 62]`
- `forbid_zones`:
  - `upper_descent_keepout`: min_mm `[-230, -100, 118]`, max_mm
    `[-120, 100, 214]`
  - `spike_field_keepout`: min_mm `[-110, -76, 28]`, max_mm
    `[180, 76, 168]`
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
  undeclared motion to traverse the descent.

## 8. Planner Artifacts

- `todo.md` captures the engineer-planner checklist for the stepped descent.
- `benchmark_definition.yaml` mirrors the declared zones, shelf geometry, and
  cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark
  evidence scene.
- `submit_benchmark_plan()` persists
  `.manifests/benchmark_plan_review_manifest.json`.
