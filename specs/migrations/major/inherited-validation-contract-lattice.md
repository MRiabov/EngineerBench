---
title: Validation Parity and Seed Regeneration Across First-Class Agent Nodes
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

# Validation Parity and Seed Regeneration Across First-Class Agent Nodes

<!-- WON'T DO: this migration is over-scoped for the original seed-drift problem. Do not continue the freshness/contract-lattice expansion as a core initiative. -->

<!-- Major migration. One shared validation kernel plus deterministic seed regeneration; freshness is not the correctness mechanism. -->

## Purpose

This migration removes the split between exit validation and node-entry
validation across the first-class orchestration chain.

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

The goal is simple:

- the same validation kernel runs at node exit and node entry;
- derived seed eval artifacts are regenerated from canonical source inputs
  instead of being hand-maintained until they drift;
- a workspace that passes once but changes before the next node is rejected
  by the next node entry.

The governing rule is monotonic: if a workspace does not satisfy a node's
validation contract at one stage, it must not be admitted by any later node
unless the workspace is changed so that the contract actually passes.

The shared contract is the validation kernel itself:

- geometry checks
- payload-clearance checks
- stage-appropriate physical or review evidence checks
- plan-quality checks where the stage already requires them

Freshness metadata is not the correctness mechanism. If any freshness data
exists, it is only supporting metadata for regeneration or diagnostics.
Correctness comes from rerunning validation on the current workspace.

This migration composes with:

- [Validation on Light Worker](./validation-on-light-worker.md)
- [Shared Scene Builder for Static Preview and Physics](./../minor/shared-scene-builder-static-preview-physics.md)
- [Role Scoped Submission Tool Split](./../minor/role-scoped-submission-tool-split.md)
- the payload-trajectory migrations that already define motion and clearance
  semantics

It does not replace those migrations. It extends the same fail-closed logic
across every node boundary and every generated seed bundle.

## Validation Parity Core

1. The worker-side exit path and the controller-side node-entry path both call
   the same shared validation kernel.
2. The shared validation kernel performs geometry checks, payload-clearance
   checks, and stage-appropriate physical or review-evidence checks.
3. For plan-reviewer transitions, the node entry uses the same contract that
   `submit_plan()` already validates for the corresponding family.
4. Coder exits and reviewer entries are not allowed to diverge into separate
   notions of “validated enough”. They must both validate the current
   workspace against the same substantive contract.
5. A workspace that fails at one stage must not be accepted at a later stage
   without first changing the workspace so the shared contract passes.

## Seed Regeneration Contract

1. Seeded workspaces and their derived artifacts are generated from canonical
   source files.
2. When the source contract changes, the seed materialization path refreshes
   the derived artifacts rather than preserving a stale hand-edited copy.
3. The migration does not require a separate freshness subsystem to make this
   safe. The shared validation kernel is the correctness mechanism.
4. Any metadata retained for provenance or diagnostics is secondary to the
   validation result.

## Problem Statement

The repository already has the pieces of the contract, but they are split by
layer and therefore can drift.

1. Worker-side validation owns the authoritative geometry and physical
   evidence kernel, but controller-side node entry does not yet invoke that
   kernel uniformly.
2. Submit-time gating and review handoff still trust persisted artifacts in
   some paths instead of rerunning the same kernel on the current workspace.
3. Seeded workspaces and mock responses are hand-maintained across many files,
   so source changes can leave derived eval artifacts stale.
4. A benchmark can pass an earlier validation step when only the authored
   fixtures are present, but still be invalid once the runtime-spawned payload
   is inserted. The failure happens when the payload's declared start pose
   overlaps benchmark-owned geometry, so exit validation and node-entry
   validation must both run the same payload-clearance check against the
   current workspace.
5. The current split is especially risky for benchmark-to-engineer handoff,
   because the benchmark reviewer is the last benchmark gate before the
   engineer planner consumes the package.
6. Utility agents are not part of this graph and must remain out of scope.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `worker_heavy/utils/validation.py` | Owns the authoritative geometry and physics kernel, including label checks, pairwise intersections, build-zone containment, parent-fixed checks, top-level location checks, and payload start-clearance checks. | The kernel is correct but isolated; the same kernel must feed both exit and entry gates. |
| `controller/agent/node_entry_validation.py` | Builds separate benchmark and engineer node contracts with per-node custom checks and separate artifact lists. | Node entry should replay one inherited validation kernel, not a hand-written registry of mostly similar rules. |
| `controller/agent/review_handover.py` and `controller/agent/benchmark_handover_validation.py` | Reviewer entry enforces stage-specific handoff checks, but the transition lattice is still fragmented. | Entry-side review must use the same kernel family as exit-side validation, only with stage-specific evidence layered on top. |
| `shared/agent_templates/codex/scripts/submit_plan.py` | Already validates and writes plan-review handoff manifests for benchmark and engineer families. | `submit_plan()` should stay aligned with the same validation kernel that node entry uses. |
| `specs/architecture/agents/handover-contracts.md` and `specs/architecture/agents/tools.md` | Describe stage contracts and tools separately, but not one inherited contract graph spanning every first-class node. | The docs need to describe one shared validation contract so the behavior is not inferred by accident. |

