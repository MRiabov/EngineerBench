---
title: Seeded Eval Template Exclusion Contract
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
added_at: '2026-04-22T10:59:32Z'
---

# Seeded Eval Template Exclusion Contract

<!-- Planned migration. No behavior change yet. -->

## Purpose

This migration removes template-authored copies from the stored seed corpus
and makes seed validation inspect only the non-template files that remain. It
supersedes [Seeded Starter Baseline Registry Contract](./seeded-starter-baseline-registry-contract.md)
from the opposite direction: instead of keeping writable starter templates in
the stored seed bundle and comparing them against a baseline, evals will keep
the seed corpus template-free while runtime workspace bootstrap still
materializes the planner scaffold before the relevant planner node starts.

The target state is to validate the eval state that the seed corpus actually
owns, while leaving runtime starter scaffold materialization to the workspace
bootstrapper and its controller entry gate.

## Problem Statement

Seeded eval workspaces currently blur two different surfaces:

- the stored seed corpus, which should only contain the non-template inputs
  that define the problem instance, and
- the runtime bootstrap scaffold, which still needs to materialize
  engineer-planner starter files before the planner node starts.

That ambiguity leaks into validation. When the corpus and the runtime scaffold
are treated as the same thing, agents learn to reason about template copies as
if they were part of the seed contract, and the validator is forced to check
the wrong boundary.

That is the wrong direction for the system. Template material should remain in
canonical template sources and runtime bootstrap helpers, while eval seed
validation should only care about the stored non-template files that define
the seeded run.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `shared/eval_artifacts.py` | Exposes `SEED_STARTER_TEMPLATE_FILES` and per-agent starter file lists that drive seeded workspace materialization. | The eval contract needs an exclusion registry, not a registry that encourages copying templates into the seed workspace. |
| `controller/agent/initialization.py` | Materializes role-specific starter files into live workspaces before node entry. | The runtime bootstrapper must stay responsible for planner scaffold materialization, separate from the stored seed corpus. |
| `evals/logic/seed_maintenance.py` | Refreshes starter template files into seeded artifact directories. | Seed maintenance must stop reintroducing template files into evaluated workspaces. |
| `evals/logic/workspace.py` | Materializes seeded workspaces from the current starter-file contract. | Workspace seeding must omit template-authored files entirely. |
| `controller/agent/node_entry_validation.py` | Validates the runtime workspace contract, including the planner scaffold that bootstrap materialized. | Validation must fail closed on forbidden template presence in the seed corpus and separately verify the runtime scaffold at planner entry. |
| `scripts/validate_eval_seed.py` | Validates seeded eval entry contracts against the current seed-corpus shape. | The CLI should inherit the template-free corpus contract instead of synchronizing or checking the runtime scaffold. |
| `specs/devtools.md` | Documents writable starter files and starter-baseline drift checks. | Developer docs need to distinguish template-free seed corpora from runtime bootstrap scaffolds. |
| `specs/architecture/agents/artifacts-and-filesystem.md` | Still conflates seed-backed rows with starter snapshots. | The file-ownership contract must distinguish stored seed files from runtime starter files. |
| `specs/architecture/agents/handover-contracts.md` | Names seeded/direct-start starter-baseline checks. | The handover contract must stop depending on seed-corpus template copies as the source of truth for planner bootstrap. |
| `tests/integration/architecture_p0/test_seed_authoring_workspace_bootstrapper.py` | Verifies starter-file refresh behavior. | Integration coverage must move from template refresh to template absence. |
| `tests/integration/architecture_p0/test_node_entry_validation.py` | Exercises starter-template validation and drift failures. | The node-entry regression suite must prove that template files are forbidden, not just matched. |
| `tests/integration/architecture_p0/test_codex_runner_mode.py` | Exercises `scripts/validate_eval_seed.py` on seeded rows. | The CLI regression must prove non-template validation still passes while template-file presence fails closed. |

## Proposed Target State

1. Seeded eval corpora never materialize template-authored files as stored
   seed artifacts.
2. Runtime workspace bootstrap still materializes the engineer-planner
   starter scaffold before the planner node starts.
