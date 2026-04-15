---
title: Inherited Validation Contract Lattice Across First-Class Agent Nodes
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

# Inherited Validation Contract Lattice Across First-Class Agent Nodes

<!-- Major migration. Exit validation and node-entry validation become one inherited contract lattice. -->

## Purpose

This migration makes node-entry validation and node-exit validation share one
inherited contract lattice across the full first-class orchestration chain.

The chain is the `AgentName` set that already participates in controller and
worker routing:

- `benchmark_planner`
- `benchmark_plan_reviewer`
- `benchmark_coder`
- `benchmark_reviewer`
- `engineer_planner`
- `engineer_plan_reviewer`
- `engineer_coder`
- `engineer_execution_reviewer`

The lattice is stage-aware, but it is not ad hoc. A node's exit produces a
deterministic contract snapshot. The next node's entry rehydrates that same
snapshot, re-proves it against the current workspace, and fails closed if any
relevant input drifted.

The contract covers geometry, stage-appropriate physical evidence, manifest
freshness, and the shared scene-builder contract when benchmark-owned payload
geometry is involved. It does not apply to `skill_agent`, `git_agent`, or
`journalling_agent`, because those are not first-class graph transitions today.

This migration composes with:

- [Validation on Light Worker](./validation-on-light-worker.md)
- [Shared Scene Builder for Static Preview and Physics](./../minor/shared-scene-builder-static-preview-physics.md)
- [Role Scoped Submission Tool Split](./../minor/role-scoped-submission-tool-split.md)
- the payload-trajectory migrations that already define motion and clearance
  semantics

It does not replace those migrations. It extends the same fail-closed logic
across every node boundary.

## Problem Statement

The repository already has the pieces of the contract, but they are split by
layer and therefore can drift.

1. Worker-side validation owns the geometry gate, but controller-side node
   entry owns the routing gate.
2. Submit-time gating trusts a persisted validation file plus a script hash,
   but that is not enough to prove the current workspace still matches the
   validated workspace.
3. Reviewer entry already checks stage-specific manifests and evidence, but the
   checks are not organized as one inherited lattice across the whole chain.
4. The node registry is written as a set of family-specific maps and custom
   checks, not as one shared transition contract with stage policy layered on
   top.
5. The persisted validation record does not carry a full contract fingerprint
   for all artifacts that affect the next node's admissibility.
6. The current shape allows a workspace to validate once and then become stale
   before the next node starts.
7. The low-friction cube class of failure demonstrates the bug class directly:
   a benchmark can validate before the runtime-spawned payload is inserted, but
   the scene is still invalid once physics applies the payload geometry.
8. The current split is especially risky for benchmark-to-engineer handoff,
   because the benchmark reviewer is the last benchmark gate before the engineer
   planner consumes the package.
9. Utility agents are not part of this graph and must remain out of scope.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `shared/enums.py` | `AgentName` lists the first-class nodes and the utility agents together, but there is no shared transition metadata or contract lattice. | The orchestration graph needs a typed, stage-aware contract model, not just enum names. |
| `controller/agent/node_entry_validation.py` | Builds separate benchmark and engineer node contracts with per-node custom checks and separate artifact lists. | Node entry should derive from one inherited transition model, not a hand-written registry of mostly similar rules. |
| `worker_heavy/utils/validation.py` | Owns the static geometry gate, including label checks, pairwise intersections, build-zone containment, parent-fixed checks, top-level location checks, and payload start-clearance checks. | The geometry checks are correct but isolated; the same kernel must feed both exit and entry gates. |
| `shared/utils/agent/__init__.py` | Exposes `validate_benchmark()`, `validate_engineering()`, and `submit_*` wrappers that can diverge in freshness semantics. | The public helpers need a shared contract snapshot, not just a success boolean. |
| `worker_heavy/utils/handover.py` | Submit-time gating verifies `validation_results.json` and `script_sha256`, but it does not prove the full contract inputs are unchanged. | A stale workspace can still slip through if the changed files are not part of the record. |
| `shared/workers/schema.py` | `ValidationResultRecord` stores `script_sha256` and `verification_result`, while `ReviewManifest` and `PlanReviewManifest` carry stage-specific data but not a shared inherited fingerprint. | The persisted record needs a deterministic freshness contract for the next node. |
| `controller/agent/review_handover.py` and `controller/agent/benchmark_handover_validation.py` | Reviewer entry checks manifests, evidence, and handoff files, but not as one shared lattice that mirrors the exit-side contract. | Entry-side review must be the same contract family as exit-side validation, only stricter. |
| `specs/migrations/minor/shared-scene-builder-static-preview-physics.md` | Fixes scene parity between preview and physics, including payload geometry reconstruction. | This migration must extend that parity to validation freshness and node transitions. |
| `specs/architecture/agents/handover-contracts.md` and `specs/architecture/agents/tools.md` | Describe stage contracts and tools separately, but not one inherited contract graph spanning every first-class node. | The docs need to describe the chain as one strict lattice so the contract is not inferred by accident. |
| `dataset/data/seed/artifacts/engineer_coder/ec-002-low-friction-cube` | Represents the exact bug class where a scene can pass an earlier validation pass and still be invalid once the runtime payload is inserted. | The migration exists to eliminate this failure mode across the whole graph. |

