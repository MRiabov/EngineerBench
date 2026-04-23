## 1. Learning Objective

Test whether an engineer can carry a `steel_ball` down an offset descent with
a positive-Y shifted basin mouth and a six-spike asymmetric field while
staying within the benchmark motion contract.

## 2. Environment Geometry

- `upper_start_platform`: elevated release platform centered at `[-298, 18, 188]`
  with size `[178, 150, 28]`.
- `upper_mid_step`: intermediate shelf centered at `[-126, 16, 140]` with
  size `[150, 124, 24]`.
- `lower_mid_step`: lower shelf centered at `[44, 20, 86]` with size
  `[146, 118, 22]`.
- `offset_goal_basin`: passive capture basin centered at `[160, 34, 24]` with
  size `[160, 136, 18]`.
- `spike_nw`, `spike_ne`, `spike_center`, `spike_sw`, `spike_tail_left`, and
  `spike_tail_right`: fixed spike-like obstacles spread across the route with
  a stronger positive-Y bias near the basin.

The route still descends from the upper platform into the basin, but the basin
is laterally offset and the spikes occupy both upper and lower lanes instead of
forming a compact diagonal.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-334, 18, 231]`
- Runtime jitter: `[12, 12, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[142, 8, 0]`, max_mm `[178, 60, 48]`
- `forbid_zones`:
  - `upper_descent_keepout`: min_mm `[-232, -96, 118]`, max_mm
    `[-108, 96, 214]`
  - `spike_field_keepout`: min_mm `[-420, -100, 24]`, max_mm
    `[140, 120, 166]`
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
  undeclared motion to traverse the offset descent.

## 8. Planner Artifacts

- `todo.md` captures the engineer-planner checklist for the offset basin and
  six-spike field.
- `benchmark_definition.yaml` mirrors the declared zones, shelf geometry, and
  cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark
  evidence scene.
- `submit_benchmark_plan()` persists
  `.manifests/benchmark_plan_review_manifest.json`.
