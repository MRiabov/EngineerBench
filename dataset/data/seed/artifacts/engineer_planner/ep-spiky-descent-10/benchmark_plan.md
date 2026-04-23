## 1. Learning Objective

Test whether an engineer can carry a `steel_ball` down a patterned spiky
descent where the route narrows in X, the obstacle field alternates in depth,
and the basin is slightly shallower than the earlier layered variants.

## 2. Environment Geometry

- `upper_start_platform`: elevated launch platform centered at `[-304, -20, 202]`
  with size `[182, 150, 30]`.
- `upper_mid_step`: intermediate shelf centered at `[-146, -14, 152]` with
  size `[158, 126, 24]`.
- `lower_mid_step`: lower shelf centered at `[20, -8, 96]` with size
  `[148, 120, 22]`.
- `goal_basin`: shallower capture basin centered at `[154, 12, 18]` with size
  `[146, 124, 18]`.
- `spike_row_left_1`, `spike_row_right_1`, `spike_row_left_2`,
  `spike_row_right_2`, `spike_row_left_3`, `spike_row_right_3`, and `spike_tail`:
  fixed spike-like obstacles arranged into a seven-spike patterned field with
  alternating side-lane offsets.

The route still descends through the same three-step principle, but the spike
field now reads as a repeating pattern rather than a single diagonal band.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-334, -24, 251]`
- Runtime jitter: `[10, 10, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[178.0, 2.0, 0.0]`, max_mm `[216.0, 26.0, 44.0]`
- `forbid_zones`:
  - `upper_descent_keepout`: min_mm `[-250.0, -102.0, 112.0]`, max_mm
    `[-112.0, 96.0, 224.0]`
  - `spike_field_keepout`: min_mm `[-230.0, -126.0, 24.0]`, max_mm
    `[176.0, 112.0, 170.0]`
- `build_zone_mm`: min_mm `[-420.0, -180.0, 0.0]`, max_mm `[420.0, 180.0, 280.0]`

## 5. Simulation Bounds

- min_mm `[-460, -200, -20]`
- max_mm `[460, 200, 280]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- All benchmark-owned geometry is static; the difficulty comes from the
  patterned seven-spike field, the narrower X corridor, and the slightly
  shallower basin.

## 7. Success Criteria

- Success if the ball ends inside `goal_zone_mm` without entering
  `spike_field_keepout`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark implies
  hidden motion in the spike field.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the patterned descent.
- `benchmark_definition.yaml` mirrors the declared zones, shelf geometry, and
  cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark
  evidence scene.
- `submit_benchmark_plan()` persists
  `.manifests/benchmark_plan_review_manifest.json`.
