---
title: Role-Based Seed Task Metadata Is Not Prompt Text
status: implemented
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
added_at: '2026-04-22T00:00:00Z'
---

# Role-Based Seed Task Metadata Is Not Prompt Text

<!-- Implementation landed. Keep this as the audit trail for the prompt-shape fix. -->

## Purpose

This migration removes a misleading prompt leak in the role-based seed path.

The `task` field in `dataset/data/seed/role_based/*.json` is review metadata
that explains what the seed row is meant to represent. It is not the runtime
prompt body for the active agent. Today the CLI workspace materializer still
threads that field into the rendered prompt, which makes the prompt text look
as if the dataset review note were part of the agent instruction contract.

The target state is simple:

1. role-based seed rows may keep `task` as dataset metadata,
2. runtime prompt materialization does not append that field to `prompt.md`,
3. prompt text comes from the role prompt plus the runtime facts the agent
   actually needs, and
4. seed-review tooling can still inspect the metadata without conflating it
   with the agent prompt.

This is a prompt-shape and contract fix, not a seed-schema rewrite. The
underlying seed rows may still describe the intended benchmark or engineering
scenario, but that description must stay on the dataset-review side of the
boundary.

## Problem Statement

The current materialization path treats `task` as if it were runtime prompt
content:

1. `evals/logic/codex_workspace.py::_build_cli_runtime_context()` appends a
   `Task:` section built from `item.task`.
2. `evals/logic/codex_workspace.py::build_cli_prompt()` renders that runtime
   context into the final CLI prompt.
3. `dataset/evals/materialize_seed_workspace.py` writes the rendered prompt to
   `prompt.md`.
4. The same prompt file is then used by CLI-provider-backed sessions and by
   inspection helpers, so the dataset review note becomes visible to the
   model.

That is misleading for role-based seed rows like
`dataset/data/seed/role_based/engineer_coder.json`, where the row `task` is
meant to summarize the intended seed for reviewers. The agent should infer
what to do from the role prompt, the copied seed artifacts, and the runtime
workspace state, not from a duplicated review note.

The bug is broader than one row because the same helper path is shared across
all role-based seed workspaces.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `dataset/data/seed/role_based/*.json` | Seed rows carry a `task` string that explains the intended seed to dataset reviewers. | That field is metadata, not canonical prompt content, and should not be appended to the agent prompt. |
| `evals/logic/codex_workspace.py` | `_build_cli_runtime_context()` appends `Task:` plus `item.task`, and `build_cli_prompt()` renders it into the final prompt. | The shared CLI prompt builder is the direct source of the leak. |
| `dataset/evals/materialize_seed_workspace.py` | Writes the rendered CLI prompt to `prompt.md` for inspection and launch helpers. | It propagates the leaked task text into the workspace prompt file. |
| `evals/logic/workspace.py` | Threads `item.task` through seeded entry validation state. | Any task-label contract that remains should be explicit about metadata versus prompt text. |
| `tests/integration/architecture_p0/test_codex_runner_mode.py` | Asserts the CLI runtime context includes the task text from the seeded row. | The integration surface currently codifies the wrong prompt shape. |
| `specs/architecture/agents/prompt-management.md` | Describes runtime-generated context as including task text. | The prompt contract needs to distinguish runtime task labels from review-only seed metadata. |
| `specs/architecture/agents/artifacts-and-filesystem.md` | Describes seed and workspace metadata boundaries, but not this metadata/prompt split. | The filesystem contract should state that review notes do not become prompt input by default. |

## Proposed Target State

1. Role-based seed rows keep their `task` string as review metadata.
2. Seed prompt materialization does not inject the row `task` into the prompt
   text.
3. The rendered `prompt.md` for a role-based seed contains the role prompt,
   backend appendix, workspace contract, and other genuine runtime facts, but
   not the dataset review note.
4. If a runtime still needs a human-readable description of the seed, that
   description comes from an explicit non-prompt metadata channel or from the
   seeded artifacts themselves, not from the review-only dataset row field.
5. Seed-authoring workflows remain distinct: authoring helpers may still accept
   a direct prompt string because that path is creating a new seed, not
   materializing an evaluated role-based row.

## Required Work

### 1. Split seed metadata from prompt content

- Remove the unconditional `Task:` injection from the shared CLI runtime
  context used by role-based seed materialization.
- Keep the role prompt, backend appendix, and workspace contract intact.
- Preserve the ability to inspect the seed-row `task` field in dataset-review
  tooling and seed validation logs if that field is still useful there.
- If the runtime needs a visible seed summary, add a dedicated metadata
  channel rather than reusing the prompt body.

### 2. Update the workspace materializer

- Keep `dataset/evals/materialize_seed_workspace.py` writing the final
  rendered prompt to `prompt.md`.
- Ensure the rendered prompt no longer includes role-based seed review notes
  from `dataset/data/seed/role_based/*.json`.
- Keep the materializer usable for inspection and launch helpers without
  making the dataset review note part of the instruction text.

### 3. Refresh docs and tests

- Update the prompt-management docs so they describe runtime context without
  implying that seed-review metadata is always prompt input.
- Update the filesystem/artifacts docs so the metadata boundary is explicit.
- Refresh the Codex runner-mode integration assertions so they stop expecting
  the role-based seed `task` string in the final prompt.
- Add a regression that proves the role-based seed prompt can be materialized
  without the dataset review note.

### 4. Audit related consumers

- Check any helper that serializes `EvalDatasetItem.task` into user-facing
  prompt text or `prompt.md`.
- Keep authoring flows separate from evaluation flows so the authoring prompt
  can still be explicit when a maintainer is creating a new seed.
- Preserve validation and observability behavior that only needs the task as
  metadata.

## Non-Goals

- Do not delete the `task` field from role-based seed rows in this migration.
- Do not change seed review semantics or the meaning of `expected_criteria`.
- Do not change the authoring workspace helper that intentionally accepts a
  direct prompt string.
- Do not rewrite the role prompts to compensate for a metadata leak.
- Do not broaden the change into a seed schema migration unless the metadata
  split proves necessary.

## Sequencing

The safe order is:

1. Remove the `Task:` injection from the shared CLI runtime context used by
   role-based seed materialization.
2. Verify the resulting `prompt.md` still contains the role prompt and
   workspace contract, but not the dataset review note.
3. Update the prompt-management and filesystem docs.
4. Refresh the integration assertions that currently expect the leaked text.
5. Add a regression for the role-based seed materialization path.

## Acceptance Criteria

1. `dataset/data/seed/role_based/engineer_coder.json` can still carry a
   reviewer-facing `task` field.
2. The rendered prompt for a role-based seed no longer includes that field as
   instruction text.
3. `prompt.md` for role-based seed materialization reads like a role runtime
   prompt, not like a copied dataset review note.
4. The authoring workspace path remains allowed to accept an explicit prompt
   string because that is a different use case.
5. The docs and integration tests describe the same boundary that the code
   enforces.

## File-Level Change Set

The implementation should touch the smallest set of files that actually
enforce the new contract:

- `evals/logic/codex_workspace.py`
- `dataset/evals/materialize_seed_workspace.py`
- `dataset/data/seed/role_based/*.json`
- `tests/integration/architecture_p0/test_codex_runner_mode.py`
- `specs/architecture/agents/prompt-management.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/devtools.md`
