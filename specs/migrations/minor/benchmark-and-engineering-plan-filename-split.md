---
title: Benchmark and Engineering Plan Filename Split
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
  - electronics_planner
  - electronics_reviewer
added_at: '2026-04-08T12:00:00Z'
---

# Benchmark and Engineering Plan Filename Split

<!-- Migration tracker. Check items conservatively as implementation lands. -->

## Purpose

This migration splits the stage narrative plan filename into two explicit
artifacts:

1. `benchmark_plan.md` for the benchmark generator graph
2. `engineering_plan.md` for the engineering graph

The split removes the shared `plan.md` authored-file contract from new
workspace materialization and submission paths. `todo.md` and `journal.md`
remain unchanged; only the stage plan artifact is renamed.

The target contract is:

1. Benchmark planners, plan reviewers, coders, and reviewers own
   `benchmark_plan.md`.
2. Engineering planners, plan reviewers, coders, execution reviewers, and
   electronics roles own `engineering_plan.md`.
3. `plan.md` is only a transitional compatibility alias for pre-existing seed
   bundles and replay material, not a canonical authored file for newly
   materialized workspaces.
4. Template repos, prompt assembly, artifact validators, and submission
   helpers infer the correct plan filename from the role rather than from a
   shared name.
5. Node-entry validation and reviewer handover fail closed when the role-
   specific plan file is missing or when a workspace still uses the wrong
   canonical plan filename.
6. The benchmark and engineering plan structure rules remain distinct and are
   still enforced.
7. The filename split is applied consistently across architecture docs, eval
   artifacts, mock responses, and integration coverage.

This is a filename and contract split, not a content simplification. The two
plans remain different artifacts with different headings, different reviewers,
and different downstream validation paths.

## Problem Statement

The current shared `plan.md` contract blurs stage boundaries in three ways:

1. It forces runtime helpers to guess whether a given plan belongs to the
   benchmark or engineering graph.
2. It makes the same file name appear in both prompt assemblies even though
   the plan content and validation rules are different.
3. It pushes file-level validation, manifest hashing, and workspace
   materialization toward content sniffing and target-node inference instead of
   explicit stage naming.

That ambiguity leaks into seed preflight, review handover, and test fixtures.
The file name itself should encode the stage because the stage already owns
the rest of the contract.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `shared/assets/template_repos/benchmark_generator/plan.md` and `shared/assets/template_repos/engineer/plan.md` | Both template repos write a generic `plan.md`. | The canonical authored filename should encode the graph so seeded workspaces and downstream tooling cannot confuse the two plan contracts. |
| `shared/agent_templates/__init__.py`, `shared/eval_artifacts.py`, `evals/logic/specs.py` | Base artifact lists still export `plan.md` for both graphs. | Workspace materialization and eval seed contracts need stage-specific filenames. |
| `shared/workers/markdown_validator.py` and `worker_heavy/utils/file_validation.py` | Markdown validation dispatches on `plan.md` and uses target-node or content sniffing to decide which structure to enforce. | The validator should dispatch on `benchmark_plan.md` and `engineering_plan.md`, with compatibility only for legacy reads. |
| `controller/agent/node_entry_validation.py`, `controller/agent/review_handover.py`, `controller/agent/benchmark_handover_validation.py` | Handoff gates read `plan.md` and pass it through cross-contract checks. | Those gates need to read the new stage-specific plan filename and hash the correct file into manifests. |
| `shared/agent_templates/codex/scripts/submit_plan.py` | Submission helper looks for `plan.md` and infers planner identity from a shared filename plus prompt markers. | The submission bridge should require the stage-specific plan filename and infer the correct planner from it. |
| `config/prompts.yaml` and `controller/agent/prompt_manager.py` | Prompt text teaches the shared `plan.md` path. | Prompts should direct agents to `benchmark_plan.md` or `engineering_plan.md` explicitly. |
| `evals/logic/workspace.py`, `evals/logic/codex_workspace.py` | Workspace materialization still assumes a shared plan file when copying role templates and assembling prompts. | Fresh benchmark and engineering workspaces need stage-specific plan filenames. |
| `specs/architecture/agents/**`, `specs/architecture/agents/agent-artifacts/**`, `specs/integration-test-list.md` | Docs still describe one `plan.md` artifact family. | The architecture and test catalog need stage-specific file names to match the runtime. |
| `tests/integration/**`, `tests/integration/mock_responses/**`, `dataset/data/seed/**` | Seeded workspaces and mock flows still assert the shared filename. | The eval surface must be refreshed so new fixtures are not seeded with stale assumptions. |

## Proposed Target State

01. `benchmark_plan.md` is the benchmark generator's canonical stage narrative.
02. `engineering_plan.md` is the engineering workflow's canonical stage
    narrative.
03. `plan.md` is not written by new starter templates, prompt assembly, or
    submission helpers.