## Definitions

1. `exit contract` means the exact set of artifacts, geometry state, and stage
   evidence a node must produce before the next node may consume the
   workspace.
2. `entry contract` means the exact set of artifacts, geometry state, and
   stage evidence the downstream node must observe before node entry is
   admitted.
3. `validation kernel` means the shared geometry, payload-clearance, and
   stage-appropriate evidence checks that run on both exit and entry.
4. `derived seed artifact` means a file in `dataset/data/seed/**` or a
   generated mock-response bundle that is produced from canonical source files
   rather than authored independently.
5. `first-class agent node` means one of the eight `AgentName` values listed in
   the frontmatter.
6. `utility agent` means `skill_agent`, `git_agent`, or `journalling_agent`.
   Those agents are not in scope for this migration.

## Proposed Target State

01. The shared validation lattice is the canonical contract for all first-
    class node transitions.
02. Every first-class node exit validates the current workspace against the
    shared kernel.
03. Every downstream first-class node entry replays the same kernel against
    the current workspace, then adds only stage-specific requirements.
04. Entry validation is always at least as strict as the previous node's exit
    validation. It may be stricter, but it may not silently become looser.
05. Geometry checks, payload-clearance checks, and physical or review-evidence
    checks are all part of the shared validation kernel.
06. `benchmark_plan_reviewer` and `engineer_plan_reviewer` use the same
    contract as `submit_plan()` for their respective families.
07. `benchmark_reviewer` entry is a strict superset of
    `benchmark_coder` exit, including benchmark geometry checks and benchmark-
    appropriate evidence.
08. `engineer_execution_reviewer` entry is a strict superset of
    `engineer_coder` exit, including engineer geometry checks and engineer-
    appropriate evidence.
09. Seed materialization regenerates derived eval artifacts from canonical
    inputs when the source contract changes.
10. The utility agents remain excluded.

## Design Notes

01. The shared validation kernel is the canonical source of truth.
02. The shared scene-builder constructor is the source of benchmark payload
    geometry for validation and preview.
03. Deterministic regeneration is preferred to hand-editing derived seeds.
04. Stage-specific evidence layers on top of the shared kernel; it does not
    replace it.
05. Missing or ambiguous inputs fail closed.
06. The seed-maintenance workflow should treat generated artifacts as
    disposable outputs that can be recreated from source contracts.

## Geometry Validation Core

1. The static geometry kernel in `worker_heavy/utils/validation.py` is the
   canonical geometry gate for the migration.
2. The geometry kernel fails closed on label collisions, pairwise solid
   intersections, build-zone violations, parent-fixed contract violations,
   top-level translation misuse, and payload start-clearance overlap.
3. The shared scene-builder constructor is the only source of benchmark
   payload geometry for preview, physics, validation, and handoff checks.
4. `benchmark_coder` exit and `benchmark_reviewer` entry use the same payload
   geometry source so the runtime payload overlap failure is rejected before
   and after insertion.
5. `engineer_coder` exit and `engineer_execution_reviewer` entry use the same
   geometry kernel for engineer-owned assembly geometry and evidence bundles.
6. Planner and plan-reviewer stages do not get a separate geometry path.
   They reuse the same kernel through the shared contract lattice and then
   layer stage-specific evidence on top.

## Required Work

### 1. Extract the shared validation kernel

- Define a shared validation kernel in shared code for geometry, payload
  clearance, and stage-specific evidence checks.
- Make both worker exit validation and controller node entry call that same
  kernel instead of maintaining separate checks that merely overlap.
- Keep the shared scene-builder constructor as the only benchmark payload
  geometry source used by the kernel.
- Keep the kernel fail-closed on label collisions, pairwise solid
  intersections, build-zone violations, parent-fixed contract violations,
  top-level translation misuse, and payload start-clearance overlap.

### 2. Align entry gates with exit gates

- Route the benchmark and engineer `validate_*()` helpers through the same
  shared validation kernel that node-entry validation uses.
- Make benchmark reviewer entry and engineer execution reviewer entry consume
  the same kernel that their corresponding coder exits already use.
- Ensure planner and plan-reviewer stages also use the shared kernel, with
  plan-specific evidence requirements layered on top.
- Keep `submit_plan()` aligned with the same contract that plan-reviewer entry
  uses for each family.

### 3. Regenerate derived seed artifacts from source

- Make the seed materialization path regenerate derived eval artifacts from
  canonical source files when the source contract changes.
- Refresh seeded workspaces, mock responses, and generated manifests from the
  same canonical inputs instead of patching them by hand.
