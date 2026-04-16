---
title: Planner Contract Retention and Restore Implementation
status: migration
agents_affected:
  - benchmark_planner
  - benchmark_plan_reviewer
  - benchmark_coder
  - benchmark_reviewer
  - engineer_planner
  - engineer_plan_reviewer
  - engineer_coder
  - engineer_execution_reviewer
added_at: '2026-04-15T00:00:00Z'
---

# Planner Contract Retention and Restore Implementation

<!-- Migration tracker. This file is the concrete implementation checklist for the retained planner contracts. -->

## Purpose

This migration turns the planner-side contract boundaries we just discussed
into concrete implementation steps.

It covers five retained contracts:

1. the publication prune boundary for technical drawing,
2. the coarse motion-forecast build-safe start and goal-contact assertions,
3. the payload-path rotation-envelope and swept-clearance contract,
4. the payload runtime fail-fast monitor, and
5. the planner inventory exactness and plan-grounding contract.

The implementation must keep those contracts aligned across runtime gates,
seeded workspaces, prompts, docs, and integration coverage. The technical-
drawing companion scripts stay pruned. The COTS carve-out stays narrow:
catalog-backed `part_id` plumbing is the only inventory surface that leaves
the exactness contract.

The source contracts live in:

- [Publication Shape Repository Pruning](../major/publication-shape-repository-pruning.md)
- [Planner Motion Forecast Build and Goal Anchor Contract](./planner-motion-forecast-build-and-goal-anchor-contract.md)
- [Payload Trajectory Rotation Envelope and Swept Clearance Migration](../major/payload-trajectory-rotation-envelope-and-swept-clearance-migration.md)
- [Payload Trajectory Runtime Fail-Fast Monitoring](../major/payload-trajectory-runtime-fail-fast-monitoring.md)
- [Planner Inventory Exactness and Plan Grounding Migration](../major/planner-inventory-exactness-and-plan-grounding.md)

In this repository, every task carries a payload trajectory to goal. The
payload-path contract is therefore mandatory baseline behavior, not an
optional refinement. The two major payload migrations above are part of that
baseline and remain mandatory for this restore.

## Problem Statement

The repository already has the shape of these contracts, but the enforcement
needs to remain explicit and fail-closed after the pruning and contract
split.

1. Planner evidence scripts must stay mandatory and validated at node entry.
2. Coarse `motion_forecast` anchors must continue to prove a build-safe start
   and explicit goal-zone entry/contact at the coarse planner layer.
3. `payload_trajectory_definition.yaml` must remain the higher-resolution
   proof that refines the coarse `motion_forecast`, and it is required for
   every payload-moving handoff.
4. The runtime monitor must keep consuming the approved payload proof instead
   of becoming a separate, looser motion contract, because the proof is a
   mandatory part of the workflow.
5. Planner inventory exactness must continue to enforce exact mentions,
   quantity preservation, and COTS `part_id` matches, while leaving the
   technical-drawing companion path pruned.
6. The seeded evals, integration tests, and prompt guidance must keep the same
   contract so the system does not drift back to the earlier looser shape.

## Proposed Target State

1. `benchmark_plan_evidence_script.py` and `solution_plan_evidence_script.py`
   remain required node-entry artifacts and remain validated with the same
   layout and inventory checks already enforced on `main`.
2. `MotionForecastAnchor`, `PayloadTrajectoryDefinition`, and
   `AssemblyDefinition.motion_forecast` keep the explicit payload-path
   contract, including the coarse planner forecast and the refined,
   mandatory payload-only path proof.
3. `validate_payload_trajectory_definition_yaml()` and
   `validate_payload_trajectory_swept_clearance()` remain the submit-time
   and clearance-proof gates for payload-path handoffs, with
   `payload_trajectory_definition.yaml` required on every engineer-side
   payload handoff.
4. `payload_trajectory_monitor` remains the runtime stop condition for the
   approved payload proof, with explicit failure metadata and observability.
