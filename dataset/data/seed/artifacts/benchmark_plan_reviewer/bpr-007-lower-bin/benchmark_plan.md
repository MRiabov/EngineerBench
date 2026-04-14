## 1. Learning Objective

Test whether an engineer can redirect a falling ball into a lower bin while avoiding a direct-drop dead zone that punishes uncontrolled release.

## 2. Environment Geometry

- `upper_start_ledge`: static ledge centered at `[-20, 0, 220]` with size `[120, 120, 24]`.
- `deflector_ramp`: static ramp centered at `[110, 0, 145]` with size `[180, 100, 90]`.
- `direct_drop_shield`: static blocker centered at `[0, 0, 65]` with size `[120, 90, 130]`.
- `lower_bin`: static capture bin centered at `[270, 0, 40]` with size `[130, 110, 60]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius in `[28, 30]` mm
- Nominal start position: `[-20, 0, 220]`
- Runtime jitter: `[8, 8, 6]` mm

## 4. Objectives

- `goal_zone`: min `[220, -45, 10]`, max `[320, 45, 85]`
- `forbid_zones`:
  - `direct_drop_dead_zone`: min `[-60, -45, 0]`, max `[60, 45, 130]`
- `build_zone`: min `[-120, -160, 0]`, max `[360, 160, 280]`

## 5. Simulation Bounds

- min `[-180, -200, -10]`, max `[420, 200, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 78 USD`, `max_weight <= 1450 g`
- The benchmark is fully static; success should come from controlled redirection rather than benchmark-side moving parts.

## 7. Success Criteria

- Success if the payload reaches `goal_zone` without entering `direct_drop_dead_zone`.
- Fail if the ball exits `simulation_bounds` or if planner artifacts imply undeclared active redirection hardware.

## 8. Planner Artifacts

- `todo.md` tracks the start ledge, deflector, dead-zone shield, and lower bin implementation.
- `benchmark_definition.yaml` mirrors the gravity-driven geometry and customer caps.
- `benchmark_assembly_definition.yaml` records the static benchmark-local parts and confirms zero DOFs.