- Keep the seed workflow fail-closed when a derived artifact no longer matches
  the source contract.

### 4. Update docs, tests, and seeds

- Update `specs/architecture/agents/handover-contracts.md`, `specs/architecture/agents/tools.md`,
  and the artifact acceptance docs so the shared kernel is described as one
  inherited chain instead of separate one-off gates.
- Update the benchmark and engineering execution review docs so they reference
  the same validation contract.
- Refresh the seeded workspaces and negative-path integration coverage that
  currently assume one validation pass is enough to carry a workspace through
  the next node.

## Non-Goals

- Do not add `skill_agent`, `git_agent`, or `journalling_agent` to the
  contract lattice.
- Do not replace stage-specific evidence semantics with one generic success
  metric.
- Do not relax geometry validation or treat earlier success as perpetual.
- Do not turn node-entry checks into warnings, soft reroutes, or best-effort
  suggestions.
- Do not make freshness metadata the correctness mechanism.
- Do not collapse benchmark and engineer contracts into one permissive schema.
- Do not change simulation backend selection, render backend selection, or the
  shared scene-builder geometry contract itself.

## Sequencing

The safest implementation order is:

1. Extract the shared validation kernel and wire worker exit validation to it.
2. Teach controller node entry to call the same kernel on the current
   workspace.
3. Align `submit_plan()` and plan-reviewer entry with the same kernel.
4. Refresh seed materialization and derived artifacts from canonical inputs.
5. Update architecture docs, role docs, artifact acceptance docs, and seeded
   regressions.

## Acceptance Criteria

1. Every first-class node transition uses the shared validation lattice.
2. A workspace that mutates after validation but before the next node starts
   is rejected by the next node entry because the kernel fails.
3. `benchmark_plan_reviewer` entry is a strict superset of the validation
   already performed by `submit_plan()` for the benchmark family, and
   `benchmark_coder` exit is the stage that still asserts the approved plan and
   benchmark geometry before review.
4. `engineer_execution_reviewer` entry is a strict superset of the validation
   already performed by `submit_plan()` for the engineering family, and
   `engineer_coder` exit is the stage that still asserts the approved plan
   before execution review.
5. Planner and plan-reviewer transitions are covered by the same validation
   kernel and do not bypass geometry or physical checks.
6. The runtime-spawned payload overlap bug class is rejected: a benchmark
   scene that appears valid before payload insertion cannot still be admitted
   once the payload is added and the current workspace no longer satisfies the
   shared clearance check.
7. Seeded workspaces can be regenerated from canonical source inputs without
   manual repair after the source contract changes.
8. Utility agents remain excluded.
9. The docs and integration coverage all describe the same contract behavior.

## Detailed Implementation Checklist

- [ ] Extract the shared validation kernel in shared code for geometry,
  payload clearance, and stage-specific evidence checks.
- [ ] Make worker exit validation call that kernel instead of owning the logic
  in isolation.
- [ ] Make controller node-entry validation call the same kernel before
  stage-specific custom checks.
- [ ] Keep the shared scene-builder constructor as the only benchmark payload
  geometry source used by the kernel.
- [ ] Preserve `_validate_moved_object_start_clearance()` as the canonical
  payload-overlap check.
- [ ] Make `submit_plan()` and plan-reviewer entry use the same plan contract
  for benchmark and engineer families.
- [ ] Make the seed materialization path regenerate derived eval artifacts
  from canonical source files when the contract changes.
- [ ] Refresh seeded workspaces, mock responses, and generated manifests that
  still encode stale assumptions.
- [ ] Add the remaining stale-after-validation, role-mismatch, and
  low-friction-cube regressions in the p0 and p1 integration suites.
- [ ] Update the acceptance-criteria docs so the shared validation contract is
  described as the source of truth.
- [ ] Run the narrowest relevant integration slice first, then widen.

## File-Level Change Set

- `controller/agent/node_entry_validation.py`
- `controller/agent/review_handover.py`
- `shared/agent_templates/codex/scripts/submit_plan.py`
- `shared/utils/agent/__init__.py`
- `worker_heavy/utils/validation.py`
- `worker_heavy/utils/handover.py`
- `dataset/data/seed/artifacts/**`
- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/tools.md`
- `specs/architecture/agents/agent-artifacts/validation_results_json_acceptance_criteria.md`
- `specs/architecture/agents/agent-artifacts/reviewer_manifest_acceptance_criteria.md`
- `specs/architecture/agents/agent-artifacts/benchmark_plan_review_yaml_acceptance_criteria.md`
- `specs/architecture/agents/agent-artifacts/engineering_plan_review_yaml_acceptance_criteria.md`
- `specs/architecture/agents/agent-artifacts/benchmark_execution_review_yaml_acceptance_criteria.md`
- `specs/architecture/agents/agent-artifacts/engineering_execution_review_yaml_acceptance_criteria.md`