5. `benchmark_plan.md` and `engineering_plan.md` remain exact-mention
   grounded for every non-COTS inventory label, while COTS `part_id` remains
   the narrow catalog-backed carve-out.
6. Technical-drawing companion scripts remain absent from the publication
   bundle and do not come back through this implementation.

## Required Work

### 1. Preserve the planner evidence-script gate

- Keep `benchmark_plan_evidence_script.py` and
  `solution_plan_evidence_script.py` in the shared handoff path contract in
  `shared/script_contracts.py` and the read-only workspace contract in
  `shared/agent_templates/__init__.py`.
- Keep `validate_planner_evidence_script_layout_contract()` in
  `worker_heavy/utils/file_validation.py` as the shape gate for planner
  evidence scripts.
- Keep `ENGINEER_PLANNER_EVIDENCE_LAYOUT_CHECK` in
  `controller/agent/handover_constants.py` and the corresponding node-entry
  custom check in `controller/agent/node_entry_validation.py`.
- Keep the planner evidence scripts mandatory at node entry for the planner
  handoff nodes that already require them.
- Keep the error path fail-closed if the evidence script is missing, unreadable,
  or violates the layout contract.

### 2. Preserve the payload-path proof contract

- Keep `MotionForecastAnchor`, `PayloadTrajectoryDefinition`, and
  `AssemblyDefinition.motion_forecast` typed in `shared/models/schemas.py`.
- Keep the coarse `motion_forecast` endpoint assertions intact: the first
  anchor remains build-zone valid and the terminal anchor or terminal event
  explicitly proves goal-zone entry/contact.
- Keep `validate_payload_trajectory_definition_yaml()` in
  `worker_heavy/utils/file_validation.py` as the submit-time gate for
  payload-path handoffs, and keep it wired for the always-required payload
  proof.
- Keep `_validate_motion_forecast_budget()`,
  `_validate_motion_endpoint_positions()`, and
  `_validate_motion_path_contract()` as the coarse-path enforcement helpers.
- Keep `validate_payload_trajectory_swept_clearance()` in
  `worker_heavy/utils/payload_trajectory_validation.py` as the swept-
  clearance proof.
- Keep the node-entry mirror in `controller/agent/node_entry_validation.py`
  so seeded workspaces fail closed before execution if the payload proof is
  inconsistent or incomplete.
- Keep the retained runtime overlay path
  `render_cad(..., payload_path=True)` as review context only; it does not
  replace the validator.

### 3. Preserve coarse motion-forecast endpoint assertions

- Keep `motion_forecast` sparse and ordered rather than promoting the coarse
  planner layer into a precise replay.
- Keep the first anchor build-zone valid for the moving engineer-owned
  solution and keep the terminal anchor or equivalent terminal event as an
  explicit goal-zone proof.
- Keep the motion forecast bounded by the coarse planner cadence and
  tolerance policy in `config/agents_config.yaml`.
- Keep the coarse forecast separate from `payload_trajectory_definition.yaml`;
  the payload artifact refines the coarse contract rather than replacing it,
  and both artifacts are mandatory baseline surfaces.
- Keep `controller/agent/node_entry_validation.py`,
  `worker_heavy/utils/file_validation.py`, prompt guidance, seed fixtures, and
  integration tests aligned with the same endpoint assertions.
- Keep benchmark-owned motion untouched.

### 4. Preserve runtime fail-fast monitoring

- Keep `worker_heavy/simulation/payload_trajectory_monitor.py` and the loop
  wiring in `worker_heavy/simulation/loop.py`.
- Keep the dedicated failure reason, structured stop payload, and monitor
  policy in `shared/enums.py`, `shared/models/simulation.py`,
  `shared/observability/schemas.py`, and `config/agents_config.yaml`.
- Keep the docs and role guidance aligned with the runtime monitor contract
  in `specs/architecture/simulation-and-rendering.md`,
  `specs/architecture/agents/tools.md`, and
  `specs/architecture/agents/agent-artifacts/payload_trajectory_definition_yaml_acceptance_criteria.md`.
