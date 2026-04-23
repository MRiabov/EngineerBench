---
title: Verified Benchmark Bundle Seed Progression Contract
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
added_at: '2026-04-22T00:00:00Z'
---

# Verified Benchmark Bundle Seed Progression Contract

<!-- Planned migration. No behavior change yet. -->

## Purpose

This migration adds progression logic on top of the existing seed-autopilot
pipeline. It does not replace the current quick-prototype workflow, and it
does not introduce a new custom execution engine.

The current seed-autopilot path remains available for fast iteration and
small batches. The new piece is a narrow controller that decides which
approved family/row should be materialized next when we want scalable corpus
generation.

The benchmark chain remains the place where the environment is authored and
verified:

1. `Benchmark Planner` writes the candidate benchmark.
2. `Benchmark Plan Reviewer` accepts or rejects that candidate.
3. `Benchmark Coder` materializes the approved benchmark implementation.
4. `Benchmark Reviewer` verifies the implemented benchmark and freezes the
   approved benchmark bundle.

Once a bundle is approved, the progression layer uses that bundle together
with the family plan in
`dataset/data/seed/artifacts/engineer_planner/engineer_planner_seed_family_plan.md`
to choose the next seed to run. The selected seed then goes through the
standard materialize-launch-validate-review-copy-back pipeline unchanged.

This migration is compatible with the template-free seed corpus contract. The
runtime starter scaffold remains a separate bootstrap layer and is not stored
as part of the published seed bundle.

## Problem Statement

The current seed-generation loop is too open-ended for scalable corpus
production.

That is not a criticism of the existing system. It is useful for quick
prototyping. The issue is that the same loop also handles progression, retry,
and execution, which makes it harder to scale cleanly when we want to produce
large numbers of reviewed seeds.

What we need is progression logic, not a new derivation engine:

1. decide which approved family/row should run next,
2. materialize a normal seed workspace,
3. launch the agent through the existing pipeline,
4. validate and review the outputs using the current checks,
5. record the result and advance the queue.

The existing family plan file names the families and target row counts, but it
does not yet act as a progression manifest with explicit bundle identity and
queue state. That leaves the controller with too little structure and too much
opportunity to revisit rows that should simply be skipped or advanced.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `dataset/data/seed/artifacts/engineer_planner/engineer_planner_seed_family_plan.md` | Describes family counts, variation knobs, and rough difficulty. | It needs explicit progression metadata so the controller can choose the next seed deterministically. |
| `dataset/evals/eval_seed_update_autopilot_per_seed.py` | Mixes selection, worker launch, validation, review, and copy-back in one loop. | The progression part needs to be clearer so the queue can scale without changing the execution pipeline. |
| `dataset/evals/materialize_seed_workspace.py` | Replays an already seeded row into a workspace for inspection or CLI launch. | It is the right execution helper; it should stay that way and not absorb progression policy. |
| `dataset/evals/materialize_seed_authoring_workspace.py` | Boots a seed-authoring workspace from starter files. | It remains a bootstrap helper, not a queueing system. |
| `dataset/evals/run_e2e_seed.py` | Runs the benchmark-to-engineer smoke chain end to end. | It is a verification path, not a progression controller. |
| `shared/eval_artifacts.py` | Owns starter-file registries and workspace helpers. | It does not yet expose progression metadata for approved bundles and target counts. |
| `specs/architecture/agents/artifacts-and-filesystem.md` | Separates benchmark-owned read-only context from engineer-owned writable files. | It does not say how progression should select the next bundle/row before the workspace is materialized. |
| `specs/architecture/agents/handover-contracts.md` | Defines benchmark and engineering handovers. | It does not define the queue/progression contract that chooses the next eligible row. |
| `specs/devtools.md` | Documents the existing seed and workspace helpers. | It does not describe the progression controller or the resume semantics for large batches. |

## Proposed Target State

1. Each benchmark family has one or more approved bundles, plus an explicit
   target row count and progression metadata.
2. The family plan records the approved bundle id, bundle fingerprint, target
   count, and allowed variation knobs for each family.
3. The progression controller chooses the next eligible seed from the family
   plan and current task state.
4. The chosen seed is then materialized into a normal seed workspace and run
   through the standard launch, validation, review, and copy-back pipeline.
5. The prompt and helper surface stays narrow. The worker sees the selected
   bundle, the family manifest, and the role prompt, not the whole repository.
6. The expensive benchmark verification is paid once per approved bundle, not
   once per queue decision.
