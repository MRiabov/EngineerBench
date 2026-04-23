## 1. Learning Objective

Review a lower-bin redirection benchmark package where a rear stop and a side
wall create a corner cradle around the final bin.

## 2. Environment Geometry

- `upper_start_ledge`: static release ledge centered at `[-50, -5, 175]` with
  size `[140, 125, 24]`.
- `deflector_ramp`: static redirection ramp centered at `[55, -10, 120]` with
  size `[180, 85, 22]`.
- `direct_drop_shield`: static shield centered at `[12, -10, 35]` with size
  `[95, 70, 70]`.
- `rear_stop`: static backstop centered at `[280, -95, 35]` with size
  `[110, 20, 70]`.
- `side_wall`: static side wall centered at `[345, -25, 35]` with size
  `[20, 90, 70]`.
- `lower_bin`: static capture bin centered at `[280, -25, 30]` with size
  `[110, 90, 50]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius_mm in `[28, 30]` mm
- Nominal start position: `[-50, -5, 225]`
- Runtime jitter: `[8, 8, 6]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[240, -80, 10]`, max_mm `[335, 30, 95]`
- `forbid_zones`:
  - `direct_drop_dead_zone`: min_mm `[-80, -55, 0]`, max_mm `[80, 45, 132]`
- `build_zone_mm`: min_mm `[-140, -180, 0]`, max_mm `[360, 180, 280]`

## 5. Simulation Bounds

- min_mm `[-190, -210, -10]`, max_mm `[430, 210, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 78 USD`, `max_weight <= 1450 g`
- The benchmark is fully static; success should come from passive redirection
  and a corner cradle around the bin rather than moving parts.

## 7. Success Criteria

- Success if the payload reaches `goal_zone_mm` without entering
  `direct_drop_dead_zone`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark implies
  hidden actuation.

## 8. Planner Artifacts

- `todo.md` tracks the ledge, ramp, shield, rear stop, side wall, and bin
  sequence.
- `benchmark_definition.yaml` mirrors the corner-catch geometry and caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  keeps the fixture set fully static.