- Keep the runtime monitor fail-closed when payload metadata is missing,
  ambiguous, or inconsistent with the approved proof, because that proof is
  always expected.
- Keep the runtime monitor separate from the static proof path; it consumes
  the proof and does not replace it.

### 5. Preserve planner inventory exactness

- Keep the exact-mention rule for every planner-declared inventory label and
  selected COTS `part_id` in the stage-specific plan file.
- Keep label multiplicity, repeated quantities, and selected-item identity
  checks fail-closed in `controller/agent/node_entry_validation.py`,
  `worker_heavy/utils/file_validation.py`, and `worker_heavy/utils/handover.py`.
- Keep benchmark and engineering flows aligned so the same inventory mismatch
  fails in both branches.
- Keep the COTS carve-out narrow: only catalog-backed `part_id` plumbing is
  removed from the inventory contract, while all non-COTS labels still match
  exactly.
- Keep the planner evidence scripts inventory-grounded, but do not reintroduce
  the technical-drawing companion scripts as part of this implementation.

### 6. Refresh docs, prompts, and starter material

- Keep `specs/architecture/agents/handover-contracts.md` and
  `specs/architecture/agents/artifacts-and-filesystem.md` aligned with the
  retained boundaries.
- Keep `config/prompts.yaml` and `controller/agent/prompt_manager.py`
  aligned with the exact-mention, payload-path, and runtime-monitor guidance.
- Keep `shared/assets/template_repos/**` and `shared/agent_templates/**`
  aligned with the retained handoff contract so the starter workspace teaches
  the same behavior the validators enforce.
- Keep the public architecture docs and the migration docs cross-linked so
  the retained contracts are easy to find from the major and minor migration
  notes.

### 7. Refresh evals, seeds, and integration coverage

- Update `scripts/validate_eval_seed.py` so seeded workspaces fail closed on
  the retained contract boundaries instead of silently accepting looser rows.
- Update `evals/logic/specs.py`, `evals/logic/codex_workspace.py`, and the
  seeded artifact trees so the eval contract matches the retained behavior.
- Update the integration catalog and the narrow integration slices that cover
  planner handoff validation, payload proof validation, runtime monitoring,
  and inventory exactness.
- Keep the seeded rows and mock responses in parity with `main` for the
  retained contracts, and do not add technical-drawing companion scripts back
  into those fixtures. Make sure the payload-path proof surfaces are present
  in every engineer row so the seeded workspace never teaches a payload-less
  contract.

## Restore Checklist Details

Investigation note: the only `main`-only deltas in the node-entry and
file-validation seams are technical-drawing-specific. Those stay excluded by
design. The checklists below cover the retained payload-path, evidence-script
fidelity, and runtime-monitor surfaces that should stay wired. Items marked
`[/]` are already aligned in `main` and stay untouched in this restore.

### 8. Restore the file surfaces

- [x] `controller/agent/node_entry_validation.py`: add the evidence-script
  artifacts to the benchmark and engineer planner contracts, and keep the
  seeded preflight on the same presence checks.
- [/] `engineer_planner_evidence_layout_custom_check()` already exists and
  should remain a layout-only validator; do not add a separate missing-file
  branch there.
- [x] `worker_heavy/utils/file_validation.py`: add the evidence scripts to the
  planner required-file maps and submission-time checks.
- [/] `validate_planner_evidence_script_layout_contract()`,
  `validate_payload_trajectory_definition_yaml()`,
  `validate_payload_trajectory_swept_clearance()`,
  `_validate_motion_forecast_budget()`, `_validate_motion_endpoint_positions()`,
  `_validate_motion_path_contract()`, and
  `validate_component_inventory_exactness()` already exist and should stay
  unchanged.
