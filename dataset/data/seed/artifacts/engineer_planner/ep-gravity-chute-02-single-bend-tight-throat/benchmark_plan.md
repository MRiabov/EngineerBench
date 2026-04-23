## 1. Learning Objective

Test whether an engineer can reason about a gravity-chute benchmark with a single bend, a tighter throat, and a laterally offset outlet while keeping the payload inside the guided descent and out of the escape floor.

## 2. Environment Geometry

- `upper_inlet_frame`: static box centered at `[-260, 0, 170]` with size `[150, 150, 20]`.
- `upper_chute_step`: static box centered at `[-150, 0, 135]` with size `[180, 120, 20]`.
- `bend_diverter`: static box centered at `[-20, 75, 95]` with size `[40, 30, 70]`.
- `lower_chute_step`: static box centered at `[140, 65, 55]` with size `[190, 110, 20]`.
- `exit_tray`: static box centered at `[275, 65, 20]` with size `[160, 140, 30]`.
- `inner_guard_rail`: static box centered at `[40, -110, 100]` with size `[300, 18, 160]`.
- `outer_guard_rail`: static box centered at `[40, 130, 100]` with size `[300, 18, 160]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held constant at 20 mm
- Nominal start position: `[-280, 0, 218]`
- Runtime jitter: `[10, 10, 6]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[235, 15, 10]`, max_mm `[325, 115, 80]`
- `forbid_zones`:
  - `bend_escape_floor`: min_mm `[-150, -150, -5]`, max_mm `[205, 150, 35]`
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
