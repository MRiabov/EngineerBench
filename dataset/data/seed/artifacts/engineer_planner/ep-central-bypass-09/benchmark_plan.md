## 1. Learning Objective

Test whether an engineer can route `transfer_cube` around a static central
blocker using a passive negative-Y bypass when the blocker is centered and the
clearance window is slightly wider but still tight.

## 2. Geometry

- `left_start_deck`: static launch deck centered at `[-30, 0, 2]` mm, size
  `[28, 18, 4]` mm.
- `right_goal_deck`: static capture deck centered at `[30, 0, 2]` mm, size
  `[28, 18, 4]` mm.
- `central_blocker`: static blocker centered at `[0, 0, 18]` mm, size
  `[14, 18, 38]` mm; it is centered and deliberately widened so the usable
  corridor feels compressed on both sides.
- The benchmark stays static; the challenge is choosing the lower bypass lane
  and respecting the inflated no-go envelope.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization: none beyond the declared cube shape
- Nominal start position: `[-30, -5, 38]`
- Runtime jitter: `[2, 2, 1]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[27, -10, 6]`, max_mm `[37, -2, 14]`
- `forbid_zones`:
  - `central_blocker`: min_mm `[-7, -9, 0]`, max_mm `[7, 9, 38]`
- `build_zone_mm`: min_mm `[-44.0, -28.0, 0.0]`, max_mm `[44.0, 28.0, 48.0]`

## 5. Simulation Bounds

- min_mm `[-60, -40, -10]`, max_mm `[60, 40, 70]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 24 USD`, `max_weight <= 24 g`
- All benchmark-owned geometry is static; the challenge comes from the centered
  wide-blocker corridor and the lower bypass choice, not hidden actuation.

## 7. Success Criteria

- Success if the cube reaches `goal_zone_mm` without entering the
  `central_blocker` forbid volume.
- Fail if the cube exits `simulation_bounds_mm` or if planner artifacts imply
  a shortcut through the blocker.

## 8. Planner Artifacts

- `todo.md` tracks the engineer-planner starter checklist for this centered
  bypass case.
- `benchmark_definition.yaml` mirrors the centered blocker, widened no-go
  envelope, and lower goal window.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` and `benchmark_script.py` preview the
  same static bypass fixture set.
