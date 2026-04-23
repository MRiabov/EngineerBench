## 1. Learning Objective

Test whether an engineer can carry a `steel_ball` down an offset descent with
a higher launch point and a laterally shifted basin while still avoiding hidden
benchmark motion.

## 2. Environment Geometry

- `upper_start_platform`: elevated release platform centered at `[-300, -18, 182]`
  with size `[180, 150, 28]`.
- `upper_mid_step`: intermediate shelf centered at `[-120, -6, 132]` with size
  `[160, 128, 24]`.
- `lower_mid_step`: lower shelf centered at `[60, 18, 78]` with size
  `[150, 120, 22]`.
- `offset_goal_basin`: basin shifted toward positive Y, centered at
  `[312, 34, 24]` with size `[150, 132, 20]`.
- `north_spike`, `south_spike`, `center_spike`, `tail_spike`: fixed
  spike-like obstacles that bias the route toward a skewed downhill tail.

The route descends with a visible lateral offset, so the planner must account
for both the higher start and the shifted basin.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-335, -18, 230]`
- Runtime jitter: `[12, 12, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[276, 10, 12]`, max_mm `[356, 82, 60]`
- `forbid_zones`:
  - `upper_descent_keepout`: min_mm `[-255, -70, 130]`, max_mm
    `[-135, 70, 238]`
  - `offset_spike_field_keepout`: min_mm `[-170, -60, 28]`, max_mm
    `[200, 70, 184]`
- `build_zone_mm`: min_mm `[-420, -180, 0]`, max_mm `[420, 180, 260]`

## 5. Simulation Bounds

- min_mm `[-460, -200, -20]`, max_mm `[460, 200, 280]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- All benchmark-owned geometry is static; the benchmark should not imply any
  hidden actuator, moving spike, or powered descent assist.

## 7. Success Criteria

- Success if the ball ends inside `goal_zone_mm` without entering
  `offset_spike_field_keepout`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark requires
  undeclared motion to traverse the offset descent.

## 8. Planner Artifacts

- `todo.md` captures the engineer-planner checklist for the offset-basin route.
- `benchmark_definition.yaml` mirrors the declared zones, shelf geometry, and
  cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark
  evidence scene.
- `submit_benchmark_plan()` persists
  `.manifests/benchmark_plan_review_manifest.json`.