- [/] `worker_heavy/utils/payload_trajectory_validation.py`,
  `worker_heavy/simulation/payload_trajectory_monitor.py`,
  `shared/models/schemas.py`, `shared/script_contracts.py`, and
  `controller/agent/handover_constants.py` already carry the retained
  contracts and do not need edits in this restore.
- [ ] `payload_trajectory_definition.yaml` becomes a universal required
  artifact in this restore; do not gate it on a moving-parts condition.
- [x] `controller/agent/benchmark_handover_validation.py`: stop filtering the
  missing-file error for `benchmark_plan_evidence_script.py`.
- [x] `controller/agent/tools.py` and `controller/agent/benchmark/tools.py`:
  add the evidence scripts to the submit-time required-file lists.
- [x] `controller/agent/nodes/planner.py` and
  `controller/agent/benchmark/nodes.py`: add the evidence scripts to the node
  `validate_files` lists.

### 9. Restore the functions

- [x] Wire `build_benchmark_node_contracts()` and
  `build_engineer_node_contracts()` so the evidence-script artifacts are
  required at node entry before the layout gate runs.
- [/] `engineer_planner_evidence_layout_custom_check()` already exists and
  should remain layout-only once the artifact is required.
- [ ] Wire `controller/agent/benchmark_handover_validation.py`,
  `controller/agent/tools.py`, `controller/agent/benchmark/tools.py`,
  `controller/agent/nodes/planner.py`, and
  `controller/agent/benchmark/nodes.py` to call
  `validate_planner_evidence_script_layout_contract()` on the required
  evidence-script artifacts.
- [/] `validate_planner_evidence_script_layout_contract()` already exists; the
  caller wiring is the missing piece.
- [ ] Wire `_validate_payload_trajectory_clearance_on_worker()` and
  `validate_seeded_workspace_handoff_artifacts()` so the seeded workspace
  fails closed on missing evidence scripts and missing
  `payload_trajectory_definition.yaml`.
- [ ] Wire engineer-planner handoff validation so
  `validate_payload_trajectory_swept_clearance()` runs against
  `assembly_definition.yaml.motion_forecast` at the `engineer_planner`
  boundary, while `payload_trajectory_definition.yaml` remains the
  engineer-coder refinement validated at its own boundary.
- [/] `validate_payload_trajectory_definition_yaml()` and the
  `validate_precise_path_definition_yaml` compatibility alias already exist
  and should remain unchanged, along with
  `_validate_motion_forecast_budget()`, `_validate_motion_endpoint_positions()`,
  and `_validate_motion_path_contract()`.
- [/] `validate_payload_trajectory_swept_clearance()` and its helper chain
  (`RotationCell`, `_anchor_sample_points()`,
  `_pose_sphere_is_obviously_clear()`, `_exact_pose_checks()`,
  `_validate_cell()`, `model_anchor_for_cell()`) already exist and should
  remain unchanged. The restore keeps the exact build123d volume-intersection
  check between the payload and fixed geometry at checked poses, not just the
  broad-phase envelope pruning.
- [/] `load_payload_trajectory_definition()`, `_resolve_body_names()`,
  `_flatten_first_contacts()`, and `PayloadTrajectoryMonitor` already exist
  and should remain unchanged.
- [/] `validate_component_inventory_exactness()` and the inventory helper path
  already exist and should remain unchanged.

### 10. Add integration coverage

- [ ] Extend `tests/integration/architecture_p0/test_planner_gates.py` with
  regressions that reject a moving engineer handoff when
  `solution_plan_evidence_script.py` is missing or malformed, when
  `assembly_definition.yaml.motion_forecast` omits the build-safe first anchor
  or goal-contact terminal proof, and when the retained inventory exactness
  contract drifts.
- [ ] Extend `tests/integration/architecture_p0/test_node_entry_validation.py`
  with seeded-workspace cases that fail closed on missing evidence scripts,
  mismatched `current_role.json`, and invalid
  `payload_trajectory_definition.yaml` or clearance-proof inputs.