3. `scripts/validate_eval_seed.py` validates only the non-template seed corpus
   and fails closed if a forbidden template file is present there.
4. The controller node-entry validation path is the source of truth for the
   runtime starter scaffold once it has been materialized.
5. Template sources remain canonical in their shared template repositories and
   prompt-context assets, but they are not stored in the evaluated seed
   corpus.
6. The docs and integration tests describe the same seed-corpus/runtime-split
   contract that the runtime enforces.

## Required Work

### 1. Define the exclusion contract explicitly

- Add an explicit template-file exclusion registry to `shared/eval_artifacts.py`
  or the nearest shared workspace-contract module for the stored seed corpus.
- Keep the set explicit per seed-backed row. Do not infer template exclusion
  from filename patterns or workspace shape.
- Make the registry distinguish template files from the non-template eval files
  that remain in scope.
- Keep the runtime starter scaffold contract separate and owned by the
  workspace bootstrapper, not the stored seed corpus.

### 2. Remove template files from seeded workspaces

- Update the seed workspace materialization path in `evals/logic/workspace.py`
  so template-authored files are not copied into the stored seed corpus.
- Keep `controller/agent/initialization.py` and the local workspace bootstrap
  helpers responsible for materializing the runtime starter scaffold before
  the planner node starts.
- Update `evals/logic/seed_maintenance.py` so it stops refreshing template
  files into the evaluated corpus.
- Keep the seed corpus focused on non-template eval artifacts, read-only
  context, and other required runtime files.

### 3. Validate only the remaining non-template contract surfaces

- Keep `controller/agent/node_entry_validation.py` fail-closed.
- Reject any stored seed corpus that still contains a forbidden template file.
- Validate the remaining non-template files through the existing controller
  seam instead of adding a separate CLI heuristic.
- Keep the runtime starter scaffold validation at planner entry after the
  bootstrapper has materialized it.
- Preserve the current validation-depth behavior from
  `scripts/validate_eval_seed.py`; this migration changes the file set under
  validation, not the depth contract.

### 4. Update docs and contract references

- Update `specs/devtools.md` so seed validation is described as template-free.
- Update `specs/architecture/agents/artifacts-and-filesystem.md` so the
  file-ownership contract distinguishes stored seed files from runtime starter
  files.
- Update `specs/architecture/agents/handover-contracts.md` so seeded/direct-
  start rows no longer treat stored template copies as part of the editable
  seed contract.
- Keep the wording distinct from the starter-baseline migration so the two
  contracts do not collapse into one another.

### 5. Refresh regression coverage

- Add negative regressions that prove a forbidden template file in a seed
  corpus fails validation.
- Add positive regressions that prove a template-free seed still validates
  successfully through `scripts/validate_eval_seed.py`.
- Update any bootstrapper or corpus-refresh tests so they assert template
  absence in the stored corpus while still checking runtime scaffold
  materialization separately.

## Non-Goals

- Do not change the shared prompt-template system under
  `shared/agent_templates/`.
- Do not change prompt rendering or agent-side prompt composition.
- Do not edit agent skills or skill-loading artifacts; this migration is
  limited to eval workspace contracts, validation, docs, and seed fixtures.
- Do not change the validation-depth contract introduced by the seeded
  validation scope migration.
- Do not change benchmark or engineering predecessor gates that are unrelated
  to template-file presence.
- Do not broaden the rule to non-seeded runtime workspaces unless they share
  the same seed contract.
- Do not remove the runtime starter scaffold from engineer-planner workspaces;
  this migration only separates stored seed corpus files from runtime bootstrap
  materialization.

## Sequencing

The safe order is:

1. Define the explicit forbidden-template registry.
2. Remove template files from seed workspace materialization and maintenance
   flows.
3. Keep validation fail-closed on template presence while leaving non-template
   checks intact.
4. Update the docs to match the new workspace contract.
5. Add the negative and positive integration regressions.
6. Re-run the narrow seed-validation CLI slice to confirm template-free seeds
   still pass.

## Acceptance Criteria