## Definitions

1. `exit contract` means the exact set of artifacts, geometry state, and stage
   evidence a node must produce before the next node may consume the workspace.
2. `entry contract` means the exact set of artifacts, geometry state, and
   stage evidence the downstream node must observe before node entry is
   admitted.
3. `contract snapshot` means the canonical, typed representation of the exit
   contract that is persisted or reconstructed at handoff.
4. `contract fingerprint` means the deterministic hash or equivalent canonical
   signature derived from the contract snapshot and its source inputs.
5. `physical evidence` means the stage-appropriate simulation, render, review,
   or motion evidence that proves the workspace still matches the contract.
6. `first-class agent node` means one of the eight `AgentName` values listed in
   the frontmatter.
7. `utility agent` means `skill_agent`, `git_agent`, or `journalling_agent`.
   Those agents are not in scope for this migration.

## Proposed Target State

1. The shared validation lattice is the canonical contract for all first-class
   node transitions.
2. Every first-class node exit produces a typed contract snapshot and a
   contract fingerprint.
3. Every downstream first-class node entry reuses that same snapshot and
   fingerprint, then adds only stage-specific requirements.
4. Entry validation is always at least as strict as the previous node's exit
   validation. It may be stricter, but it may not silently become looser.
5. Geometry checks and physical-evidence checks are both part of the lattice.
   The code path that validates them can differ by stage, but the contract
   semantics do not.
6. `benchmark_reviewer` entry is a strict superset of
   `benchmark_coder` exit, including benchmark geometry checks and benchmark-
   appropriate physical evidence freshness.
7. `engineer_execution_reviewer` entry is a strict superset of
   `engineer_coder` exit, including engineer geometry checks and engineer-
   appropriate physical evidence freshness.
8. `benchmark_plan_reviewer` and `engineer_plan_reviewer` are also part of the
   same lattice. They do not bypass freshness checks simply because they sit
   between planning and coding.
9. The bridge transition from `benchmark_reviewer` to `engineer_planner` is
   first-class. The engineer planner must prove that the benchmark reviewer
   package is current before the engineer graph starts.
10. Planner root nodes still participate in the lattice. Their root contract is
    the seeded workspace state plus the current-role manifest, and they emit the
    first fingerprint for later nodes to inherit.
11. The submit and handoff gates compare the current workspace against the last
    recorded fingerprint. A present `validation_results.json` file is not
    enough on its own.
12. The lattice stays typed. Stage-specific records should inherit from shared
    base models or fragments instead of collapsing into one permissive schema.
13. The utility agents remain excluded.

## Design Notes

1. The fingerprint must be stage-aware and canonical. A single global workspace
   hash is too coarse and will cause false invalidations.
2. The fingerprint must cover every file that materially affects the next
   node's admissibility. If a file changes the geometry, the stage evidence, or
   the current role, it belongs in the snapshot.
3. Modification time is not sufficient. The contract needs content-based
   freshness, not filesystem guesswork.
