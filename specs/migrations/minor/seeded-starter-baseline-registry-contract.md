title: Seeded Starter Baseline Registry Contract
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
added_at: '2026-04-15T18:02:00Z'
---

# Seeded Starter Baseline Registry Contract

<!-- Migration tracker. Check items conservatively as implementation lands. -->

## Purpose

This migration makes every seed-backed agent row that owns writable authored
files fail closed when any file the evaluated agent is expected to edit
already contains solved output instead of the checked-in starter baseline for
that exact path. This applies to all seed-backed rows, including planner,
coder, and reviewer rows wherever they own writable starter files.

The contract is intentionally explicit:

1. Any seed-backed agent row fails when a writable starter file differs from
   the checked-in starter baseline for that exact path.
2. The registry of writable starter files lives in `shared/eval_artifacts.py`
   and is consumed by both validation and seed-maintenance utilities.
3. The rule is enforced through the real node-entry validation path, so
   `scripts/validate_eval_seed.py` inherits it automatically.
4. Validation fails closed when the seeded workspace is missing one of those
   starter files or when the file content no longer matches the checked-in
   starter snapshot.
5. Review YAML outputs remain outside this starter-baseline rule because they
   are not starter-authored writable source files.

This is a seed-contract fix, not a workspace-template rewrite. The evaluated
agent must begin from the same starter file at the same path it will later
edit, instead of from a pre-solved output that hides template drift.

## Problem Statement

Some seed rows previously carried authored files that already looked solved,
even though the downstream agent was supposed to edit those exact paths.

That creates three problems for any seed-backed agent row with writable
starter files:

1. the seed validator can accept a row whose starter file is already partially
   or fully solved,
2. the checked-in template and the seeded workspace can drift apart without a
   failure, and
3. the eval row no longer reflects the real start state the downstream agent
   would see in a fresh workspace.

The issue is visible anywhere the agent is expected to edit writable starter
files, not just one role family.

The seed validator already has the right runtime seam to enforce this; the
missing piece is the explicit content comparison against the starter baseline.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `shared/eval_artifacts.py` | Exposes workspace artifact lists, but not yet a single starter-baseline registry for every seed-backed agent row. | The writable starter-file registry needs a shared home so validation and maintenance can consume one source of truth. |
| `controller/agent/node_entry_validation.py` | Validates seeded workspaces, but the starter-baseline rule is only partially enforced and can drift with file-specific checks. | The runtime gate needs one fail-closed comparison that reads the shared starter registry. |
| `scripts/validate_eval_seed.py` | Materializes the seed workspace and calls the shared validation path. | The CLI should inherit the same starter-baseline failure mode without adding a second contract. |
| `scripts/update_eval_seed_templates.py` | Maintainer utility for copying checked-in starter files into the seed corpus. | The seed corpus needs a simple refresh path that syncs the same shared registry before validation. |
| `evals/logic/workspace.py` | Seeds workspaces for eval validation and forwards the validation scope. | The eval helper must keep delegating to the shared starter registry instead of reimplementing starter checks. |
| `specs/devtools.md` | Mentions starter drift, but not the exact writable paths that must match the checked-in starter snapshot for every seed-backed row. | The maintainer docs need the exact file-level rule once, not separate per-role restatements. |
| `specs/architecture/agents/handover-contracts.md` | Describes seeded/direct-start validation at a high level. | The handover contract should name the starter-baseline expectation explicitly. |
| `specs/architecture/agents/artifacts-and-filesystem.md` | Defines file ownership and template permissions. | The filesystem contract should state that writable starter files must be seeded from the checked-in baseline. |
| `tests/integration/architecture_p0/test_node_entry_validation.py` | Covers starter drift, but does not yet prove every seed-backed row is enforced. | The integration suite needs negative regressions for writable starter-file drift. |
| `tests/integration/architecture_p0/test_codex_runner_mode.py` | Exercises the seed-validator CLI, but the seed outcome assertions must match the new starter-baseline state. | The CLI regression should prove starter-compliant rows still pass while pre-solved rows fail. |

## Proposed Target State

1. Every seed-backed agent row with writable authored files begins from the
   checked-in starter baseline for the paths that row expects the agent to
   edit.
2. The shared registry of writable starter files lives in `shared/eval_artifacts.py`.
3. The runtime validation path fails closed on missing starter files, content
   mismatches, or pre-solved output in any of those writable starter paths.
4. The CLI seed validator inherits the same behavior because it uses the
   controller validation seam rather than a separate heuristic.
