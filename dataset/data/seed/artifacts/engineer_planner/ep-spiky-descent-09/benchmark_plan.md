## 1. Learning Objective

Test whether an engineer can carry a `steel_ball` down a taller spiky descent
where the launch is higher, the basin is shifted negative-Y, and the obstacle
field alternates between upper and lower side lanes.

## 2. Environment Geometry

- `upper_start_platform`: elevated launch platform centered at `[-310, -18, 200]`
  with size `[182, 150, 30]`.
- `upper_mid_step`: intermediate shelf centered at `[-150, -12, 154]` with
  size `[160, 126, 24]`.
- `lower_mid_step`: lower shelf centered at `[30, -6, 100]` with size
  `[150, 120, 22]`.
- `goal_basin`: deeper capture basin centered at `[154, -24, 14]` with size
  `[158, 132, 22]`.
- `spike_west_high`, `spike_west_low`, `spike_center_high`, `spike_center_low`,
  `spike_tail_left`, and `spike_tail_right`: fixed spike-like obstacles arranged
  as a taller diagonal field with alternating side-lane offsets.

The route still descends through the same three-step principle, but the goal
basin is pulled negative-Y and the spike field is stretched into a longer
diagonal sequence.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-334, -24, 249]`
- Runtime jitter: `[10, 10, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[178.0, -34.0, 0.0]`, max_mm `[216.0, -8.0, 44.0]`
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
- All benchmark-owned geometry is static; the difficulty comes from the taller
  launch, the deeper negative-Y basin, and the longer alternating spike field.

## 7. Success Criteria

- Success if the ball ends inside `goal_zone_mm` without entering
  `spike_field_keepout`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark implies
  hidden motion in the spike field.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the taller descent.
- `benchmark_definition.yaml` mirrors the declared zones, shelf geometry, and
  cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark
  evidence scene.
- `submit_benchmark_plan()` persists
  `.manifests/benchmark_plan_review_manifest.json`.
