## 1. Learning Objective

Test whether an engineer can bridge or hand off a low-friction cube across a floor gap while accounting for an off-axis spawn and a narrower target window within purely static benchmark geometry.

- **Core Challenge**: A static gap separates `left_start_deck` and `right_goal_deck`; downstream engineering must span the void while keeping `transfer_cube` clear of `floor_gap`.
- **Key Principle**: The benchmark geometry stays fixed; the downstream engineer supplies the crossing structure.
- **Robustness Strategy**: Wide landing decks, the `bridge_reference_table`, and the `gap_floor_guard` make the challenge legible across the declared jitter envelope.

## 2. Environment Geometry

- `left_start_deck`: box centered at `[-238, -18, 35]` with size `[184, 180, 70]`.
- `right_goal_deck`: box centered at `[278, 16, 35]` with size `[200, 180, 70]`.
- `bridge_reference_table`: static top surface centered at `[74, -4, 55]` with size `[150, 110, 30]`; this is a passive benchmark fixture, not an actuator.
- `gap_floor_guard`: static lower wall centered at `[18, 0, 18]` with size `[190, 320, 36]` to keep the gap visually explicit.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization: none beyond the declared cube size
- Nominal start position: `[-258, -16, 80]`
- Runtime jitter: `[9, 9, 5]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[232, -66, 25]`, max_mm `[326, 66, 118]`
- `forbid_zones`:
  - `floor_gap`: min_mm `[-90, -156, -4]`, max_mm `[100, 156, 44]`
- `build_zone_mm`: min_mm `[-340, -180, 0]`, max_mm `[380, 180, 260]`

## 5. Simulation Bounds

- min_mm `[-380, -220, -20]`, max_mm `[420, 220, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- All benchmark-owned geometry is static; the benchmark should not imply any hidden powered bridge, launcher, or gate.

## 7. Success Criteria

- Success if the cube ends inside `goal_zone_mm` without entering `floor_gap`.
- Fail if the cube leaves `simulation_bounds_mm` or if the benchmark requires undeclared motion to span the gap.

## 8. Planner Artifacts

- `todo.md` captures the benchmark-planner checklist for the offset geometry and payload objective.
- `benchmark_definition.yaml` mirrors the declared zones, decks, guard, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local fixture inventory and confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark evidence scene.
- `submit_benchmark_plan()` persists `.manifests/benchmark_plan_review_manifest.json`.