- [ ] Extend `tests/integration/architecture_p0/test_int_008_objectives_validation.py`
  so the build-zone and goal-zone geometry semantics still support the
  endpoint assertions used by the motion-forecast and payload-path contracts.
- [ ] Extend `tests/integration/architecture_p1/test_handover.py` so the
  handoff bundle still contains the retained evidence-script and payload-path
  artifacts, and still omits technical-drawing companions.
- [ ] Extend `tests/integration/architecture_p1/test_benchmark_workflow.py`
  with a benchmark-side evidence-fidelity regression that proves the
  benchmark evidence scene still preserves the approved benchmark labels and
  quantities and remains grounded in `benchmark_plan.md` and
  `benchmark_assembly_definition.yaml`.
- [ ] Extend `tests/integration/architecture_p1/test_engineering_loop.py` with
  an end-to-end engineer run that proves the coarse forecast survives into
  `payload_trajectory_definition.yaml` and that the runtime monitor fails fast
  on a corridor violation with the retained failure reason.
- [ ] Extend `tests/integration/architecture_p1/test_reviewer_evidence.py` so
  the reviewer manifest still exposes the retained planner evidence,
  payload-path proof, and runtime failure metadata.
- [x] Keep `tests/integration/architecture_p0/test_codex_runner_mode.py`
  asserting that the seed templates still advertise
  `benchmark_plan_evidence_script.py` and `solution_plan_evidence_script.py`
  and do not reference any `_technical_drawing.py` companion.
- [ ] Keep `tests/integration/architecture_p0/test_planner_gates.py` and the
  seeded planner workflows aligned with the same evidence-fidelity and
  exactness expectations so plan text, evidence scripts, and YAML remain
  mutually reconstructable.

### 11. Payload-Path Restore Handoff Checklist

Use this checklist to hand off the unconditional payload-path restore to the
next agent without re-explaining the architecture.
The ownership split stays the same: `assembly_definition.yaml.motion_forecast`
remains the planner-authored coarse contract, and
`payload_trajectory_definition.yaml` remains the engineer-coder-authored
refinement that makes the path reviewable at higher resolution. The
`motion_forecast` name is a historical drift; when the prose needs a clearer
term, `coarse_payload_trajectory` is the same planner-owned low-resolution
contract.

- [x] Add a checked-in `payload_trajectory_definition.yaml` scaffold to the
  engineer starter template surface that feeds `load_seed_starter_template_files()`,
- [x] Populate the engineer seed rows under `dataset/data/seed/artifacts/engineer_*`
  with the same payload file, starting with `ec-002-low-friction-cube`, so
  seeded workspaces materialize the scaffold before validation.
- [x] Keep `controller/agent/node_entry_validation.py` fail-closed on the
  engineer coder path for presence only: `payload_trajectory_definition.yaml`
  must exist so the coder can edit it, while geometric completeness stays in
  the submit-time engineer validation path.
- [x] Thread the payload file through the engineer submit/review validation
  surfaces by updating `controller/agent/nodes/coder.py`,
  `controller/agent/nodes/execution_reviewer.py`, and the matching handoff
  constants in `controller/agent/handover_constants.py` so later stages carry
  the engineer-owned proof forward instead of silently dropping it.
- [x] Keep `worker_heavy/utils/file_validation.py` and
  `worker_heavy/utils/payload_trajectory_validation.py` aligned so the
  planner-owned coarse `motion_forecast` is clearance-validated at the
  `engineer_planner` boundary and still gates the engineer-owned precise
  file, while the precise file is only content-validated at the engineer
  coder boundary.
- [x] Make `assembly_definition.yaml.motion_forecast` mandatory for engineer
  handoffs in `worker_heavy/utils/file_validation.py` so the coarse payload
  contract fails closed instead of passing by omission.
- [ ] Keep `worker_heavy/simulation/payload_trajectory_monitor.py` as the
  fail-fast consumer of the approved payload proof, and make missing payload
  metadata, backend mismatch, or corridor drift produce explicit stop
  metadata instead of a silent disable.
