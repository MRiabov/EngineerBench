## 1. Learning Objective

Review a lower-bin redirection benchmark package where the payload starts
higher and must settle into a deeper lower bin with a passive redirection
path.

## 2. Environment Geometry

- `upper_start_ledge`: static release ledge centered at `[-45, 0, 180]` with
  size `[140, 120, 24]`.
- `deflector_ramp`: static redirection ramp centered at `[45, 0, 145]` with
  size `[190, 90, 22]`.
- `direct_drop_shield`: static shield centered at `[10, 0, 35]` with size
  `[100, 80, 70]`.
- `lower_bin`: static capture bin centered at `[285, 0, 30]` with size
  `[140, 120, 60]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius_mm in `[28, 30]` mm
- Nominal start position: `[-45, 0, 240]`
- Runtime jitter: `[8, 8, 6]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[230, -50, 10]`, max_mm `[340, 50, 110]`
- `forbid_zones`:
  - `direct_drop_dead_zone`: min_mm `[-80, -50, 0]`, max_mm `[80, 50, 130]`
- `build_zone_mm`: min_mm `[-140, -180, 0]`, max_mm `[360, 180, 280]`

## 5. Simulation Bounds

- min_mm `[-190, -210, -10]`, max_mm `[430, 210, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 78 USD`, `max_weight <= 1450 g`
- The benchmark is fully static; success should come from passive redirection
  and a deeper catch cavity rather than moving parts.

## 7. Success Criteria

- Success if the payload reaches `goal_zone_mm` without entering
  `direct_drop_dead_zone`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark implies
  hidden actuation.

## 8. Planner Artifacts

- `todo.md` tracks the high release, ramp, shield, and deeper bin sequence.
- `benchmark_definition.yaml` mirrors the taller drop geometry and caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  keeps the fixture set fully static.
