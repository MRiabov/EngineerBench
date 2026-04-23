## 1. Learning Objective

Review a lower-bin redirection benchmark package where a ball starts on a
raised ledge, is steered by a passive deflector, avoids a direct-drop dead
zone, and settles into a wide lower bin.

## 2. Environment Geometry

- `upper_start_ledge`: static release ledge centered at `[-25, 0, 160]` with
  size `[150, 140, 24]`.
- `deflector_ramp`: static redirection ramp centered at `[60, 0, 110]` with
  size `[190, 90, 22]`.
- `direct_drop_shield`: static shield centered at `[15, 0, 35]` with size
  `[100, 80, 70]`.
- `lower_bin`: static capture bin centered at `[275, 0, 30]` with size
  `[140, 120, 50]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius_mm in `[28, 30]` mm
- Nominal start position: `[-25, 0, 220]`
- Runtime jitter: `[8, 8, 6]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[225, -50, 10]`, max_mm `[335, 50, 95]`
- `forbid_zones`:
  - `direct_drop_dead_zone`: min_mm `[-70, -50, 0]`, max_mm `[70, 50, 130]`
- `build_zone_mm`: min_mm `[-140, -180, 0]`, max_mm `[360, 180, 280]`

## 5. Simulation Bounds

- min_mm `[-190, -210, -10]`, max_mm `[430, 210, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 78 USD`, `max_weight <= 1450 g`
- The benchmark is fully static; success should come from passive redirection
  rather than benchmark-side moving parts.

## 7. Success Criteria

- Success if the payload reaches `goal_zone_mm` without entering
  `direct_drop_dead_zone`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark
  artifacts imply undeclared active hardware.

## 8. Planner Artifacts

- `todo.md` tracks the ledge, ramp, shield, and bin implementation sequence.
- `benchmark_definition.yaml` mirrors the declared zones, geometry, and caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  confirms the benchmark is fully static.
