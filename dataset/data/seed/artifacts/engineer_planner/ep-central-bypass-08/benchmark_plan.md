## 1. Learning Objective

Test whether an engineer can route `projectile_ball` around a static central
blocker using a passive positive-Y bypass while keeping the path clear of a
slightly expanded no-go volume.

## 2. Geometry

- `left_start_deck`: static launch deck centered at `[-30, 0, 2]` mm, size
  `[28, 18, 4]` mm.
- `right_goal_deck`: static capture deck centered at `[30, 0, 2]` mm, size
  `[28, 18, 4]` mm.
- `central_blocker`: static blocker centered at `[0, -3, 18]` mm, size
  `[12, 14, 36]` mm; it sits slightly toward negative-Y so the positive-Y lane
  is the cleaner bypass.
- The benchmark stays static; the challenge is staying in the upper bypass
  lane rather than trying to thread the blocker.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization: none beyond the declared sphere shape
- Nominal start position: `[-30, 5, 38]`
- Runtime jitter: `[2, 2, 1]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[27, 2, 6]`, max_mm `[37, 10, 14]`
- `forbid_zones`:
  - `central_blocker`: min_mm `[-6, -10, 0]`, max_mm `[6, 4, 36]`
- `build_zone_mm`: min_mm `[-44.0, -28.0, 0.0]`, max_mm `[44.0, 28.0, 48.0]`

## 5. Simulation Bounds

- min_mm `[-60, -40, -10]`, max_mm `[60, 40, 70]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 24 USD`, `max_weight <= 24 g`
- All benchmark-owned geometry is static; the challenge comes from the
  positive-Y bypass choice and jitter tolerance, not hidden actuation.

## 7. Success Criteria

- Success if the sphere reaches `goal_zone_mm` without entering the
  `central_blocker` forbid volume.
- Fail if the sphere exits `simulation_bounds_mm` or if planner artifacts imply
  a shortcut through the blocker.

## 8. Planner Artifacts

- `todo.md` tracks the engineer-planner starter checklist for this bypass case.
- `benchmark_definition.yaml` mirrors the negative-Y blocker shift and the
  positive-Y route choice.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` and `benchmark_script.py` preview the
  same static bypass fixture set.