- [x] Update `tests/integration/architecture_p0/test_node_entry_validation.py`,
  `tests/integration/architecture_p1/test_engineering_loop.py`, and
  `tests/integration/architecture_p1/test_reviewer_evidence.py` to cover the
  missing-file, malformed-scaffold, and successful-handoff cases for
  `payload_trajectory_definition.yaml`.
- [ ] Keep the public docs in
  `specs/architecture/agents/handover-contracts.md`,
  `specs/architecture/agents/artifacts-and-filesystem.md`,
  `specs/architecture/agents/agent-artifacts/README.md`,
  `specs/architecture/agents/roles-detailed/engineer-plan-reviewer.md`,
  `specs/architecture/simulation-and-rendering.md`,
  `specs/architecture/agents/tools.md`,
  `specs/architecture/agents/roles-detailed/engineer-coder.md`,
  `specs/architecture/agents/agent-artifacts/payload_trajectory_definition_yaml_acceptance_criteria.md`,
  `specs/migrations/major/payload-trajectory-rotation-envelope-and-swept-clearance-migration.md`,
  and `specs/migrations/major/payload-trajectory-runtime-fail-fast-monitoring.md`
  aligned with the same unconditional rule so the starter workspace, runtime
  monitor, and handoff contract all describe the same artifact.

## Non-Goals

- Do not restore `benchmark_plan_technical_drawing_script.py`,
  `solution_plan_technical_drawing_script.py`, or any other
  `_technical_drawing.py` scripts.
- Do not broaden the COTS carve-out beyond catalog-backed `part_id` plumbing.
- Do not relax static payload-path proof or runtime fail-fast monitoring.
- Do not convert the runtime overlay into validation evidence.

## Sequencing

1. Lock the planner evidence-script gate and node-entry checks.
2. Keep the coarse motion-forecast endpoint assertions aligned across schema,
   prompts, seeds, and node entry.
3. Keep the payload-path proof helpers and clearance validator aligned.
4. Keep the runtime monitor and failure payload aligned with the static proof.
5. Keep the inventory exactness checks fail-closed for all non-COTS items.
6. Refresh prompts, docs, starter templates, seeded evals, and integration
   coverage last.

## Acceptance Criteria

1. Planner evidence scripts remain mandatory node-entry artifacts and fail
   closed on missing or malformed layout.
2. Payload-path handoffs continue to require the coarse build-safe start and
   explicit goal-contact forecast, plus the refined precise path and swept-
   clearance validation.
3. Runtime payload monitoring still stops simulation with the retained
   failure reason and structured metadata when the approved proof is no
   longer satisfied.
4. Non-COTS inventory labels and quantities still match exactly across the
   stage-specific plan text, evidence scripts, planner handoff artifacts, and
   the evidence scenes grounded in the approved source plan/YAML contracts.
5. COTS `part_id` remains the only carved-out inventory surface.
6. Technical-drawing companion scripts remain absent from the retained
   bundle.

## File-Level Change Set

The implementation should touch the smallest set of files that enforce the
retained contracts:

- `controller/agent/node_entry_validation.py`
- `worker_heavy/utils/file_validation.py`
- `controller/agent/benchmark_handover_validation.py`
- `controller/agent/tools.py`
- `controller/agent/benchmark/tools.py`
- `controller/agent/nodes/planner.py`
- `controller/agent/benchmark/nodes.py`
- `tests/integration/architecture_p0/test_node_entry_validation.py`
- `tests/integration/architecture_p0/test_planner_gates.py`
- `tests/integration/architecture_p0/test_int_008_objectives_validation.py`
- `tests/integration/architecture_p0/test_codex_runner_mode.py`
- `tests/integration/architecture_p1/test_handover.py`
- `tests/integration/architecture_p1/test_benchmark_workflow.py`
- `tests/integration/architecture_p1/test_engineering_loop.py`
- `tests/integration/architecture_p1/test_reviewer_evidence.py`
