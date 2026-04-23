## 1. Learning Objective

Review a lower-bin redirection benchmark package where staggered lips shape a
diagonal release into a shallow tray-style catch.

## 2. Environment Geometry

- `upper_start_ledge`: static release ledge centered at `[-55, 5, 170]` with
  size `[130, 115, 24]`.
- `deflector_ramp`: static redirection ramp centered at `[35, 10, 112]` with
  size `[170, 80, 22]`.
- `direct_drop_shield`: static shield centered at `[8, 5, 34]` with size
  `[95, 68, 68]`.
- `release_lip`: static release lip centered at `[160, 5, 82]` with size
  `[24, 110, 20]`.
- `front_lip`: static front lip centered at `[295, 88, 35]` with size
  `[110, 16, 30]`.
- `lower_bin`: static capture bin centered at `[295, 25, 30]` with size
  `[110, 90, 50]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius_mm in `[28, 30]` mm
- Nominal start position: `[-55, 5, 225]`
- Runtime jitter: `[8, 8, 6]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[250, -10, 10]`, max_mm `[345, 70, 95]`
- `forbid_zones`:
  - `direct_drop_dead_zone`: min_mm `[-80, -55, 0]`, max_mm `[80, 45, 132]`
- `build_zone_mm`: min_mm `[-140, -180, 0]`, max_mm `[360, 180, 280]`

## 5. Simulation Bounds

- min_mm `[-190, -210, -10]`, max_mm `[430, 210, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 78 USD`, `max_weight <= 1450 g`
- The benchmark is fully static; success should come from passive redirection
  and the staggered lip geometry rather than moving parts.

## 7. Success Criteria

- Success if the payload reaches `goal_zone_mm` without entering
  `direct_drop_dead_zone`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark implies
  hidden actuation.

## 8. Planner Artifacts

- `todo.md` tracks the ledge, ramp, shield, release lip, front lip, and bin
  sequence.
- `benchmark_definition.yaml` mirrors the staggered-lip geometry and caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  keeps the fixture set fully static.
