## 1. Learning Objective

Test whether an engineer can carry a 25 mm-radius steel ball over a chamfered,
filleted step ridge while navigating asymmetric clutter blocks and without
relying on hidden benchmark motion or a frictionless flat push.

## 2. Environment Geometry

- `terrain_base`: flat route slab centered at `[0, 0, 6]` with size
  `[720, 180, 12]`.
- `terrain_ridge`: softened step centered at `[0, 0, 20]` with size
  `[120, 180, 16]`; this is the benchmark-side terrain discontinuity, not an
  actuator.
- `left_noise_block`: low clutter block centered at `[-185, -58, 22]` with
  size `[36, 42, 20]`.
- `right_noise_block`: low clutter block centered at `[168, 54, 21]` with size
  `[40, 34, 18]`.
- `goal_catch_tray`: passive capture tray centered at `[330, 0, 24]` with size
  `[160, 180, 12]`.

The route still runs from left to right across the slab, but the ridge is
shorter and the clutter blocks add asymmetric visual noise to the open route.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-348, 0, 163]`
- Runtime jitter: `[12, 12, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[320, -90, 25]`, max_mm `[390, 90, 90]`
- `forbid_zones`:
  - `ridge_keepout`: min_mm `[-72, -130, 12]`, max_mm `[72, 130, 36]`
- `build_zone_mm`: min_mm `[-420, -160, 0]`, max_mm `[420, 160, 220]`

## 5. Simulation Bounds

- min_mm `[-460, -200, -20]`, max_mm `[460, 200, 260]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- All benchmark-owned geometry is static; the benchmark should not imply any
  hidden powered cradle, moving ridge, or actuator.
- The ridge edges are softened with chamfers and fillets, and the two clutter
  blocks are read-only obstructions rather than solution aids.

## 7. Success Criteria

- Success if the ball ends inside `goal_zone_mm` without entering
  `ridge_keepout`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark requires
  undeclared motion to cross the softened step ridge.

## 8. Planner Artifacts

- `todo.md` captures the engineer-planner checklist for the ridge-crossing
  guide solution.
- `benchmark_definition.yaml` mirrors the declared zones, ridge geometry, and
  cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured
  parts and confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark
  evidence scene.
- `submit_benchmark_plan()` persists
  `.manifests/benchmark_plan_review_manifest.json`.
