## 1. Learning Objective

Review a lower-bin redirection benchmark package where twin side rails create
a narrowed entry channel into a central lower bin.

## 2. Environment Geometry

- `upper_start_ledge`: static release ledge centered at `[-30, 0, 170]` with
  size `[140, 120, 24]`.
- `deflector_ramp`: static redirection ramp centered at `[55, 0, 120]` with
  size `[185, 85, 22]`.
- `direct_drop_shield`: static shield centered at `[12, 0, 35]` with size
  `[95, 70, 70]`.
- `entry_channel_left`: static channel rail centered at `[290, -55, 35]` with
  size `[120, 10, 70]`.
- `entry_channel_right`: static channel rail centered at `[290, 55, 35]` with
  size `[120, 10, 70]`.
- `lower_bin`: static capture bin centered at `[290, 0, 30]` with size
  `[110, 90, 50]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius_mm in `[28, 30]` mm
- Nominal start position: `[-30, 0, 220]`
- Runtime jitter: `[8, 8, 6]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[245, -60, 10]`, max_mm `[340, 60, 95]`
- `forbid_zones`:
  - `direct_drop_dead_zone`: min_mm `[-80, -50, 0]`, max_mm `[80, 50, 130]`
- `build_zone_mm`: min_mm `[-140, -180, 0]`, max_mm `[360, 180, 280]`

## 5. Simulation Bounds

- min_mm `[-190, -210, -10]`, max_mm `[430, 210, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 78 USD`, `max_weight <= 1450 g`
- The benchmark is fully static; success should come from passive redirection
  and the narrowed approach channel rather than moving parts.

## 7. Success Criteria

- Success if the payload reaches `goal_zone_mm` without entering
  `direct_drop_dead_zone`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark implies
  hidden actuation.

## 8. Planner Artifacts

- `todo.md` tracks the ledge, ramp, shield, entry rails, and bin sequence.
- `benchmark_definition.yaml` mirrors the narrowed entry-channel geometry and
  caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  keeps the fixture set fully static.
