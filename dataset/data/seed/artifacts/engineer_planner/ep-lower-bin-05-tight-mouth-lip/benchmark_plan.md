## 1. Learning Objective

Review a lower-bin redirection benchmark package where the catch bin has a
tighter mouth and a passive lip that changes the landing envelope.

## 2. Environment Geometry

- `upper_start_ledge`: static release ledge centered at `[-35, 5, 165]` with
  size `[145, 128, 24]`.
- `deflector_ramp`: static redirection ramp centered at `[60, 10, 112]` with
  size `[180, 88, 22]`.
- `direct_drop_shield`: static shield centered at `[10, -8, 35]` with size
  `[95, 70, 70]`.
- `lower_bin`: static capture bin centered at `[280, 18, 28]` with size
  `[110, 90, 46]`.
- `catch_lip`: static lip centered at `[280, 18, 74]` with size `[120, 90, 12]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius_mm in `[28, 30]` mm
- Nominal start position: `[-35, 5, 220]`
- Runtime jitter: `[8, 8, 6]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[250, 0, 10]`, max_mm `[315, 45, 90]`
- `forbid_zones`:
  - `direct_drop_dead_zone`: min_mm `[-80, -50, 0]`, max_mm `[80, 50, 130]`
- `build_zone_mm`: min_mm `[-140, -180, 0]`, max_mm `[360, 180, 280]`

## 5. Simulation Bounds

- min_mm `[-190, -210, -10]`, max_mm `[430, 210, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 78 USD`, `max_weight <= 1450 g`
- The benchmark is fully static; success should come from passive redirection
  and a smaller landing mouth rather than moving parts.

## 7. Success Criteria

- Success if the payload reaches `goal_zone_mm` without entering
  `direct_drop_dead_zone`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark implies
  hidden actuation.

## 8. Planner Artifacts

- `todo.md` tracks the ledge, ramp, shield, bin, and lip sequence.
- `benchmark_definition.yaml` mirrors the tighter catch-mouth geometry and
  caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  keeps the fixture set fully static.
