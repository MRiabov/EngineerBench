## 1. Learning Objective

Test whether an engineer can bridge or hand off a low-friction cube across a slightly wider floor gap while reading the side-wall framing and preserving a purely static benchmark geometry.

## 2. Environment Geometry

- `left_start_deck`: box centered at `[-232, -6, 35]` with size `[184, 184, 70]`.
- `right_goal_deck`: box centered at `[274, 6, 35]` with size `[198, 176, 70]`.
- `bridge_reference_table`: static top surface centered at `[82, 0, 54]` with size `[156, 112, 28]`; this is a passive benchmark fixture, not an actuator.
- `gap_floor_guard`: static lower wall centered at `[18, 0, 18]` with size `[188, 320, 36]` to keep the gap visually explicit.
- `left_noise_wall`: a passive framing wall centered at `[-330, -150, 34]` with size `[18, 40, 68]`.
- `right_noise_wall`: a passive framing wall centered at `[330, 150, 34]` with size `[18, 40, 68]`.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization: none beyond the declared cube size
- Nominal start position: `[-250, -6, 129]`
- Runtime jitter: `[8, 10, 5]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[228, -72, 25]`, max_mm `[334, 72, 120]`
- `forbid_zones`:
  - `floor_gap`: min_mm `[-88, -160, -4]`, max_mm `[96, 160, 44]`
- `build_zone_mm`: min_mm `[-340, -240, 0]`, max_mm `[390, 240, 260]`

## 5. Simulation Bounds

- min_mm `[-380, -220, -20]`, max_mm `[420, 220, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- All benchmark-owned geometry is static; the benchmark should not imply any hidden powered bridge, launcher, or gate.

## 7. Success Criteria

- Success if the cube ends inside `goal_zone_mm` without entering `floor_gap`.
- Fail if the cube leaves `simulation_bounds_mm` or if the benchmark requires undeclared motion to span the gap.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the decks, gap visualization, bridge reference, and side-wall framing.
- `benchmark_definition.yaml` mirrors the declared zones, decks, guard, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts, including the two passive framing walls, and confirms the benchmark is fully static.
