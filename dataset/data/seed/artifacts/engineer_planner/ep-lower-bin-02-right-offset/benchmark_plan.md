## 1. Learning Objective

Review a lower-bin redirection benchmark package where the payload must follow
a laterally offset passive route into a side-shifted lower bin.

## 2. Environment Geometry

- `upper_start_ledge`: static release ledge centered at `[-35, 8, 170]` with
  size `[145, 130, 24]`.
- `deflector_ramp`: static redirection ramp centered at `[70, 18, 115]` with
  size `[180, 90, 22]`.
- `direct_drop_shield`: static shield centered at `[18, 6, 35]` with size
  `[105, 86, 70]`.
- `lower_bin`: static capture bin centered at `[285, 35, 30]` with size
  `[130, 110, 50]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius_mm in `[28, 30]` mm
- Nominal start position: `[-35, 8, 225]`
- Runtime jitter: `[8, 8, 6]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[240, 0, 10]`, max_mm `[345, 85, 95]`
- `forbid_zones`:
  - `direct_drop_dead_zone`: min_mm `[-75, -50, 0]`, max_mm `[80, 55, 130]`
- `build_zone_mm`: min_mm `[-140, -180, 0]`, max_mm `[360, 180, 280]`

## 5. Simulation Bounds

- min_mm `[-190, -210, -10]`, max_mm `[430, 210, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 78 USD`, `max_weight <= 1450 g`
- The benchmark is fully static; success should come from passive redirection
  and side-offset geometry rather than benchmark-side motion.

## 7. Success Criteria

- Success if the payload reaches `goal_zone_mm` without entering
  `direct_drop_dead_zone`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark implies
  hidden actuation.

## 8. Planner Artifacts

- `todo.md` should sequence the offset ledge, skewed ramp, shield, and bin.
- `benchmark_definition.yaml` mirrors the offset geometry and caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  keeps the fixture set fully static.
