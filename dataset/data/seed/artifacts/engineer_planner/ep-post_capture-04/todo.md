# TODO List

## Phase 1: Ground the Handoff

- [ ] Confirm `.manifests/current_role.json` names `engineer_planner`
- [ ] Re-read `benchmark_definition.yaml` and `benchmark_assembly_definition.yaml` for the fixed gap geometry
- [ ] Note the exact `transfer_cube`, `left_start_deck`, `right_goal_deck`, `bridge_reference_table`, and `gap_floor_guard` labels

## Phase 2: Keep The Planner Artifacts Aligned

- [ ] Keep `engineering_plan.md` grounded to `transfer_cube` and the 280 mm gap span
- [ ] Keep `assembly_definition.yaml` aligned with the same part names, costs, and coarse trajectory
- [ ] Keep `solution_plan_evidence_script.py` as a readable preview of the four-part bridge assembly

## Phase 3: Cross-Check Coherence

- [ ] Verify the part dimensions, volumes, and totals match across the plan and YAML
- [ ] Verify the first trajectory anchor starts at the payload spawn position
- [ ] Verify the last trajectory anchor ends at the goal-zone center
- [ ] Verify the evidence scene shows the bridge deck, anchor blocks, and exit lip

## Phase 4: Handoff Ready

- [ ] Leave benchmark-owned files unchanged
- [ ] Keep the workspace starter-like rather than solved
- [ ] Do not add downstream implementation work to this planner seed
