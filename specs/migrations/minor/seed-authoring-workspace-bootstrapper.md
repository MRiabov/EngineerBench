---
title: Seed Authoring Workspace Bootstrapper
status: implemented
agents_affected: []
added_at: '2026-04-22T06:45:55Z'
---

# Seed Authoring Workspace Bootstrapper

<!-- Implemented migration. The helper is implemented and the integration slice passes. -->

## Purpose

This migration adds a maintainer-facing devtool that materializes a blank-slate
workspace for a selected seed authoring role. The new helper gives seed
creators the exact starter/template files and workspace metadata they need to
bootstrap a new eval seed without hand-assembling the directory tree.

The helper is the inverse of `dataset/evals/materialize_seed_workspace.py`:
the existing utility inspects an already-seeded row, while this migration
defines a helper for creating the authoring workspace that will later become a
seed row. The target contract lives alongside the existing seed-workspace and
filesystem docs in `specs/devtools.md`,
`specs/architecture/agents/agent-harness.md`,
`specs/architecture/agents/artifacts-and-filesystem.md`,
`shared/agent_templates/__init__.py`, and `shared/eval_artifacts.py`.

The helper stays separate from `scripts/update_eval_seed_templates.py`.
The refresh script copies canonical starter files into already-existing seed
corpus directories; the new bootstrapper will create the blank authoring
workspace that seed creators edit before they publish a row.

## Problem Statement

Seed creation is currently split across two partial tools and a manual workflow:

1. `dataset/evals/materialize_seed_workspace.py` can inspect a seeded row, but
   it is row-centric and assumes the seed already exists.
2. `scripts/update_eval_seed_templates.py` can refresh starter files inside the
   corpus, but it does not give a fresh workspace rooted in the target agent
   context.
3. Seed creators still have to assemble the workspace directory tree, starter
   files, and metadata by hand or by copying from an existing row.
4. The current process makes it easy to forget a starter file, copy the wrong
   reference file, or accidentally reuse a solved output as the bootstrap
   baseline.
5. The shared starter registry already exists, so the missing piece is a direct
   authoring entrypoint that consumes it.

That gap slows down eval creation and creates avoidable drift between the seed
corpus, the starter registry, and the working directory seed authors use while
building a new row.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `dataset/evals/materialize_seed_workspace.py` | Materializes a seeded row into `/tmp/problemologist-evals/<agent>/` for inspection and optional CLI-provider launching. | It is the wrong shape for seed creation because it assumes the row already exists and treats the workspace as a replay surface. |
| `dataset/evals/materialize_seed_authoring_workspace.py` | Bootstraps a blank authoring workspace and links the repository-local `.venv` into it. | It is the missing authoring entrypoint that seed creators need. |
| `evals/logic/workspace.py` | Shared workspace materialization code copies seed artifacts and writes `.manifests/current_role.json`. | The helper logic is already present, but there is no authoring-focused CLI around it. |
| `shared/agent_templates/__init__.py` | Loads the starter file set for each agent. | The new bootstrapper must reuse this source of truth instead of duplicating starter-path logic. |
| `shared/eval_artifacts.py` | Defines the per-agent starter template file registry used by validation and seed maintenance. | The authoring helper must stay aligned with the same registry that validation uses. |
| `scripts/update_eval_seed_templates.py` | Refreshes checked-in starter files in the corpus. | It is a maintenance utility, not a blank-workspace generator. |
| `scripts/validate_eval_seed.py` | Validates already-materialized seed rows. | Validation is downstream of authoring and cannot help create the initial workspace. |
| `.agents/skills/eval-creation-workflow/SKILL.md` | Describes manual seed hygiene and corpus refresh, but not a direct bootstrap command. | Seed creators need a concrete helper to follow instead of a purely manual setup path. |
| `specs/devtools.md` | Documents the current inspection and refresh utilities, but no blank-slate authoring helper. | The devtools index should name the bootstrapper so seed creators can discover it. |

## Proposed Target State

1. A dedicated helper exists at
   `dataset/evals/materialize_seed_authoring_workspace.py` and materializes a
   blank seed-authoring workspace for a selected agent.
2. The helper uses the shared starter/template registry and the shared
   workspace contract instead of hard-coded starter paths or local heuristics.
3. The workspace root is a stable scratch tree under
   `/tmp/problemologist-evals/seed_authoring/` so seed-authoring runs do not
   collide with the existing seed-inspection helper.
4. The helper writes the backend-owned workspace metadata required by the
   runtime contract, including the current-role manifest and any prompt/context
   files the seed authoring flow needs.
5. The helper links the repository-local `.venv` into the workspace instead of
   copying it, so the authoring workspace keeps a stable Python entrypoint
   without duplicating the full environment tree.
6. The helper fails closed when the requested agent has no starter set or when
   the workspace cannot be assembled exactly from the shared registry.
7. `scripts/update_eval_seed_templates.py` remains the separate corpus-refresh
   tool, and `dataset/evals/materialize_seed_workspace.py` remains the separate
   inspection helper.
8. Docs and skill guidance direct seed creators to the new helper for
   bootstrapping and to the refresh utility only for corpus synchronization.

## Required Work

### 1. Define the bootstrapper contract

- Choose the exact CLI shape for the new seed-authoring helper.
- Define which agent identifiers, task identifiers, and workspace roots it
  accepts.
