## 1. Learning Objective

Test whether an engineer can carry a `steel_ball` down a compressed spiky
descent where the horizontal runout is shortened, the basin mouth is tighter,
and the spike field is denser near the lower approach.

## 2. Environment Geometry

- `upper_start_platform`: elevated launch platform centered at `[-306, -22, 196]`
  with size `[180, 148, 30]`.
- `upper_mid_step`: intermediate shelf centered at `[-150, -18, 152]` with
  size `[158, 126, 24]`.
- `lower_mid_step`: lower shelf centered at `[22, -12, 98]` with size
  `[146, 116, 22]`.
- `goal_basin`: shallow capture basin centered at `[140, 4, 18]` with size
  `[152, 128, 18]`.
- `spike_front_left`, `spike_front_right`, `spike_mid_center`,
  `spike_tail_left`, and `spike_tail_right`: fixed spike-like obstacles that
  compress the downhill runout into a tighter five-spike field.

The route still descends through the same three-step principle, but the final
runout is shorter and the lower field is more crowded than in the baseline
layered variant.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-334, -24, 242]`
- Runtime jitter: `[10, 10, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[140.0, 4.0, 0.0]`, max_mm `[176.0, 30.0, 44.0]`
- `forbid_zones`:
  - `upper_descent_keepout`: min_mm `[-250.0, -102.0, 110.0]`, max_mm
    `[-112.0, 96.0, 220.0]`
  - `spike_field_keepout`: min_mm `[-230.0, -126.0, 22.0]`, max_mm
    `[136.0, 112.0, 168.0]`
- `build_zone_mm`: min_mm `[-420.0, -180.0, 0.0]`, max_mm `[420.0, 180.0, 280.0]`

## 5. Simulation Bounds

- min_mm `[-460, -200, -20]`
- max_mm `[460, 200, 280]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- All benchmark-owned geometry is static; the benchmark challenge comes from
  the compressed runout, the tighter basin mouth, and the denser five-spike
  field.

## 7. Success Criteria

- Success if the ball ends inside `goal_zone_mm` without entering
  `spike_field_keepout`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark implies
  hidden motion in the spike field.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the compact descent.
- `benchmark_definition.yaml` mirrors the declared zones, shelf geometry, and
  cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark
  evidence scene.
- `submit_benchmark_plan()` persists
  `.manifests/benchmark_plan_review_manifest.json`.