7. Families without approved bundles, or families that have already reached
   their target counts, are skipped by the progression controller rather than
   forcing a new execution path.

## Required Work

### 1. Define a verified bundle registry

- Add an explicit approved-bundle registry for benchmark families.
- Store the benchmark family, approved bundle id, bundle fingerprint, and
  target row count in the registry.
- Keep the registry explicit. Do not infer progression state from row ids,
  directory names, or prompt text.
- Keep the benchmark bundle immutable after benchmark reviewer approval.

### 2. Make the family plan progression-aware

- Update `dataset/data/seed/artifacts/engineer_planner/engineer_planner_seed_family_plan.md`
  so each family entry points at an approved bundle and target count.
- Keep the family plan as the progression manifest, not as a freeform prompt
  note.
- Preserve the row-count and variation-knob information, but add the bundle
  identity needed to select the next eligible row deterministically.
- If a family lacks an approved bundle or has already exhausted its target
  count, the progression controller should skip it.

### 3. Keep execution on the standard pipeline

- Reuse the existing seed workspace materialization path.
- Reuse the existing worker launch path.
- Reuse the existing validation, review, and copy-back steps.
- Do not add a custom derivation engine or custom validator path for the new
  scalable lane.

### 4. Narrow the queue/progression surface

- Keep the progression controller limited to the family plan, approved bundle
  registry, and current task state.
- Keep benchmark-owned artifacts read-only in the selected bundle.
- Keep the prompt text and helper instructions focused on bundle identity,
  family progression, and the current row contract.

### 5. Update docs and tests

- Update the docs so the progression controller is clearly separated from the
  standard execution pipeline.
- Update the devtools docs so the selection/progression path and the
  row-inspection path are clearly separated.
- Keep the benchmark and engineering runtime contracts unchanged.

### 6. Add regression coverage

- Add a regression that proves the progression controller skips families with
  no approved bundle.
- Add a regression that proves the progression controller advances past a
  family that has already reached its target count.
- Add a regression that proves the queue resumes from recorded progression
  state after interruption.
- Add a regression that proves the standard materialize-launch-validate-
  review pipeline still works unchanged for the selected seed.

## Non-Goals

- Do not change benchmark authoring, benchmark review criteria, or benchmark
  runtime semantics.
- Do not remove the existing quick-prototype seed-autopilot path.
- Do not replace the standard materialize-launch-validate-review pipeline.
- Do not add custom validation or custom workspace materialization logic for
  the scalable lane.
- Do not broaden the progression controller to scan unrelated repository
  docs.
- Do not replace the family plan with freeform prompt text.

## Risks

1. If the bundle registry is implicit, rows will silently drift to stale
   benchmark inputs.
2. If the progression controller still scans broad repo context, token cost
   and failure rate will remain high.
3. If the family plan does not carry bundle identity and target count, the
   queue cannot resume cleanly.
4. If queue state is not persisted, interruptions will duplicate rows.

## Sequencing

The safe order is:

1. Define the approved bundle registry and fingerprint contract.
2. Update `engineer_planner_seed_family_plan.md` to reference approved
   bundles and target counts.
3. Implement the progression controller and persistence of task state.
4. Reuse the existing materialize-launch-validate-review pipeline unchanged.
5. Update docs and tests.
6. Add the missing-bundle, exhausted-family, and resume regressions.

## Acceptance Criteria

1. The controller can deterministically choose the next eligible seed.
2. The family plan file names the bundle identity and target count for each
   family entry.
3. The standard materialize-launch-validate-review pipeline runs unchanged on
   the selected seed.
4. The queue resumes from recorded progression state after interruption.
5. Families without approved bundles or exhausted target counts are skipped.
6. The docs and regression suite describe the same progression contract that
   the controller enforces.

## File-Level Change Set

The implementation should touch the smallest set of files that actually
enforce the progression contract:

- `dataset/data/seed/artifacts/engineer_planner/engineer_planner_seed_family_plan.md`
- `shared/eval_artifacts.py`
- `dataset/evals/eval_seed_update_autopilot_per_seed.py`
- `dataset/evals/materialize_seed_workspace.py`
- `specs/devtools.md`
- `specs/architecture/agents/handover-contracts.md`
- `scripts/internal/eval_seed_selection.py`
- `tests/integration/architecture_p0/test_codex_runner_mode.py`
- `tests/integration/architecture_p1/test_benchmark_workflow.py` if the
  progression controller needs a new end-to-end assertion
