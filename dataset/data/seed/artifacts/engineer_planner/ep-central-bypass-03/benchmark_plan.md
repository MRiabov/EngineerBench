## 1. Learning Objective

Test whether an engineer can route `transfer_cube` around a static central
blocker using a passive positive-Y bypass under a tighter corridor envelope.

## 2. Geometry

- `left_start_deck`: static launch deck centered at `[-30, 0, 2]` mm, size
  `[28, 18, 4]` mm.
- `right_goal_deck`: static capture deck centered at `[30, 0, 2]` mm, size
  `[28, 18, 4]` mm.
- `central_blocker`: static blocker centered at `[0, -4, 17]` mm, size
  `[10, 16, 34]` mm; it is shifted toward negative-Y and made slightly taller
  and wider so the positive-Y route is narrower.
- The benchmark stays static; the challenge is choosing the right-hand bypass
  corridor and preserving clearance against the expanded blocker envelope.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization: none beyond the declared cube shape
- Nominal start position: `[-30, 6, 24]`
- Runtime jitter: `[3, 2, 1]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[27, 2, 6]`, max_mm `[37, 10, 14]`
- `forbid_zones`:
  - `central_blocker`: min_mm `[-5, -12, 0]`, max_mm `[5, 4, 34]`
- `build_zone_mm`: min_mm `[-44.0, -28.0, 0.0]`, max_mm `[44.0, 28.0, 48.0]`

## 5. Simulation Bounds

- min_mm `[-60, -40, -10]`, max_mm `[60, 40, 70]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 24 USD`, `max_weight <= 24 g`
- All benchmark-owned geometry is static; the challenge comes from the
  tightened positive-Y bypass corridor and the payload jitter, not hidden
  actuation.

## 7. Success Criteria

- Success if the cube reaches `goal_zone_mm` without entering the
  `central_blocker` forbid volume.
- Fail if the cube exits `simulation_bounds_mm` or if planner artifacts imply
  a shortcut through the blocker.

## 8. Planner Artifacts

- `todo.md` tracks implementation of the launch deck, blocker, bypass route,
  and goal deck.
- `benchmark_definition.yaml` mirrors the shifted blocker, tighter goal
  window, and right-biased route choice.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` and `benchmark_script.py` preview the
  same static bypass fixture set.
