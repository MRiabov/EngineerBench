## 1. Learning Objective

Test whether an engineer can reason about a gravity-chute benchmark with a
taller clearance profile and a laterally offset outlet tray while keeping the
payload inside a clearly guided passive descent.

## 2. Environment Geometry

- `upper_inlet_frame`: static box centered at `[-275, 0, 184]` with size `[160, 160, 20]`.
- `upper_chute_step`: static box centered at `[-150, 0, 146]` with size `[190, 128, 20]`.
- `mid_chute_step`: static box centered at `[-10, 0, 106]` with size `[200, 128, 20]`.
- `lower_chute_step`: static box centered at `[140, 35, 66]` with size `[200, 128, 20]`.
- `exit_tray`: static box centered at `[305, 55, 24]` with size `[190, 160, 30]`.
- `left_guard_rail`: static box centered at `[20, -110, 104]` with size `[350, 18, 170]`.
- `right_guard_rail`: static box centered at `[20, 110, 104]` with size `[350, 18, 170]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held constant at 20 mm
- Nominal start position: `[-295, 0, 228]`
- Runtime jitter: `[8, 8, 5]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[250, 25, 10]`, max_mm `[345, 95, 84]`
- `forbid_zones`:
  - `offset_tray_escape_floor`: min_mm `[-190, -160, -5]`, max_mm `[225, 160, 40]`
- `build_zone_mm`: min_mm `[-360, -185, 0]`, max_mm `[420, 185, 270]`

## 5. Simulation Bounds

- min_mm `[-390, -220, -20]`, max_mm `[430, 220, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- The benchmark geometry is static and the chute should remain legible without hidden powered aids or benchmark-owned motion.

## 7. Success Criteria

- Success if `steel_ball` stays within the stepped chute and finishes inside `goal_zone_mm` on `exit_tray`.
- Fail if the ball leaves `simulation_bounds_mm`, escapes through the floor gap, or requires undeclared benchmark motion to complete the descent.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the inlet frame, stepped chute, and offset outlet tray geometry.
- `benchmark_definition.yaml` mirrors the declared zones, chute fixtures, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