4. The shared scene-builder contract is part of the snapshot whenever benchmark
   payload geometry is part of the scene. That is what prevents the benchmark
   scene from validating before payload insertion and then drifting into an
   invalid physics state.
5. The controller-side gate and the worker-side gate should call the same
   shared contract evaluator. The only difference should be stage policy and
   artifact set.
6. Review-stage manifests are not the sole source of truth. They are one piece
   of the contract snapshot, alongside the authored script, the YAML inputs, the
   current-role manifest, and the latest stage evidence.
7. A missing or ambiguous fingerprint input fails closed. The lattice should
   never infer that a workspace is still valid just because one downstream file
   happened to remain present.
8. Planner and reviewer stages should use the same lattice shape as coder and
   execution-reviewer stages, but the evidence they require is stage-specific.
   Planning stages prove handoff consistency and motion feasibility; coder and
   review stages prove implementation and runtime evidence.
9. The lattice should be implemented as typed schema objects, not as ad hoc
   dictionaries. That keeps the contract explicit and easier to diff.
10. The new contract should be readable from the persisted artifacts. Later
    entry gates must be able to tell why the previous node passed without
    reconstructing hidden state from logs.

## Required Work

### 1. Introduce shared contract models

- Define a typed contract snapshot model in shared code.
- Define a typed contract fingerprint model that is derived from the snapshot
  and the exact stage inputs.
- Keep the model stage-aware so benchmark and engineer families can share the
  same structure without sharing the same semantics.
- Include the current-role manifest and the relevant session or episode
  identifiers in the snapshot so entry validation is tied to the active
  workspace.

### 2. Refactor node transition policy

- Derive the first-class node transition graph from `AgentName` plus stage
  family policy instead of maintaining two mostly independent registries.
- Encode the `benchmark_reviewer -> engineer_planner` bridge as a first-class
  transition with explicit freshness checks.
- Keep the utility agents out of the registry so the lattice does not widen to
  non-graph helpers.
- Make root nodes emit the initial fingerprint that later nodes inherit.

### 3. Unify exit and entry validation

- Route the benchmark and engineer `validate_*()` helpers through the same
  shared contract evaluator that node-entry validation uses.
- Make benchmark reviewer entry and engineer execution reviewer entry consume
  the same geometry checks that their corresponding coder exits already use.
- Add stage-appropriate physical evidence checks on top of the shared geometry
  checks rather than replacing them.
- Ensure planner and plan-reviewer stages also use the shared contract
  evaluator, with plan-specific evidence requirements layered on top.

### 4. Extend persisted records and handoff gates

- Extend `ValidationResultRecord` with a contract fingerprint and the minimal
  set of validated input hashes needed to prove freshness.
- Extend the reviewer-manifest and plan-review-manifest contracts with the same
  fingerprint or equivalent typed freshness metadata.
- Make submit and handoff gates compare the current workspace to the recorded
  fingerprint before accepting a node transition.
- Reject stale workspaces even when the old validation record still exists and
  says success.

### 5. Update docs, skills, and seeded regressions

- Update the handover-contract docs so the lattice is described as one
  inherited chain instead of separate one-off gates.
- Update the tool docs and role docs so benchmark and engineer roles describe
  the same contract family.
- Update the artifact acceptance docs for validation results and reviewer
  manifests so the new fingerprint is part of the persisted contract.
- Refresh the seeded workspaces and negative-path integration coverage that
  currently assume one validation pass is enough to carry a workspace through
  the next node.

## Non-Goals

- Do not add `skill_agent`, `git_agent`, or `journalling_agent` to the
  contract lattice.
- Do not replace stage-specific evidence semantics with one generic success
  metric.
- Do not relax geometry validation or treat earlier success as perpetual.
- Do not change simulation backend selection, render backend selection, or the
  shared scene-builder geometry contract itself.
- Do not turn node-entry checks into warnings, soft reroutes, or best-effort
  suggestions.
- Do not collapse benchmark and engineer contracts into one permissive schema.

## Sequencing

The safest implementation order is:

1. Define the shared contract snapshot and fingerprint models.
2. Refactor the exit-side validators to emit the same snapshot the entry-side
   gates will consume.