5. Review YAML outputs remain outside this rule because they are not
   starter-authored writable source files.
6. The docs and integration tests describe the same starter-baseline rule that
   the controller enforces.

## Required Work

### 1. Define the shared starter registry

- Add a seed-starter registry to `shared/eval_artifacts.py`.
- Map every seed-backed agent row that owns writable authored files to the exact
  starter file paths that must be materialized and validated.
- Keep the registry explicit. Do not infer the set from workspace shape or
  path heuristics.

### 2. Enforce the starter baseline in node entry validation

- Keep the starter-baseline comparison in `controller/agent/node_entry_validation.py`.
- Compare the seeded workspace copy of each writable starter file against the
  canonical starter content for that exact path.
- Fail closed when the file is missing, unreadable, or different from the
  checked-in template.
- Apply the rule to every seed-backed row that owns writable starter files.

### 3. Route the CLI through the controller seam

- Keep `scripts/validate_eval_seed.py` as a thin maintainer-facing wrapper
  over the shared preflight path.
- Pass the chosen validation scope through unchanged.
- Do not reintroduce a separate CLI-side fallback or filename heuristic for
  starter detection.

### 4. Add a simple corpus refresh utility

- Add `scripts/update_eval_seed_templates.py` as a thin maintainer utility.
- Use the shared starter registry to copy starter files into the seed corpus.
- Keep the utility separate from validation so corpus refresh stays an explicit
  maintenance action.

### 5. Refresh the seed corpus

- Update the affected seed artifacts so the
  writable starter files are checked-in starter versions, not solved outputs.
- Keep read-only context files and review evidence files as they are unless
  they are part of the starter-baseline contract for that row.

### 6. Update docs and contract references

- Update `specs/devtools.md` to name the writable starter files that must match
  the checked-in baseline.
- Update `specs/architecture/agents/handover-contracts.md` so the seeded/direct
  start contract names the starter-baseline check.
- Update `specs/architecture/agents/artifacts-and-filesystem.md` so the file
  ownership rules make the starter-baseline expectation explicit for every
  seed-backed role.
- Keep the wording distinct from the validation-scope migration so the docs do
  not collapse the two contracts into one vague rule.

### 7. Add regression coverage

- Add regressions that overwrite writable starter files in the affected seed
  rows and prove the node-entry validator rejects them.
- Add a CLI regression that confirms the starter-compliant seed rows still pass
  through `scripts/validate_eval_seed.py`.

## Non-Goals

- Do not change reviewer-owned review YAML paths or their lifecycle.
- Do not change the benchmark or engineering predecessor gates themselves.
- Do not add a permissive fallback to accept solved starter files.
- Do not generalize the rule to files the agent only reads.
- Do not rename the starter-authored source files in this migration.

## Risks

1. If the starter-baseline check only covers a subset of seed-backed agent
   rows, the excluded rows can still drift silently.
2. If the CLI reimplements the comparison separately from the controller path,
   the two seed validators can diverge.
3. If solved starter files remain in the seed corpus, the integration suite can
   pass while the checked-in seed baseline is still wrong.

## Sequencing

The safe order is:

1. Add the shared starter registry in `shared/eval_artifacts.py`.
2. Enforce the starter-baseline comparison in the node-entry validation path.
3. Add the maintainer utility that copies the registry into the seed corpus.
4. Refresh the affected seed artifacts to checked-in starter content.
5. Update the maintainer docs and handover references.
6. Add the negative regressions for affected seed rows.
7. Re-run the relevant seed flows and the narrow seed-validator CLI slice.

## Acceptance Criteria

1. Any seed-backed agent row fails when a writable starter file differs from
   the checked-in starter baseline for that exact path.
2. Starter-compliant seed rows still validate successfully through
   `scripts/validate_eval_seed.py`.
3. The controller validation path is the single source of truth for the check.
4. The integration suite proves both the positive and negative cases for
   affected seed rows.

## File-Level Change Set

The implementation should touch the smallest set of files that actually
enforce the new contract:

- `shared/eval_artifacts.py`
- `controller/agent/node_entry_validation.py`
- `scripts/update_eval_seed_templates.py`
- `scripts/validate_eval_seed.py`
- `evals/logic/workspace.py`
- `specs/devtools.md`
- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `tests/integration/architecture_p0/test_node_entry_validation.py`
- `tests/integration/architecture_p0/test_codex_runner_mode.py`
- `dataset/data/seed/artifacts/**`
