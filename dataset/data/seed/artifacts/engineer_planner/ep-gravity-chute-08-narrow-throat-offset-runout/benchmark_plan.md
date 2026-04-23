## 1. Learning Objective

Test whether an engineer can reason about a gravity-chute style benchmark where a payload must stay inside a visually contracted, guided descent from an upper inlet to a slightly offset lower outlet tray without relying on hidden benchmark motion.

## 2. Environment Geometry

- `upper_inlet_frame`: static box centered at `[-260, -5, 170]` with size `[150, 130, 20]`.
- `upper_chute_step`: static box centered at `[-150, -8, 135]` with size `[180, 110, 20]`.
- `mid_chute_step`: static box centered at `[-20, -8, 95]` with size `[190, 94, 20]`.
- `lower_chute_step`: static box centered at `[120, -4, 55]` with size `[190, 82, 20]`.
- `exit_tray`: static box centered at `[270, -4, 20]` with size `[180, 108, 30]`.
- `left_guard_rail`: static box centered at `[-55, -90, 100]` with size `[320, 16, 160]`.
- `right_guard_rail`: static box centered at `[-55, 81, 100]` with size `[320, 16, 160]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held constant at 20 mm
- Nominal start position: `[-280, -4, 218]`
- Runtime jitter: `[8, 7, 5]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[235, -50, 10]`, max_mm `[325, 45, 82]`
- `forbid_zones`:
  - `chute_escape_floor`: min_mm `[-170, -140, -5]`, max_mm `[200, 130, 35]`
- `build_zone_mm`: min_mm `[-350, -180, 0]`, max_mm `[360, 180, 260]`

## 5. Simulation Bounds

- min_mm `[-390, -220, -20]`, max_mm `[420, 220, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- The benchmark geometry is static and the chute should remain legible without hidden powered aids or benchmark-owned motion.

## 7. Success Criteria

- Success if `steel_ball` stays within the contracted chute and finishes inside `goal_zone_mm` on `exit_tray`.
- Fail if the ball leaves `simulation_bounds_mm`, escapes through the floor gap, or requires undeclared benchmark motion to complete the descent.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the inlet frame, stepped chute, contracted throat, and outlet tray geometry.
- `benchmark_definition.yaml` mirrors the declared zones, chute fixtures, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
