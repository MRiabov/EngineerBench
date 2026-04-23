## 1. Learning Objective

Test whether an engineer can reason about a gravity-chute benchmark where the
payload must follow a single bend that swings toward negative Y and still
settle into a lower outlet tray.

## 2. Environment Geometry

- `upper_inlet_frame`: static box centered at `[-260, 0, 176]` with size `[150, 150, 20]`.
- `upper_chute_step`: static box centered at `[-150, 0, 140]` with size `[180, 120, 20]`.
- `bend_diverter`: static box centered at `[-18, -78, 96]` with size `[40, 30, 70]`.
- `lower_chute_step`: static box centered at `[140, -66, 56]` with size `[190, 110, 20]`.
- `exit_tray`: static box centered at `[280, -66, 20]` with size `[170, 140, 30]`.
- `inner_guard_rail`: static box centered at `[40, -145, 100]` with size `[300, 18, 160]`.
- `outer_guard_rail`: static box centered at `[40, 145, 100]` with size `[300, 18, 160]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held constant at 20 mm
- Nominal start position: `[-290, 0, 220]`
- Runtime jitter: `[10, 10, 6]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[235, -120, 10]`, max_mm `[325, -20, 80]`
- `forbid_zones`:
  - `bend_escape_floor`: min_mm `[-160, -160, -5]`, max_mm `[210, 160, 35]`
- `build_zone_mm`: min_mm `[-350, -180, 0]`, max_mm `[360, 180, 260]`

## 5. Simulation Bounds

- min_mm `[-390, -220, -20]`, max_mm `[420, 220, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- The benchmark geometry is static and the bend should remain legible without hidden powered aids or benchmark-owned motion.

## 7. Success Criteria

- Success if `steel_ball` stays inside the bent chute and finishes inside `goal_zone_mm` on `exit_tray`.
- Fail if the ball leaves `simulation_bounds_mm`, escapes before the bend resolves, or requires undeclared benchmark motion to complete the descent.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the inlet frame, bend diverter, and offset outlet tray geometry.
- `benchmark_definition.yaml` mirrors the declared zones, chute fixtures, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
