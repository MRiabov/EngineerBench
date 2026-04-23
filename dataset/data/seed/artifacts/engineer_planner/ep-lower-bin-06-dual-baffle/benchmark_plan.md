## 1. Learning Objective

Review a lower-bin redirection benchmark package where two mid-course baffles
create a repeated obstruction pattern before the payload reaches the bin.

## 2. Environment Geometry

- `upper_start_ledge`: static release ledge centered at `[-45, -5, 180]` with
  size `[140, 125, 24]`.
- `deflector_ramp`: static redirection ramp centered at `[55, -5, 125]` with
  size `[185, 85, 22]`.
- `direct_drop_shield`: static shield centered at `[15, -20, 35]` with size
  `[100, 80, 70]`.
- `midway_baffle_left`: static obstruction centered at `[165, -60, 35]` with
  size `[30, 60, 70]`.
- `midway_baffle_right`: static obstruction centered at `[165, 20, 35]` with
  size `[30, 60, 70]`.
- `lower_bin`: static capture bin centered at `[290, -25, 32]` with size
  `[125, 105, 48]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius_mm in `[28, 30]` mm
- Nominal start position: `[-45, -5, 230]`
- Runtime jitter: `[8, 8, 6]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[250, -70, 10]`, max_mm `[335, 15, 95]`
- `forbid_zones`:
  - `direct_drop_dead_zone`: min_mm `[-80, -55, 0]`, max_mm `[80, 45, 132]`
- `build_zone_mm`: min_mm `[-140, -180, 0]`, max_mm `[360, 180, 280]`

## 5. Simulation Bounds

- min_mm `[-190, -210, -10]`, max_mm `[430, 210, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 78 USD`, `max_weight <= 1450 g`
- The benchmark is fully static; success should come from passive redirection
  and repeated obstructions rather than moving parts.

## 7. Success Criteria

- Success if the payload reaches `goal_zone_mm` without entering
  `direct_drop_dead_zone`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark implies
  hidden actuation.

## 8. Planner Artifacts

- `todo.md` tracks the ledge, ramp, shield, repeated baffles, and bin
  sequence.
- `benchmark_definition.yaml` mirrors the duplicated-obstruction geometry and
  caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  keeps the fixture set fully static.
