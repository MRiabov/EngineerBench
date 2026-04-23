## 1. Learning Objective

Test whether an engineer can reason about a gravity-chute benchmark with a terraced funnel, repeated stepped features, and paired decoy baffles while keeping the payload inside the guided descent and out of the escape floor.

## 2. Environment Geometry

- `upper_inlet_frame`: static box centered at `[-270, 10, 176]` with size `[150, 150, 20]`.
- `terrace_a`: static box centered at `[-190, -10, 144]` with size `[160, 100, 20]`.
- `terrace_b`: static box centered at `[-95, 24, 114]` with size `[150, 92, 20]`.
- `terrace_c`: static box centered at `[30, 8, 84]` with size `[140, 84, 20]`.
- `exit_tray`: static box centered at `[275, 18, 20]` with size `[160, 96, 30]`.
- `left_guard_rail`: static box centered at `[-45, -120, 100]` with size `[320, 16, 160]`.
- `right_guard_rail`: static box centered at `[-45, 104, 100]` with size `[320, 16, 160]`.
- `false_baffle_a`: static box centered at `[80, -150, 92]` with size `[28, 24, 90]`.
- `false_baffle_b`: static box centered at `[105, 140, 72]` with size `[24, 24, 80]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held constant at 20 mm
- Nominal start position: `[-285, 12, 220]`
- Runtime jitter: `[9, 7, 5]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[240, -2, 10]`, max_mm `[308, 46, 78]`
- `forbid_zones`:
  - `terrace_escape_floor`: min_mm `[-180, -145, -5]`, max_mm `[205, 130, 35]`
- `build_zone_mm`: min_mm `[-350, -180, 0]`, max_mm `[360, 180, 260]`

## 5. Simulation Bounds

- min_mm `[-390, -220, -20]`, max_mm `[420, 220, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- The benchmark geometry is static and the chute should remain legible without hidden powered aids or benchmark-owned motion.

## 7. Success Criteria

- Success if `steel_ball` stays inside the terraced funnel and finishes inside `goal_zone_mm` on `exit_tray`.
- Fail if the ball leaves `simulation_bounds_mm`, escapes through the floor gap, or requires undeclared benchmark motion to complete the descent.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the inlet frame, terraced surfaces, paired decoy baffles, and the contracted outlet tray geometry.
- `benchmark_definition.yaml` mirrors the declared zones, chute fixtures, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
