## 1. Learning Objective

Test whether an engineer can bridge or hand off a low-friction cube across a stepped gap while accounting for a mild platform height mismatch and purely static benchmark geometry.

- **Core Challenge**: A static gap separates `left_start_deck` and `right_goal_deck`; downstream engineering must span the void while keeping `transfer_cube` clear of `floor_gap`.
- **Key Principle**: The benchmark geometry stays fixed; the downstream engineer supplies the crossing structure.
- **Robustness Strategy**: Wide landing decks, the `bridge_reference_table`, and the `gap_floor_guard` make the challenge legible across the declared jitter envelope.

## 2. Environment Geometry

- `left_start_deck`: box centered at `[-236, 0, 33]` with size `[184, 184, 66]`.
- `right_goal_deck`: box centered at `[266, 0, 44]` with size `[200, 180, 76]`.
- `bridge_reference_table`: static top surface centered at `[78, 0, 57]` with size `[144, 116, 26]`; this is a passive benchmark fixture, not an actuator.
- `gap_floor_guard`: static lower wall centered at `[12, 0, 18]` with size `[172, 300, 36]` to keep the gap visually explicit.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization: none beyond the declared cube size
- Nominal start position: `[-250, 0, 79]`
- Runtime jitter: `[7, 7, 5]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[210, -70, 30]`, max_mm `[330, 70, 128]`
- `forbid_zones`:
  - `floor_gap`: min_mm `[-80, -150, -4]`, max_mm `[98, 150, 44]`
- `build_zone_mm`: min_mm `[-340, -180, 0]`, max_mm `[370, 180, 260]`

## 5. Simulation Bounds

- min_mm `[-380, -220, -20]`, max_mm `[420, 220, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- All benchmark-owned geometry is static; the benchmark should not imply any hidden powered bridge, launcher, or gate.

## 7. Success Criteria

- Success if the cube ends inside `goal_zone_mm` without entering `floor_gap`.
- Fail if the cube leaves `simulation_bounds_mm` or if the benchmark requires undeclared motion to span the gap.

## 8. Planner Artifacts

- `todo.md` captures the benchmark-planner checklist for the stepped geometry and payload objective.
- `benchmark_definition.yaml` mirrors the declared zones, decks, guard, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local fixture inventory and confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark evidence scene.
- `submit_benchmark_plan()` persists `.manifests/benchmark_plan_review_manifest.json`.