04. `todo.md` remains the execution checklist filename for both workflows.
05. `journal.md` remains unchanged.
06. Validation code accepts the new plan filenames as canonical and only
    tolerates `plan.md` during a bounded compatibility window for old seed or
    replay artifacts.
07. The plan structure rules continue to differ by workflow:
    - benchmark plan remains the learning objective / geometry / objectives /
      risk contract;
    - engineering plan remains the solution / parts / assembly / budget / risk
      contract.
08. Planner handoff manifests and review artifacts continue to have the same
    filenames, but their hash sets and artifact lookups refer to the stage-
    specific plan file.
09. The seed validator, node-entry validator, and reviewer gates all fail
    closed if the wrong plan file is missing or stale.
10. The integration catalog and seeded mock responses refer to the split
    filenames so the contract is visible in tests, not only in runtime
    helpers.

## Phased Migration Shape

This migration is broader than a simple rename because it touches prompt
assembly, validation, seed preflight, and review routing.

1. Contract and naming tranche: rename the template-repo plan files and
   update workspace materialization.
2. Validation tranche: update file validators, node-entry validation, and
   review handover to require the stage-specific filenames.
3. Prompt and docs tranche: update the prompt assembly, role sheets, and
   artifact contracts to use the explicit plan names.
4. Seed and integration tranche: refresh eval seeds, mock responses, and
   integration coverage so the new filenames are the visible contract.

## Required Work

### 1. Rename the canonical plan files

- Rename `shared/assets/template_repos/benchmark_generator/plan.md` to
  `benchmark_plan.md`.
- Rename `shared/assets/template_repos/engineer/plan.md` to
  `engineering_plan.md`.
- Update any starter file copy logic so new workspaces materialize the new
  filenames directly.
- Keep the file contents stage-specific; do not homogenize the benchmark and
  engineering narratives just to reduce drift.
- Do not rename `todo.md` or `journal.md` in this migration.

### 2. Update workspace materialization and submission helpers

- Update `shared/agent_templates/__init__.py` role template lists to include
  the stage-specific plan filename.
- Update `shared/eval_artifacts.py` and `evals/logic/specs.py` so eval
  contracts refer to `benchmark_plan.md` and `engineering_plan.md`.
- Update `shared/agent_templates/codex/scripts/submit_plan.py` to require the
  correct plan filename for each planner role and to infer the planner role
  from the split file rather than from a generic `plan.md`.
- Update any workspace bootstrapper or materializer that still copies
  `plan.md` into planner workspaces.

### 3. Make validation stage-aware

- Update `shared/workers/markdown_validator.py` so the file-name dispatch
  recognizes `benchmark_plan.md` and `engineering_plan.md`.
- Update `worker_heavy/utils/file_validation.py` so node-output and
  cross-contract checks read the stage-specific plan file, not a shared
  `plan.md`.
- Update `controller/agent/node_entry_validation.py`,
  `controller/agent/review_handover.py`, and
  `controller/agent/benchmark_handover_validation.py` to read the split plan
  filename and to pass that file into hash checks, manifest checks, and
  exact-mention validation.
- Update `controller/agent/handover_constants.py` so stage-scoped artifact
  lists name the split plan files.
- Keep legacy `plan.md` recognition only where it is needed to replay or
  ingest historical seed bundles. New submissions should not rely on it.

### 4. Update prompts and role guidance

- Update `config/prompts.yaml` and `controller/agent/prompt_manager.py` so
  the planner prompts name the stage-specific plan file.
- Update `specs/architecture/agents/roles.md`, the role sheets under
  `roles-detailed/`, and the artifact contracts under `agent-artifacts/` to
  reflect the renamed files.
- Split the `plan.md` artifact contract into separate benchmark and
  engineering plan contract docs, or replace it with a stage-scoped contract
  index that explicitly names both files.
- Update the prompt text that tells agents to "read plan.md" so it names the
  correct stage-specific plan file.

### 5. Refresh tests, seeds, and mock responses

- Update `scripts/validate_eval_seed.py` so seed preflight fails closed on
  missing `benchmark_plan.md` or `engineering_plan.md`.
- Update `specs/integration-test-list.md` and the affected integration tests
  to assert the new filenames.
- Refresh `tests/integration/mock_responses/**` and
  `dataset/data/seed/**` so rows that used to carry `plan.md` now carry the
  correct role-specific plan file.
- Update representative test cases in `tests/integration/architecture_p0/`
  and `tests/integration/architecture_p1/` that currently assert `plan.md`
  presence, structure, or replay behavior.
- Keep the old fixtures readable only long enough to migrate the corpus; do
  not leave them as a permanent second canonical plan surface.

### 6. Update docs and architecture references

- Update `specs/architecture/agents/handover-contracts.md` to list
  `benchmark_plan.md` and `engineering_plan.md` as the planner handoff
  files.
- Update `specs/architecture/agents/artifacts-and-filesystem.md` to reflect
  the split file ownership and read/write permissions.
