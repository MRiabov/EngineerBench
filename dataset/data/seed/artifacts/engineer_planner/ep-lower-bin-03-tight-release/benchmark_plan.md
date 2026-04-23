## 1. Learning Objective

Review a lower-bin redirection benchmark package where the capture mouth is
smaller, the release is more tightly aligned, and the passive shield must keep
the direct-drop path obvious.

## 2. Environment Geometry

- `upper_start_ledge`: static release ledge centered at `[-40, -5, 175]` with
  size `[140, 125, 24]`.
- `deflector_ramp`: static redirection ramp centered at `[55, -8, 118]` with
  size `[175, 85, 22]`.
- `direct_drop_shield`: static shield centered at `[10, -2, 35]` with size
  `[110, 82, 70]`.
- `lower_bin`: static capture bin centered at `[280, -18, 31]` with size
  `[120, 100, 48]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius_mm in `[28, 30]` mm
- Nominal start position: `[-40, -5, 228]`
- Runtime jitter: `[8, 8, 6]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[235, -65, 10]`, max_mm `[330, 5, 90]`
- `forbid_zones`:
  - `direct_drop_dead_zone`: min_mm `[-80, -55, 0]`, max_mm `[75, 45, 132]`
- `build_zone_mm`: min_mm `[-140, -180, 0]`, max_mm `[360, 180, 280]`

## 5. Simulation Bounds

- min_mm `[-190, -210, -10]`, max_mm `[430, 210, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 78 USD`, `max_weight <= 1450 g`
- The benchmark is fully static; success should come from precise passive
  release alignment and a narrower catch geometry rather than moving parts.

## 7. Success Criteria

- Success if the payload reaches `goal_zone_mm` without entering
  `direct_drop_dead_zone`.
- Fail if the ball leaves `simulation_bounds_mm` or if the benchmark implies
  unsupported active motion.

## 8. Planner Artifacts

- `todo.md` tracks the tighter ledge, compact ramp, shield, and bin sequence.
- `benchmark_definition.yaml` mirrors the compact lower-bin geometry and caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local parts and
  keeps the fixture set fully static.