3. Teach node-entry validation to compare the current workspace against the
   recorded fingerprint and to re-run the stage-appropriate geometry and
   physical checks.
4. Extend persisted validation and review records so freshness can survive
   submission and review boundaries.
5. Update architecture docs, role docs, artifact acceptance docs, and seeded
   regressions.

## Acceptance Criteria

1. Every first-class node transition uses the shared validation lattice.
2. A workspace that mutates after validation but before the next node starts is
   rejected by the next node entry.
3. `benchmark_reviewer` entry is a strict superset of
   `benchmark_coder` exit, including geometry and benchmark-appropriate
   physical evidence freshness.
4. `engineer_execution_reviewer` entry is a strict superset of
   `engineer_coder` exit, including geometry and engineer-appropriate
   physical evidence freshness.
5. Planner and plan-reviewer transitions are covered by the same lattice and do
   not bypass freshness checks.
6. The low-friction cube bug class is rejected: a benchmark scene that passed
   before runtime payload insertion cannot still be admitted once the current
   workspace no longer matches the recorded contract.
7. The persisted validation and review artifacts carry enough fingerprint data
   to detect stale handoffs without guesswork.
8. Utility agents remain excluded.
9. The docs and integration coverage all describe the same contract behavior.

## Detailed Implementation Checklist

### Contract snapshot and fingerprinting

- [ ] Add `shared/validation_contracts.py` or an equivalent shared module for
      typed contract snapshots and fingerprints.
- [ ] Define a `ValidationContractSnapshot` model that records the active
      `AgentName`, transition family, session or episode identifiers, current
      role, and the exact files that make the next node admissible.
- [ ] Define a `ValidationContractFingerprint` model derived from the snapshot
      and normalized file digests.
- [ ] Keep the snapshot deterministic and order-stable so path ordering or
      dictionary ordering does not change the fingerprint.
- [ ] Include `.manifests/current_role.json` in every snapshot because node
      entry already treats it as authoritative role metadata.
- [ ] Add helpers for computing canonical SHA-256 digests over the files that
      each transition actually consumes.
- [ ] Keep the fingerprint typed and stage-aware rather than collapsing all
      first-class nodes into one global workspace hash.

### Transition matrix

