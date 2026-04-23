## 1. Learning Objective

Test whether an engineer can reason about a gravity-chute benchmark with uneven offsets, a layered runout, and a visually distracting decoy tower while keeping the payload inside the guided descent and out of the escape floor.

## 2. Environment Geometry

- `upper_inlet_frame`: static box centered at `[-275, -20, 170]` with size `[150, 130, 20]`.
- `upper_chute_step`: static box centered at `[-170, -18, 138]` with size `[170, 108, 20]`.
- `mid_chute_step`: static box centered at `[-25, 10, 102]` with size `[180, 92, 20]`.
- `lower_chute_step`: static box centered at `[125, 28, 64]` with size `[190, 84, 20]`.
- `exit_tray`: static box centered at `[275, 28, 20]` with size `[160, 104, 30]`.
- `left_guard_rail`: static box centered at `[-45, -128, 100]` with size `[320, 16, 160]`.
- `right_guard_rail`: static box centered at `[-45, 94, 100]` with size `[320, 16, 160]`.
- `decoy_tower`: static box centered at `[30, -160, 90]` with size `[30, 30, 140]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held constant at 20 mm
- Nominal start position: `[-280, -4, 218]`
- Runtime jitter: `[8, 7, 5]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[238, 18, 10]`, max_mm `[325, 68, 80]`
- `forbid_zones`:
  - `escape_floor`: min_mm `[-170, -140, -5]`, max_mm `[205, 130, 35]`
- `build_zone_mm`: min_mm `[-350, -180, 0]`, max_mm `[360, 180, 260]`

## 5. Simulation Bounds

- min_mm `[-390, -220, -20]`, max_mm `[420, 220, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- The benchmark geometry is static and the chute should remain legible without hidden powered aids or benchmark-owned motion.

## 7. Success Criteria

- Success if `steel_ball` stays inside the layered chute and finishes inside `goal_zone_mm` on `exit_tray`.
- Fail if the ball leaves `simulation_bounds_mm`, escapes through the floor gap, or requires undeclared benchmark motion to complete the descent.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the inlet frame, staggered chute steps, decoy tower, and offset outlet tray geometry.
- `benchmark_definition.yaml` mirrors the declared zones, chute fixtures, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