1. Seeded eval corpora contain no template-authored files.
2. Runtime workspace bootstrap still materializes the engineer-planner starter
   scaffold before planner entry.
3. `scripts/validate_eval_seed.py` validates only the non-template seed
   corpus and fails closed if a forbidden template file is present there.
4. The controller validation path, not a CLI heuristic, owns the runtime
   starter scaffold contract at planner entry.
5. The docs and integration tests describe the same seed-corpus/runtime-split
   contract that the runtime enforces.
6. The new contract supersedes the starter-baseline registry approach rather
   than layering on top of it.

## Migration Checklist

### Contract Definition

- [ ] Enumerate the exact template-authored files that are forbidden in each
  seed-backed row.
- [ ] Identify the non-template workspace files that remain in scope for each
  affected row.
- [ ] Keep the exclusion registry explicit instead of inferring it from file
  names, directory layout, or agent name.

### Workspace Materialization

- [ ] Remove template-authored files from seeded workspace materialization in
  `evals/logic/workspace.py`.
- [ ] Keep runtime starter scaffold materialization in
  `controller/agent/initialization.py` and local workspace bootstrap helpers.
- [x] Update `evals/logic/seed_maintenance.py` so it stops refreshing template
  files into the evaluated corpus.
- [ ] Preserve read-only context files and other non-template seed artifacts
  that are still required for the runtime contract.

### Validation Plumbing

- [ ] Keep `controller/agent/node_entry_validation.py` fail-closed on forbidden
  template presence in the seed corpus.
- [ ] Ensure validation still inspects the remaining non-template files through
  the controller seam rather than a separate CLI heuristic.
- [ ] Keep runtime starter scaffold validation at planner entry after bootstrap
  materialization.
- [ ] Preserve the current validation-depth behavior from
  `scripts/validate_eval_seed.py`.
- [ ] Confirm the CLI surface continues to fail closed on malformed or missing
  required non-template files.

### Documentation

- [ ] Update `specs/devtools.md` so seed validation is described as
  template-free.
- [ ] Update `specs/architecture/agents/artifacts-and-filesystem.md` so the
  file-ownership contract distinguishes non-template eval files from forbidden
  template files.
- [ ] Update `specs/architecture/agents/handover-contracts.md` so seeded/direct-
  start rows no longer treat template files as part of the editable workspace
  contract.
- [ ] Keep the wording distinct from the starter-baseline migration and do not
  merge the two contracts into one rule.
- [ ] Leave agent skill files and skill-loading docs untouched unless a later
  migration explicitly changes them.

### Test Coverage

- [ ] Add negative regressions that prove a forbidden template file in a seed
  workspace fails validation.
- [ ] Add positive regressions that prove a template-free seed still validates
  successfully through `scripts/validate_eval_seed.py`.
- [x] Update bootstrapper or corpus-refresh tests so they assert template
  absence instead of starter-template restoration.
- [ ] Refresh any CLI regression cases that still assume the workspace contains
  editable template files.

### Cutover Verification

- [ ] Re-run the narrow seed-validation CLI slice on representative rows after
  the workspace contract changes land.
- [ ] Confirm the seed corpus no longer materializes template files for any
  affected row.
- [x] Confirm the runtime starter scaffold still materializes for
  engineer_planner before node entry.
- [ ] Confirm the controller validation path and CLI validation path still
  agree on success and failure outcomes.
- [ ] Confirm no agent skill files were edited as part of the migration.

## File-Level Change Set

The implementation should touch the smallest set of files that actually
enforce the new contract:

- `shared/eval_artifacts.py`
- `controller/agent/initialization.py`
- `evals/logic/seed_maintenance.py`
- `evals/logic/workspace.py`
- `controller/agent/node_entry_validation.py`
- `scripts/validate_eval_seed.py`
- `specs/devtools.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/handover-contracts.md`
- `tests/integration/architecture_p0/test_seed_authoring_workspace_bootstrapper.py`
- `tests/integration/architecture_p0/test_node_entry_validation.py`
- `tests/integration/architecture_p0/test_codex_runner_mode.py`
- `dataset/data/seed/artifacts/**`