| Transition | Freshness inputs that must be covered |
| -- | -- |
| `benchmark_planner -> benchmark_plan_reviewer` | `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_plan_evidence_script.py`, `manufacturing_config.yaml`, `.manifests/current_role.json` |
| `benchmark_plan_reviewer -> benchmark_coder` | benchmark plan review manifest, approved planner package files, `.manifests/current_role.json` |
| `benchmark_coder -> benchmark_reviewer` | `benchmark_script.py`, `validation_results.json`, `simulation_result.json`, `renders/.../render_manifest.json`, benchmark review manifest, `.manifests/current_role.json` |
| `benchmark_reviewer -> engineer_planner` | benchmark review manifest, benchmark handoff evidence package, `.manifests/current_role.json` |
| `engineer_planner -> engineer_plan_reviewer` | `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, `benchmark_assembly_definition.yaml`, `solution_plan_evidence_script.py`, `manufacturing_config.yaml`, `.manifests/current_role.json` |
| `engineer_plan_reviewer -> engineer_coder` | engineering plan review manifest, approved planner package files, `.manifests/current_role.json` |
| `engineer_coder -> engineer_execution_reviewer` | `solution_script.py`, `validation_results.json`, `simulation_result.json`, `renders/.../render_manifest.json`, engineering execution handoff manifest, `.manifests/current_role.json` |

### Runtime and node-entry plumbing

- [ ] Refactor `controller/agent/node_entry_validation.py` so
      `build_benchmark_node_contracts()` and `build_engineer_node_contracts()`
      consume the same inherited transition model instead of maintaining two
      mostly independent registries.
- [ ] Keep `evaluate_node_entry_contract()` as the central node-entry gate, but
      make it compare the current workspace against the stored fingerprint
      before it accepts the stage-specific custom checks.
- [ ] Make root planner nodes emit the first fingerprint for their family so
      later nodes can inherit the same contract lineage.
- [ ] Carry the benchmark reviewer to engineer planner bridge through the same
      transition model instead of treating it as a one-off post-benchmark
      exception.
- [ ] Keep `validate_seeded_workspace_handoff_artifacts()` on the same shared
      kernel so benchmark and engineer seed validation do not drift from node
      entry.
- [ ] Make `validate_benchmark()` and `validate_engineering()` call the same
      shared geometry and evidence kernel that node-entry validation uses.
- [ ] Preserve `_validate_moved_object_start_clearance()` as the canonical
      payload-overlap check and ensure the shared scene-builder constructor is
      the only geometry source for that check.

### Freshness and handoff plumbing

- [ ] Extend `ValidationResultRecord` with a contract fingerprint and the
      minimum set of validated input hashes required to prove freshness.
- [ ] Extend `ReviewManifest` and `PlanReviewManifest` with the same freshness
      metadata or an explicit typed equivalent.
- [ ] Keep `PlanReviewManifest.artifact_hashes` as the plan-review freshness
      source, but require downstream gates to compare it against the live
      fingerprint instead of trusting presence alone.
- [ ] Update `worker_heavy/utils/handover.py::submit_for_review()` so a current
      `validation_results.json` file is not enough unless its recorded hashes
      still match the workspace.
- [ ] Update `shared/utils/agent/__init__.py::_submit_for_review_submission()`
      and `controller/clients/worker.py::submit()` to pass the current
      fingerprint through controller and worker transports.
- [ ] Thread the fingerprint through
      `controller/clients/worker.py::validate()`,
      `controller/clients/worker.py::simulate()`,
      `controller/clients/worker.py::verify()`, and
      `controller/clients/worker.py::submit()`.
- [ ] Update `controller/agent/review_handover.py::validate_reviewer_handover()`
      so it compares the review manifest, validation record, simulation record,
      and current workspace against the same lineage.
- [ ] Update `controller/agent/review_handover.py::validate_plan_reviewer_handover()`
      so plan-review entry rejects stale planner artifacts even when the old
      manifest still exists.
- [ ] Update `controller/agent/review_handover.py::validate_approved_benchmark_bundle()`
      so benchmark approval consumes freshness metadata from the benchmark
      reviewer package, not just `review_manifest.script_sha256`.

### Geometry and physical evidence

- [ ] Keep geometry validation fail-closed on label collisions, pairwise solid
      intersections, build-zone violations, parent-fixed contract violations,
      top-level translation misuse, and payload start-clearance overlap.
- [ ] Make the same geometry kernel available to preview, physics, validation,
      and handoff checks so the benchmark payload cannot be inserted differently
      in each path.
- [ ] Keep benchmark execution review benchmark-neutral, but require benchmark
      motion evidence freshness when benchmark-owned moving fixtures exist.
- [ ] Keep engineer execution review solve-oriented, and require the latest
      validation and simulation evidence to match the current workspace
      fingerprint before approval.
- [ ] Keep planner and plan-reviewer stages tied to their own motion or
      handoff evidence so they do not bypass freshness checks simply because
      they are pre-implementation stages.

### Docs, artifact acceptance, and roles

- [ ] Update `specs/architecture/agents/handover-contracts.md` so the handoff
      graph is described as one inherited lattice instead of separate validator
      islands.
- [ ] Update `specs/architecture/agents/tools.md` so `validate_*()`,
      `simulate_*()`, and `submit_*()` are described as contract-aware wrappers
      over the same freshness model.
- [ ] Update `specs/migrations/minor/role-scoped-submission-tool-split.md` or
      its follow-on docs if any remaining generic submission wording still
      appears in the dependency chain for this migration.
- [ ] Update `specs/architecture/agents/definitions-of-success-and-failure.md`
      so stale-workspace failure is explicit and belongs to the same taxonomy as
      geometry and physical-evidence failure.
- [ ] Update `specs/architecture/simulation-and-rendering.md` where the shared
      scene-builder contract interacts with validation freshness.
- [ ] Update `specs/architecture/agents/agent-artifacts/validation_results_json_acceptance_criteria.md`
      to require freshness metadata, not only pass/fail state.
- [ ] Update `specs/architecture/agents/agent-artifacts/reviewer_manifest_acceptance_criteria.md`
      so reviewer entry is tied to the live fingerprint and not just the
      manifest filename.
- [ ] Update the benchmark and engineering execution review acceptance docs so
      the checklist language matches the new fingerprint-based gate.
- [ ] Update role docs for benchmark coder, benchmark reviewer, engineer
      coder, and engineer execution reviewer so the same contract lineage is
      visible to the agents that produce or consume the artifacts.

### Tests and seeded regressions

- [ ] Add a stale-after-validation regression in
      `tests/integration/architecture_p0/test_node_entry_validation.py` where
      the workspace mutates after a valid check and the next node is rejected.
- [ ] Add a current-role mismatch regression where the files are correct but
      `.manifests/current_role.json` names the wrong node.
- [ ] Add a benchmark payload overlap regression in
      `tests/integration/architecture_p0/test_int_024_runtime_execute.py` or
      `tests/integration/architecture_p0/test_architecture_p0.py` that proves
      the shared payload-clearance check rejects the low-friction cube class of
      failure.
- [ ] Add a benchmark handoff staleness regression in
      `tests/integration/architecture_p1/test_handover.py`.
- [ ] Add a benchmark review freshness regression in
      `tests/integration/architecture_p1/test_benchmark_workflow.py`.
- [ ] Add an engineer execution reviewer freshness regression in
      `tests/integration/architecture_p1/test_engineering_loop.py` and
      `tests/integration/architecture_p1/test_reviewer_evidence.py`.
- [ ] Refresh `dataset/data/seed/artifacts/**` for `ec-002-low-friction-cube`
      and any similar seeds where validation can pass before payload insertion
      but fail once the runtime-spawned payload is actually present.
- [ ] Refresh mock responses or generated manifests that still assume
      `validation_results.json` plus `script_sha256` is sufficient freshness.

### Sequencing guardrails

- [ ] Implement the fingerprint and snapshot models before widening the node
      registry.
- [ ] Keep the geometry kernel and the freshness kernel in lockstep; do not
      land one without the other.
- [ ] Keep the role-scoped submission helper names as canonical inputs to the
      new transition lattice. Do not introduce any new generic submission
      helper names.
- [ ] Update the submit and handoff gates before refreshing seeds so stale
      states fail closed immediately.
- [ ] Run the narrowest relevant integration slice first and widen only after
      the freshness contract is stable.

## File-Level Change Set

- `controller/agent/node_entry_validation.py`
- `controller/agent/benchmark_handover_validation.py`
- `controller/agent/review_handover.py`
- `controller/api/routes/script_tools.py`
- `controller/middleware/remote_fs.py`
- `controller/clients/worker.py`
- `controller/agent/handover_constants.py`
- `shared/enums.py`
- `shared/utils/agent/__init__.py`
- `shared/workers/schema.py`
- `shared/models/schemas.py`
- `shared/validation_contracts.py`
- `worker_heavy/utils/validation.py`
- `worker_heavy/utils/handover.py`
- `worker_heavy/simulation/builder.py`
- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/tools.md`
- `specs/architecture/agents/definitions-of-success-and-failure.md`
- `specs/architecture/simulation-and-rendering.md`
- `specs/architecture/agents/agent-artifacts/validation_results_json_acceptance_criteria.md`
- `specs/architecture/agents/agent-artifacts/reviewer_manifest_acceptance_criteria.md`
- `specs/architecture/agents/agent-artifacts/benchmark_execution_review_yaml_acceptance_criteria.md`
- `specs/architecture/agents/agent-artifacts/engineering_execution_review_yaml_acceptance_criteria.md`
- `specs/architecture/agents/agent-artifacts/benchmark_plan_review_yaml_acceptance_criteria.md`
- `specs/architecture/agents/agent-artifacts/engineering_plan_review_yaml_acceptance_criteria.md`
- `tests/integration/architecture_p0/test_node_entry_validation.py`
- `tests/integration/architecture_p1/test_handover.py`
- `tests/integration/architecture_p1/test_benchmark_workflow.py`
- `tests/integration/architecture_p1/test_engineering_loop.py`
- `tests/integration/architecture_p1/test_reviewer_evidence.py`
- `dataset/data/seed/artifacts/**`
