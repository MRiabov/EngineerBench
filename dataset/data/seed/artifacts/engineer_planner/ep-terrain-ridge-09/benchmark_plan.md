## 1. Learning Objective

Test whether an engineer can carry a 25 mm-radius steel ball over a rounded
ridge while navigating a full four-sided perimeter wall enclosure, a circular
entry pillar, an off-axis center divider, a diagonally canted block, a decoy
tray, and a lifted goal tray without relying on hidden benchmark motion or a
frictionless flat push.

## 2. Environment Geometry

- `terrain_base`: flat route slab centered at `[0, 0, 6]` with size
  `[720, 180, 12]`.
- `terrain_ridge`: rounded ridge centered at `[0, 0, 34]` with radius `18`
  and length `150`; this is the benchmark-side terrain discontinuity, not an
  actuator.
- `left_noise_pillar`: cylindrical obstruction centered at `[-196, -54, 26]`
  with radius `12` and height `30`.
- `right_noise_block`: asymmetrical block centered at `[182, 48, 24]` with size
  `[42, 24, 18]`.
- `false_tray`: decoy tray centered at `[212, -38, 20]` with size
  `[76, 56, 8]`.
- `center_divider`: off-axis divider centered at `[58, 0, 30]` with size
  `[12, 118, 36]` and an `11 deg` yaw.
- `offset_mid_beam`: diagonally canted blocker centered at `[118, 18, 56]`
  with size `[32, 18, 68]` and a `30 deg` yaw.
- `north_wall`: perimeter wall centered at `[0, 89, 17]` with size
  `[700, 2, 10]`.
- `south_wall`: perimeter wall centered at `[0, -89, 17]` with size
  `[700, 2, 10]`.
- `west_wall`: perimeter wall centered at `[-405, 0, 17]` with size
  `[2, 176, 10]`.
- `east_wall`: perimeter wall centered at `[405, 0, 17]` with size
  `[2, 176, 10]`.
- `goal_catch_tray`: passive capture tray centered at `[345, 30, 24]` with size
  `[90, 90, 12]`.

The route still runs from left to right across the slab, but the wall enclosure
narrows the visual field and the ridge sits inside a tray-like perimeter with a
slightly skewed divider pushed further to the right.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held fixed at `25 mm`
  - no alternate shapes or size variants
- Nominal start position: `[-348, 0, 52]`
- Runtime jitter: `[12, 12, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[320, -5, 25]`, max_mm `[390, 70, 90]`
- `forbid_zones`:
- `ridge_keepout`: min_mm `[-72, -130, 12]`, max_mm `[72, 130, 36]`
- `build_zone_mm`: min_mm `[-420, -160, 0]`, max_mm `[420, 160, 220]`

## 5. Simulation Bounds

- min_mm `[-460, -200, -20]`, max_mm `[460, 200, 260]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- All benchmark-owned geometry is static; the benchmark should not imply any
  hidden powered cradle, moving ridge, or actuator.
- The ridge edges are softened with chamfers and fillets, and the perimeter
  rails are read-only enclosure geometry rather than solution aids.

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
