## 1. Learning Objective

Test whether an engineer can route `projectile_ball` around a static central
blocker using a passive bypass design rather than a direct-line transfer.

## 2. Geometry

- `left_start_deck`: static launch deck centered at `[-30, 0, 2]` mm, size
  `[28, 18, 4]` mm.
- `right_goal_deck`: static capture deck centered at `[30, 0, 2]` mm, size
  `[28, 18, 4]` mm.
- `central_blocker`: tall static blocker centered at `[0, 0, 16]` mm, size
  `[10, 14, 32]` mm, fixed in the middle of the route.
- The benchmark stays static; the challenge is choosing a bypass route around
  the blocker without relying on benchmark-side motion, with an intentionally
  tightened centered corridor carrying most of the signal.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Radius range (static randomization): `[4.8, 6.0]` mm
- Nominal start position: `[-30, 0.5, 24]`
- Runtime jitter: `[2, 2, 1]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[27, -4, 6]`, max_mm `[37, 4, 14]`
- `forbid_zones`:
  - `central_blocker`: min_mm `[-7, -9, 0]`, max_mm `[7, 9, 32]`
- `build_zone_mm`: min_mm `[-44.0, -28.0, 0.0]`, max_mm `[44.0, 28.0, 48.0]`

## 5. Simulation Bounds

- min_mm `[-60, -40, -10]`, max_mm `[60, 40, 70]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 24 USD`, `max_weight <= 24 g`
- All benchmark-owned geometry is static; the challenge should come from the
  around-obstacle route and jitter tolerance, not hidden actuation.

## 7. Success Criteria

- Success if the ball reaches `goal_zone_mm` without entering the
  `central_blocker` forbid volume, using the tightened centered corridor.
- Fail if the ball exits `simulation_bounds_mm` or if planner artifacts imply a
  shortcut through the blocker.

## 8. Planner Artifacts

- `todo.md` tracks implementation of the launch deck, blocker, bypass route,
  and goal deck.
- `benchmark_definition.yaml` mirrors the route geometry and objective zones.
- `benchmark_assembly_definition.yaml` records benchmark-local cost estimates
  and confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` and `benchmark_script.py` preview the
  same static bypass fixture set.
