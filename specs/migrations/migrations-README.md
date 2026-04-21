# Migration Doc Guide

This directory contains implementation-facing migration specs. A migration doc
describes how the repo moves from an existing contract to a new contract.
It is not a general design essay, task list, or issue tracker.
This guide only defines how migration docs should be written; it does not
override `specs/desired_architecture.md` or any file under `specs/architecture/`.

## Scope

- Use a migration doc when the change alters a contract, runtime boundary,
  workspace shape, validation gate, or documented ownership rule.
- Write the doc in the `major/` folder when the change is cross-cutting or
  architecture-level.
- Write the doc in the `minor/` folder when the scope is narrower but still
  contract-bearing.
- Keep the filename descriptive and specific to the migration.

## Migration Timeline

Use `uv run specs/migrations/list_migrations_by_date.py` to sort migration docs
by their last git edit time.

The script prints entries in the form:

```text
edited:
01-01-2026 14:15 - specs/migrations/minor/role-scoped-render-buckets.md, agents affected: [benchmark_reviewer, engineer_coder]
```

The script accepts `--since` and `--until` bounds in ISO date or datetime form
so you can narrow the list to a specific period.

If a migration changes agent-facing logic, record the blast radius in YAML
frontmatter at the top of the doc. Use a shape like:

```md
---
title: Role-Scoped Render Buckets
status: investigation
agents_affected:
  - benchmark_reviewer
  - engineer_coder
added_at: 2026-04-05T14:15:00Z
---
```

The script reads `agents_affected` from frontmatter first and falls back to
legacy body detection only for older docs that have not been updated yet.
You can also keep an `added_at` field in the same frontmatter when you want the
creation timestamp recorded directly in the migration doc.
The `status` field should reflect the doc lifecycle; keep it aligned with the
body narrative so investigation, active migration, implemented, and completed
records do not contradict each other.

## Required Shape

Follow this order unless a migration has a strong reason to add a small
section of its own:

01. `# Title`
02. Optional status comment such as `<!-- Investigation doc. No behavior change yet. -->`
    or `<!-- Implemented. ... -->`
03. Optional `## Status` section for completed or frozen records
04. `## Purpose`
05. `## Problem Statement`
06. `## Current-State Inventory`
07. `## Proposed Target State`
08. `## Required Work`
09. `## Non-Goals`
10. `## Sequencing`
11. `## Acceptance Criteria`
12. `## Migration Checklist` - detailed execution checklist. If it's too much to
13. `## File-Level Change Set`

Optional follow-up sections may include `Open Questions`, `Risks`, `Test Impact`,
`Verified This Pass`, `Seed and Fixture Updates`, `Completion Note`, and other
short migration-specific sections such as `Rollout Order`, `Assessment`,
`Resolved Decisions`, `Design Notes`, `Cleanup Checklist`,
`Implementation Checklist`, or `Phased Migration Shape` when they add distinct
contract value.

## Writing Rules

- Use declarative language for the contract sections: `Purpose`,
  `Problem Statement`, `Current-State Inventory`, `Proposed Target State`,
  `Non-Goals`, `Sequencing`, and `Acceptance Criteria`.
- Use action-oriented language for `Required Work` and the checklist, because
  those sections track implementation steps and verification status.
- Name the exact files, modules, routes, prompts, or artifacts that own the
  contract.
- Prefer concrete, testable statements over vague goals.
- Use plain Markdown only. Keep headers, lists, and tables simple.
- Use HTML comments only for temporary notes, investigation markers, or frozen
  reminders that are not part of the active contract.
- Keep repeated guidance minimal. If the same rule already appears elsewhere in
  the spec set, reference it instead of restating it.

### Validation Planning

- If a migration changes any agent-facing logic, treat eval updates as required
  follow-up work. The migration checklist should name each changed
  agent-facing surface and the eval artifacts that must be updated for it.
- During feature planning, inventory integration-test impact exhaustively
  before narrowing scope. As a rule of thumb, expect at least 10 existing
  integration tests to need updates per feature unless the migration doc
  explicitly justifies a smaller set.
- Define happy-path and negative-path tests.

## Section Guidance

### Purpose

- State the migration target in one short paragraph.
- Link the owning architecture spec or specs that define the desired state.
- Make clear whether the doc is an investigation, a planned implementation, or
  a completed migration record.

### Problem Statement

- Describe the current mismatch or failure mode.
- Explain why the current behavior is wrong for the target architecture.
- Keep the focus on the contract gap, not on coding steps.

### Current-State Inventory

- Use a table or compact bullet list.
- Include the relevant repo areas and the reason each one must change.
- Prefer exact file paths and runtime names over generic descriptions.

### Proposed Target State

- Write numbered, declarative outcomes.
- Each item should be verifiable.
- Make ownership and failure behavior explicit.
- Include only the state that the migration is meant to establish.

### Required Work

- Write these items as implementation tasks, not as passive system statements.
- Group work by contract area, plumbing, validation, docs, and tests.
- Use subsections when the migration spans several distinct surfaces.
- Keep the items bounded enough that each one can be checked off cleanly.

### Non-Goals

- State what this migration will not change.
- Use this section to prevent scope creep and accidental follow-on work.

### Sequencing

- List the safe implementation order when ordering matters.
- Keep the sequence short and practical.
- If ordering does not matter, say so directly.

### Acceptance Criteria

- Write concrete pass/fail statements.
- Tie each criterion to a visible contract, artifact, gate, or test.
- Use this section as the migration's success definition.

### Migration Checklist

- Use `[ ]` for pending items and `[x]` only when the item is actually done.
- Keep checklist items atomic and checkable.
- Put checklist items under topical subheadings when that makes the work easier
  to track.
- Mark an item complete only after the relevant integration evidence exists.
- If an item is no longer needed, leave a short written waiver instead of
  silently deleting the intent.
- Treat the checklist as the progress record for the migration.
- Phrase checklist items as concrete completion conditions, not aspirational
  goals.

Important: if you feel overwhelmed trying to create the checklist in a single go with the migrations, it's OK, first write the previous migration spec points, and ask the developer to create execution checklists separately. I would then complete the checklist separately.

### File-Level Change Set

- List the smallest realistic set of files that enforce the new contract.
- Include spec files, runtime files, prompt files, templates, tests, and seed
  fixtures when they are part of the change.
- If a file is only a temporary compatibility alias, say so explicitly.

## Completion Rule

When a migration is complete, update the lifecycle status, add a short
completion note, and keep the doc frozen unless a later architecture change
reopens the scope. Do not keep editing a finished migration as if it were a
living task list.

## Preferred Style

- Use the same direct, fail-closed tone as the architecture docs.
- Keep the document readable at a glance.
- Be specific about contracts, but avoid unnecessary verbosity.
- Treat the migration doc as the implementation record for that migration; the
  architecture docs remain the source of truth for the target state.
