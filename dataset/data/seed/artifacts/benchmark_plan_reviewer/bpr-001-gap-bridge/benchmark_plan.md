## 1. Learning Objective

Test whether an engineer can bridge or hand off a low-friction cube across a floor gap while respecting a fixed gap forbid volume and purely static benchmark geometry.

## 2. Environment Geometry

- `left_start_deck`: box centered at `[-220, 0, 35]` with size `[180, 180, 70]`.
- `right_goal_deck`: box centered at `[250, 0, 35]` with size `[200, 180, 70]`.
- `bridge_reference_table`: static top surface centered at `[70, 0, 55]` with size `[140, 120, 30]`; this is a passive benchmark fixture, not an actuator.
- `gap_floor_guard`: static lower wall centered at `[10, 0, 20]` with size `[160, 300, 40]` to keep the gap visually explicit.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization: none beyond the declared cube size
- Nominal start position: `[-250, 0, 70]`
- Runtime jitter: `[8, 8, 5]` mm

## 4. Objectives

- `goal_zone`: min `[210, -70, 25]`, max `[320, 70, 120]`
- `forbid_zones`:
  - `floor_gap`: min `[-70, -150, -5]`, max `[90, 150, 45]`
- `build_zone`: min `[-340, -180, 0]`, max `[360, 180, 260]`

## 5. Simulation Bounds

- min `[-380, -220, -20]`, max `[420, 220, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- All benchmark-owned geometry is static; the benchmark should not imply any hidden powered bridge, launcher, or gate.

## 7. Success Criteria

- Success if the cube ends inside `goal_zone` without entering `floor_gap`.
- Fail if the cube leaves `simulation_bounds` or if the benchmark requires undeclared motion to span the gap.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the decks, gap visualization, and passive bridge reference.
- `benchmark_definition.yaml` mirrors the declared zones, decks, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms zero benchmark-side DOFs.