- State the exact file-set contract for the blank workspace, including the
  starter/template files, read-only reference files, and backend-owned
  metadata.
- Keep the helper fail-closed when a required starter file is missing or when
  the requested agent has no known starter set.

### 2. Reuse shared workspace plumbing

- Build the new helper on top of the shared materialization code in
  `evals/logic/workspace.py` instead of duplicating workspace assembly logic.
- Load starter files through `shared/agent_templates/__init__.py` and
  `shared/eval_artifacts.py`.
- Keep the bootstrapper aligned with the current-role manifest contract and any
  other workspace metadata that the runtime expects.
- Avoid creating a second source of truth for starter/template classification.

### 3. Keep refresh and inspection paths separate

- Leave `scripts/update_eval_seed_templates.py` as the tool for refreshing the
  checked-in seed corpus.
- Leave `dataset/evals/materialize_seed_workspace.py` as the tool for
  inspecting an already seeded row.
- Do not let the new helper overwrite the corpus or act as a validation
  shortcut.

### 4. Update docs and skills

- Update `specs/devtools.md` to document the planned bootstrapper and its
  relationship to the existing inspection and refresh utilities.
- Update `.agents/skills/eval-creation-workflow/SKILL.md` so seed creators are
  told when to use the new helper and when to use the refresh utility.
- Keep the wording distinct from the seeded-starter-baseline and current-role
  migrations so the docs do not collapse the authoring flow into runtime
  validation.

### 5. Add follow-on coverage

- Add integration coverage for the blank-workspace materialization path once
  the helper exists.
- Add a regression that proves the bootstrapper does not silently write solved
  outputs into starter paths.
- Add a regression that proves corpus refresh and blank-workspace creation
  remain different commands.

## Non-Goals

- Do not change the seed validation gate.
- Do not change the runtime current-role contract.
- Do not add a second corpus sync utility.
- Do not make the blank-workspace helper mutate the checked-in seed corpus.
- Do not turn the bootstrapper into a full seed generator that writes solved
  outputs.
- Do not change the shared starter registry semantics in this migration.
- Do not replace `dataset/evals/materialize_seed_workspace.py`.

## Sequencing

The safe order is:

1. Define the bootstrapper contract and file-set shape.
2. Reuse the shared workspace materialization helpers.
3. Add the new CLI entrypoint and make it fail closed on missing starter paths.
4. Update the devtools doc and seed-creation skill guidance.
5. Add integration coverage for the blank-workspace path and the separation
   from corpus refresh.

## Acceptance Criteria

1. A seed creator can materialize a blank workspace for a selected agent from a
   single command.
2. The workspace contains the exact starter/template file set needed to begin
   seed authoring.
3. The helper uses the shared starter registry rather than ad hoc path
   inference.
4. `scripts/update_eval_seed_templates.py` remains a corpus refresh utility and
   does not become the bootstrapper.
5. `dataset/evals/materialize_seed_workspace.py` remains the inspection helper
   for existing seed rows.
6. `specs/devtools.md` and the seed-creation skill name the bootstrapper
   explicitly.
7. Integration coverage proves the blank-workspace helper and the corpus
   refresh utility are separate contracts.

## Completion Note

The seed-authoring bootstrapper now lives in
`dataset/evals/materialize_seed_authoring_workspace.py`. It reuses the shared
Codex workspace materializer, copies the starter-template set for the selected
agent, writes the current-role manifest, and fails closed for roles without a
starter set. The narrow integration slice covering the helper passed on
2026-04-22.

## Migration Checklist

### Contract definition

- [x] Define the new seed-authoring helper CLI and its accepted agent/task/root
  arguments.
- [x] Define the blank-workspace file-set contract and the fail-closed behavior
  for missing starter files.
- [x] Choose the scratch-root convention under `/tmp/problemologist-evals/`
  for authoring workspaces.

### Workspace plumbing

- [x] Reuse the shared workspace materialization helpers instead of
  duplicating file-copy logic.
- [x] Load starter files from the shared starter registry.
- [x] Write the backend-owned metadata needed by the authoring workspace
  contract.
- [x] Keep the bootstrapper from mutating the checked-in seed corpus.

### Docs and skills

- [x] Update `specs/devtools.md`.
- [x] Update `.agents/skills/eval-creation-workflow/SKILL.md`.
- [x] Add a short note that distinguishes the bootstrapper from
  `scripts/update_eval_seed_templates.py` and
  `dataset/evals/materialize_seed_workspace.py`.

### Validation

- [x] Add integration coverage for the blank-workspace materialization path.
- [x] Add a regression that proves starter paths are not pre-solved by the
  bootstrapper.
- [ ] Add a regression that proves corpus refresh stays separate from
  workspace bootstrap.

## File-Level Change Set

The implementation should touch the smallest set of files that actually
enforce the new contract:

- `dataset/evals/materialize_seed_authoring_workspace.py`
- `evals/logic/workspace.py` if the shared helper needs a reusable
  authoring-materialization function
- `scripts/update_eval_seed_templates.py` if its docs or CLI text need to
  point at the new helper
- `specs/devtools.md`
- `.agents/skills/eval-creation-workflow/SKILL.md`
- `tests/integration/architecture_p0/test_seed_authoring_workspace_bootstrapper.py`