- Update `specs/architecture/agents/overview.md`,
  `specs/architecture/agents/roles.md`, and the role sheets so the ownership
  tables no longer imply one shared `plan.md`.
- Update any adjacent docs that currently describe the plan artifact family
  as a single filename.

## Non-Goals

- Do not rename `todo.md`.
- Do not rename `journal.md`.
- Do not change the benchmark or engineering plan content requirements
  beyond the filename split.
- Do not change the review-manifest filenames in `.manifests/`.
- Do not combine the benchmark and engineering plan structures into one
  shared template just to simplify validation.
- Do not change the benchmark inventory exactness contract; that stays in
  the inventory-grounding migration.
- Do not remove the temporary legacy read path for historic seed bundles
  before the corpus has been refreshed.

## Sequencing

The safe order is:

1. Rename the template-repo plan files and update starter workspace
   materialization.
2. Update `submit_plan()`, eval artifact selection, and file validators to
   use the split filenames.
3. Update controller entry validation, review handover, and seed preflight.
4. Refresh prompts, role sheets, and artifact contract docs.
5. Update seeded eval rows, mock responses, and integration tests.
6. Remove any remaining compatibility references to shared `plan.md` once
   the corpus no longer depends on it.

## Acceptance Criteria

1. A freshly materialized benchmark planner workspace contains
   `benchmark_plan.md` rather than `plan.md`.
2. A freshly materialized engineering planner workspace contains
   `engineering_plan.md` rather than `plan.md`.
3. `submit_plan()` and node-entry validation treat the split filenames as
   canonical and fail closed when they are absent or stale.
4. The benchmark and engineering plan structure validators still enforce
   their respective headings after the rename.
5. Seeded eval rows and integration tests refer to the stage-specific
   filenames.
6. The architecture docs and artifact contracts no longer imply that one
   shared `plan.md` is the canonical planning artifact for both graphs.

## File-Level Change Set

The implementation should touch the smallest set of files that actually
enforce the new contract:

- `shared/assets/template_repos/benchmark_generator/plan.md` ->
  `shared/assets/template_repos/benchmark_generator/benchmark_plan.md`
- `shared/assets/template_repos/engineer/plan.md` ->
  `shared/assets/template_repos/engineer/engineering_plan.md`
- `shared/agent_templates/__init__.py`
- `shared/eval_artifacts.py`
- `evals/logic/specs.py`
- `evals/logic/workspace.py`
- `evals/logic/codex_workspace.py`
- `shared/agent_templates/codex/scripts/submit_plan.py`
- `shared/workers/markdown_validator.py`
- `worker_heavy/utils/file_validation.py`
- `controller/agent/handover_constants.py`
- `controller/agent/node_entry_validation.py`
- `controller/agent/review_handover.py`
- `controller/agent/benchmark_handover_validation.py`
- `controller/agent/prompt_manager.py`
- `config/prompts.yaml`
- `specs/architecture/agents/overview.md`
- `specs/architecture/agents/roles.md`
- `specs/architecture/agents/roles-detailed/benchmark-planner.md`
- `specs/architecture/agents/roles-detailed/engineer-planner.md`
- `specs/architecture/agents/roles-detailed/benchmark-coder.md`
- `specs/architecture/agents/roles-detailed/engineer-coder.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/agent-artifacts/README.md`
- `specs/architecture/agents/agent-artifacts/benchmark_plan_md_acceptance_criteria.md`
- `specs/architecture/agents/agent-artifacts/engineering_plan_md_acceptance_criteria.md`
- `specs/integration-test-list.md`
- `scripts/validate_eval_seed.py`
- `tests/integration/**`
- `tests/integration/mock_responses/**`
- `dataset/data/seed/**`

## Open Questions

The runtime compatibility window for `plan.md` has been removed. The remaining
work in this migration is corpus cleanup and stale-reference removal in tests,
seeds, and historical docs.

## Migration Checklist

### Contract

- [ ] Rename the benchmark and engineering planner starter templates to
  `benchmark_plan.md` and `engineering_plan.md`.
- [ ] Update workspace materialization so the new filenames are copied into
  fresh workspaces.
- [ ] Remove `plan.md` from the canonical starter files for new benchmark and
  engineering planner workspaces.
- [ ] Keep `todo.md` and `journal.md` unchanged.

### Runtime

- [ ] Update `submit_plan()` to require the stage-specific plan file.
- [ ] Update the markdown validator and file-validation helpers to dispatch
  on the split filenames.
- [ ] Update controller node-entry validation and review-handoff checks to
  read the split filenames.
- [ ] Keep the legacy `plan.md` read path only for bounded compatibility.

### Docs and tests

- [ ] Update the architecture docs, artifact contracts, and role sheets.
- [ ] Refresh the seeded eval rows, mock responses, and integration tests.
- [ ] Update `specs/integration-test-list.md` and any affected INT mapping
  notes.
- [ ] Verify the narrow seed-preflight slice first, then widen to the
  affected integration coverage.
