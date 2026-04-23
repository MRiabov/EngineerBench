## 1. Learning Objective

Test whether an engineer can carry a `steel_ball` down a compressed stepped
descent with a shortened runout and a shallow landing basin while staying
clear of a compact spike trio and without relying on hidden benchmark motion.

## 2. Environment Geometry

- `upper_start_platform`: elevated release platform centered at `[-274, 2, 184]`
  with size `[174, 148, 28]`.
- `compact_mid_step`: intermediate shelf centered at `[-106, -6, 136]` with
  size `[146, 122, 24]`.
- `compact_lower_step`: lower shelf centered at `[28, 8, 84]` with size
  `[144, 118, 22]`.
- `shallow_goal_basin`: passive capture basin centered at `[144, 12, 22]` with
  size `[148, 126, 18]`.
- `spike_front_left`, `spike_mid`, `spike_low_right`: fixed spike-like
  obstacles arranged on a shortened downhill diagonal.

The route still descends from the upper platform into the basin, but the
horizontal span is more compact than the baseline variant and the landing
basin is shallower.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-326, 4, 230]`
- Runtime jitter: `[12, 12, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[108, -40, 8]`, max_mm `[180, 68, 50]`
- `forbid_zones`:
  - `upper_descent_keepout`: min_mm `[-232, -96, 118]`, max_mm
    `[-114, 96, 214]`
  - `spike_field_keepout`: min_mm `[-202, -120, 24]`, max_mm
    `[100, 80, 160]`
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
  undeclared motion to traverse the compact descent.

## 8. Planner Artifacts

- `todo.md` captures the engineer-planner checklist for the compact runout.
- `benchmark_definition.yaml` mirrors the declared zones, shelf geometry, and
  cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark
  evidence scene.
- `submit_benchmark_plan()` persists
  `.manifests/benchmark_plan_review_manifest.json`.
