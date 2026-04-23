## 1. Learning Objective

Test whether an engineer can reason about a gravity-chute style benchmark where a payload must stay inside a patterned, guided descent from an upper inlet through three staggered risers to a lower outlet tray without relying on hidden benchmark motion.

## 2. Environment Geometry

- `upper_inlet_frame`: static box centered at `[-255, -15, 174]` with size `[160, 140, 20]`.
- `upper_chute_step`: static box centered at `[-155, -15, 140]` with size `[175, 120, 20]`.
- `riser_a`: static box centered at `[-35, 15, 108]` with size `[60, 35, 40]`.
- `riser_b`: static box centered at `[25, -20, 78]` with size `[80, 25, 40]`.
- `riser_c`: static box centered at `[100, 8, 54]` with size `[60, 35, 40]`.
- `lower_chute_step`: static box centered at `[230, 0, 42]` with size `[190, 120, 20]`.
- `exit_tray`: static box centered at `[270, 0, 15]` with size `[170, 130, 30]`.
- `left_guard_rail`: static box centered at `[20, -130, 100]` with size `[300, 18, 160]`.
- `right_guard_rail`: static box centered at `[20, 130, 100]` with size `[300, 18, 160]`.
- `decoy_wall`: static box centered at `[45, 75, 88]` with size `[80, 16, 120]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `steel_ball`
- Static randomization:
  - radius held constant at 20 mm
- Nominal start position: `[-285, -10, 218]`
- Runtime jitter: `[12, 9, 7]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[255, -65, 10]`, max_mm `[335, 65, 80]`
- `forbid_zones`:
  - `pattern_escape_floor`: min_mm `[-170, -150, -5]`, max_mm `[225, 150, 35]`
- `build_zone_mm`: min_mm `[-350, -180, 0]`, max_mm `[360, 180, 260]`

## 5. Simulation Bounds

- min_mm `[-390, -220, -20]`, max_mm `[420, 220, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- The benchmark geometry is static and the chute should remain legible without hidden powered aids or benchmark-owned motion.

## 7. Success Criteria

- Success if `steel_ball` stays within the patterned chute and finishes inside `goal_zone_mm` on `exit_tray`.
- Fail if the ball leaves `simulation_bounds_mm`, escapes through the floor gap, or requires undeclared benchmark motion to complete the descent.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the inlet frame, staggered risers, decoy wall, and outlet tray geometry.
- `benchmark_definition.yaml` mirrors the declared zones, chute fixtures, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
