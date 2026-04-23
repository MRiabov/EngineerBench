## 1. Learning Objective

Test whether an engineer can bridge or hand off a low-friction cube across a floor gap while accounting for a skewed divider, a canted mid-beam, and a false bridge block in a fully static benchmark scene.

- **Core Challenge**: A static gap separates `left_start_deck` and `right_goal_deck`; downstream engineering must span the void while keeping `transfer_cube` clear of `floor_gap`.
- **Key Principle**: The benchmark geometry stays fixed; the downstream engineer supplies the crossing structure.
- **Robustness Strategy**: Wide landing decks, the `bridge_reference_table`, the `gap_floor_guard`, and the mid-span divider and beam make the challenge legible across the declared jitter envelope.

## 2. Environment Geometry

- `left_start_deck`: box centered at `[-242, -24, 35]` with size `[186, 170, 70]`.
- `right_goal_deck`: box centered at `[286, 20, 35]` with size `[202, 176, 70]`.
- `bridge_reference_table`: static top surface centered at `[88, -10, 56]` with size `[150, 100, 30]`; this is a passive benchmark fixture, not an actuator.
- `gap_floor_guard`: static lower wall centered at `[24, 0, 19]` with size `[192, 312, 38]` to keep the gap visually explicit.
- `center_divider`: tall divider centered at `[220, 150, 22]` with size `[40, 80, 44]` that splits the span from the positive-Y side.
- `canted_mid_beam`: angled blocker centered at `[152, 170, 48]` with size `[36, 22, 68]` and a positive yaw to make the corridor asymmetrical.
- `false_bridge_block`: decoy block centered at `[150, -58, 13]` with size `[58, 44, 18]` underneath the bridge line.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization: none beyond the declared cube size
- Nominal start position: `[-264, -24, 131]`
- Runtime jitter: `[10, 8, 5]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[236, -60, 25]`, max_mm `[330, 62, 116]`
- `forbid_zones`:
  - `floor_gap`: min_mm `[-96, -160, -4]`, max_mm `[108, 160, 46]`
- `build_zone_mm`: min_mm `[-360, -190, 0]`, max_mm `[390, 190, 270]`

## 5. Simulation Bounds

- min_mm `[-380, -220, -20]`, max_mm `[420, 220, 320]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 120 USD`, `max_weight <= 2200 g`
- All benchmark-owned geometry is static; the benchmark should not imply any hidden powered bridge, launcher, or gate.

## 7. Success Criteria

- Success if the cube ends inside `goal_zone_mm` without entering `floor_gap`.
- Fail if the cube leaves `simulation_bounds_mm` or if the benchmark requires undeclared motion to span the gap.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the decks, divider, beam, gap visualization, and passive bridge reference.
- `benchmark_definition.yaml` mirrors the declared zones, decks, guard, divider, beam, and decoy block.
- `benchmark_assembly_definition.yaml` records the benchmark-local fixture inventory and confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` provides the previewable benchmark evidence scene.
- `submit_benchmark_plan()` persists `.manifests/benchmark_plan_review_manifest.json`.
