## 1. Learning Objective

Test whether an engineer can reason about a gravity-chute style benchmark where a payload must stay inside a stepped, guided descent from an upper inlet to a lower outlet tray without relying on hidden benchmark motion.

## 2. Environment Geometry

- `upper_inlet_frame`: static box centered at `[-260, 0, 170]` with size `[150, 150, 20]`.
- `upper_chute_step`: static box centered at `[-150, 0, 135]` with size `[180, 140, 20]`.
- `mid_chute_step`: static box centered at `[-20, 0, 95]` with size `[190, 140, 20]`.
- `lower_chute_step`: static box centered at `[120, 0, 55]` with size `[190, 140, 20]`.
- `exit_tray`: static box centered at `[265, 0, 20]` with size `[170, 150, 30]`.
- `left_guard_rail`: static box centered at `[-60, -85, 100]` with size `[320, 20, 160]`.
- `right_guard_rail`: static box centered at `[-60, 85, 100]` with size `[320, 20, 160]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held constant at 20 mm
- Nominal start position: `[-280, 0, 218]`
- Runtime jitter: `[8, 8, 5]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[230, -70, 10]`, max_mm `[315, 70, 80]`
- `forbid_zones`:
  - `chute_escape_floor`: min_mm `[-160, -150, -5]`, max_mm `[190, 150, 35]`
- `build_zone_mm`: min_mm `[-350, -180, 0]`, max_mm `[360, 180, 260]`

## 5. Simulation Bounds

- min_mm `[-390, -220, -20]`, max_mm `[420, 220, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- The benchmark geometry is static and the chute should remain legible without hidden powered aids or benchmark-owned motion.

## 7. Success Criteria

- Success if `steel_ball` stays within the stepped chute and finishes inside `goal_zone_mm` on `exit_tray`.
- Fail if the ball leaves `simulation_bounds_mm`, escapes through the floor gap, or requires undeclared benchmark motion to complete the descent.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the inlet frame, stepped chute, and outlet tray geometry.
- `benchmark_definition.yaml` mirrors the declared zones, chute fixtures, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
