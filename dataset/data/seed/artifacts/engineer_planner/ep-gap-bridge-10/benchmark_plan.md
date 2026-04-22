## 1. Learning Objective

Test whether an engineer can bridge or hand off a low-friction sphere across a narrow floor gap while respecting a fixed gap forbid volume and purely static benchmark geometry.

## 2. Environment Geometry

- `left_start_deck`: box centered at `[-30, 0, 2]` with size `[28, 18, 4]`.
- `right_goal_deck`: box centered at `[30, 0, 2]` with size `[28, 18, 4]`.
- `bridge_reference_table`: static top surface centered at `[0, 0, 9]` with size `[8, 8, 18]`; this is a passive benchmark fixture, not an actuator.
- `gap_floor_guard`: static lower wall centered at `[0, -14, 3]` with size `[18, 4, 6]` to keep the gap visually explicit.

## 3. Input Objective

- Shape: `sphere`
- Label: `transfer_cube`
- Static randomization:
  - radius_mm fixed at `5`
- Nominal start position: `[-30, 0, 24]`
- Runtime jitter: `[2, 2, 1]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[24, -10, 6]`, max_mm `[40, 10, 18]`
- `forbid_zones`:
  - `floor_gap`: min_mm `[-12, -20, -5]`, max_mm `[12, 20, 12]`
- `build_zone_mm`: min_mm `[-60, -30, 0]`, max_mm `[60, 30, 40]`

## 5. Simulation Bounds

- min_mm `[-80, -40, -10]`, max_mm `[80, 40, 60]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 27 USD`, `max_weight <= 30 g`
- All benchmark-owned geometry is static; the benchmark should not imply any hidden powered bridge, launcher, or gate.

## 7. Success Criteria

- Success if the sphere ends inside `goal_zone_mm` without entering `floor_gap`.
- Fail if the sphere leaves `simulation_bounds_mm` or if the benchmark requires undeclared motion to span the gap.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the decks, gap visualization, and passive bridge reference.
- `benchmark_definition.yaml` mirrors the declared zones, decks, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
