## 1. Learning Objective

Test whether an engineer can carry a `steel_ball` down a layered descent with
a positive-Y shifted basin and a compact four-spike field that alternates
between upper and lower lanes.

## 2. Environment Geometry

- `upper_start_platform`: elevated release platform centered at `[-292, -20, 190]`
  with size `[178, 150, 28]`.
- `upper_mid_step`: intermediate shelf centered at `[-128, -14, 142]` with
  size `[154, 126, 24]`.
- `lower_mid_step`: lower shelf centered at `[44, -2, 88]` with size
  `[146, 120, 22]`.
- `goal_basin`: passive capture basin centered at `[156, 18, 20]` with size
  `[166, 142, 20]`.
- `spike_high_left`, `spike_high_right`, `spike_low_left`, and `spike_tail`:
  fixed spike-like obstacles alternating between upper and lower lanes to make
  the route read as a layered field.

The route still descends from the upper platform into the basin, but the
spikes are split across two vertical bands instead of forming a single row.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-334, -20, 231]`
- Runtime jitter: `[12, 12, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[138, 0, 0]`, max_mm `[174, 44, 48]`
- `forbid_zones`:
  - `upper_descent_keepout`: min_mm `[-228, -96, 118]`, max_mm
    `[-108, 96, 214]`
  - `spike_field_keepout`: min_mm `[-220, -130, 24]`, max_mm
    `[136, 120, 166]`
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
  undeclared motion to traverse the layered descent.

## 8. Planner Artifacts

- `todo.md` captures the engineer-planner checklist for the layered field.
- `benchmark_definition.yaml` mirrors the declared zones, shelf geometry, and
  cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark
  evidence scene.
- `submit_benchmark_plan()` persists
  `.manifests/benchmark_plan_review_manifest.json`.
