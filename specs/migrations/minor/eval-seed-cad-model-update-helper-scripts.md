---
title: Eval Seed CAD Model Update Helper Scripts
status: investigation
agents_affected:
  - benchmark_planner
  - benchmark_coder
  - engineer_planner
  - engineer_coder
added_at: '2026-04-22T00:00:00Z'
---

# Eval Seed CAD Model Update Helper Scripts

<!-- Investigation doc. No behavior change yet. -->

## Purpose

This migration adds two fail-closed helper scripts for CAD-bearing eval work:

1. a maintainer-facing script in `scripts/` for seed-corpus refresh work, and
2. a workspace-copied helper for active CAD-editing agents.

The target contract is:

1. CAD-derived seed artifacts are updated mechanically from the authoritative
   markdown/source inputs and the already-computed CAD values, not by hand.
2. The maintainer script updates only the role-writable non-markdown CAD files
   for the selected seed row(s) and can refresh renders by default.
3. The workspace helper reads `.manifests/current_role.json` and updates only
   the active role's writable CAD files.
4. Non-CAD roles fail closed.
5. Read-only benchmark context is never rewritten from an engineer-planner
   invocation.
6. The updater reuses the same canonicalization logic that validation uses for
   CAD values, so the written YAML/JSON matches the validator's expected
   schema and numbers.

This is a contract-and-utility migration, not a new CAD language. The helper
scripts reduce repeated LLM work when a seed maintainer or CAD-editing agent
already knows the numeric values and just needs to fan them into the correct
files.

The first rollout is engineer_planner seed creation, but the writable-target
registry is already shaped so benchmark_planner, benchmark_coder, and
engineer_coder can use the same contract without a second migration.

## Problem Statement

The current seed-update path still requires manual syncing of several CAD
files after a planner or coder changes a design.

The pain is visible in the current engineer-planner seed workflow:

1. the maintainer updates a seed worktree by hand,
2. the CAD-derived YAML and Python evidence files are refreshed separately from
   the narrative markdown,
3. render bundles are refreshed in another pass, and
4. the role-specific writable-file boundary is enforced only by memory and
   validation, not by a dedicated updater contract.

That creates two failure modes:

1. the same CAD value gets recomputed or retyped in multiple places, and
2. writable CAD files can drift while read-only benchmark context is touched
   by mistake.

The repo already has a fail-closed current-role contract and a validation
contract. The missing piece is a small updater utility that writes the same
canonical values those validators expect.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `scripts/update_eval_seed_templates.py` | Copies starter templates into seed artifacts, but only refreshes starter-baseline files. | It does not update the CAD-derived YAML/Python values that still require manual syncing. |
| `scripts/update_eval_seed_renders.py` | Regenerates deterministic seed renders, but only as a separate pass. | CAD-value refresh and render refresh should be coordinated by one maintainer-facing helper. |
| `dataset/evals/eval_seed_update_autopilot_per_seed.py` | Orchestrates template and render refresh as separate steps. | The autopilot still has a manual CAD-value sync gap. |
| `evals/logic/codex_workspace.py` | Materializes workspace helper scripts, but no CAD-update helper is copied into CAD-editing workspaces. | Active CAD-editing roles need a workspace-local helper that can update only their writable CAD files. |
| `shared/eval_artifacts.py` | Tracks starter-template files, but not a role-scoped CAD-update target registry. | The updater needs an explicit writable-file registry per CAD-editing role. |
| `shared/agent_templates/codex/scripts/submit_plan.py`, `submit_review.py`, `submit_for_review.py` | Already read `.manifests/current_role.json` and fail closed on role inference. | The CAD updater should use the same fail-closed role source instead of guessing from workspace shape. |
| `specs/devtools.md` | Documents validation and render refresh utilities, but not a CAD model updater. | Maintainer docs need the new entrypoint and its default render behavior. |
| `specs/architecture/agents/tools.md` | Documents command-like helper bridges, but not a CAD updater bridge. | Agent-facing docs need the workspace helper and its role gate. |
| `specs/architecture/agents/artifacts-and-filesystem.md` | Documents file ownership, but not the updater's writable-only discipline. | The helper must be documented as touching only writable CAD files and never read-only benchmark context. |
| `.agents/skills/eval-creation-workflow/SKILL.md` | Tells seed authors to use the existing template and render refresh tools. | Seed authors need the CAD-update helper called out explicitly. |
| `.agents/skills/runtime-script-contract/SKILL.md` | Describes the runtime script contract, but not the new workspace CAD updater. | Workspace scripts need an explicit contract for the role-gated updater and its writable-file boundary. |

## Proposed Target State

1. There is a maintainer-facing script at `scripts/update_eval_seed_cad_model.py`.
2. The maintainer script accepts the existing maintainer selection style:
   `--agent` chooses the role family, `--task-id` narrows to one row, and the
   script can use the same filtering conventions as the other seed-maintenance
   utilities.
3. The maintainer script updates only the role-writable non-markdown CAD files
   for the selected row.
4. The maintainer script defaults to refreshing renders and accepts
   `--no-update-renders` to suppress that side effect.
5. The maintainer script does not rewrite markdown files, prompt files,
   journals, manifests, or any read-only benchmark context.
6. There is a workspace-copied helper at
   `shared/agent_templates/codex/scripts/update_cad_model.py`, exposed through
   the normal workspace helper-copy path and, if the implementation keeps a
   command bridge, through a shell wrapper in the same directory.
7. The workspace helper reads `.manifests/current_role.json` and fails closed
   if the manifest is missing, malformed, or names a non-CAD role.
8. The workspace helper updates only the writable CAD files for the active
   role and never writes read-only benchmark fixtures from an engineer-planner
   workspace.
9. The updater core uses one explicit writable-target registry per CAD-editing
   role.

| Role | Writable CAD targets |
| -- | -- |
| `benchmark_planner` | `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_plan_evidence_script.py` |
| `benchmark_coder` | `benchmark_script.py` |
| `engineer_planner` | `benchmark_definition.yaml`, `assembly_definition.yaml`, `solution_plan_evidence_script.py` |
| `engineer_coder` | `solution_script.py`, `payload_trajectory_definition.yaml` |

10. The updater core reuses the same canonical validation/normalization logic
    that seed validation and planner costing use for CAD-derived values, so
    the updater writes the same schema shape and numbers that validation later
    accepts.
11. `benchmark_planner`, `benchmark_coder`, `engineer_planner`, and
    `engineer_coder` can all use the helper; reviewers and other non-CAD roles
    fail closed.
12. `engineer_planner` invocations never mutate benchmark-owned read-only
    files such as `benchmark_assembly_definition.yaml` or
    `benchmark_script.py`.

## Required Work

### 1. Define the shared CAD-update registry and core

- Add a role-scoped writable CAD target registry to `shared/eval_artifacts.py`.
- Add a shared updater module under `evals/logic/` that both scripts can
  import.
- Reuse the same canonicalization logic that validation uses for CAD-derived
  values instead of reimplementing the numeric derivation in the updater.
- Make the shared updater accept structured computed values, not freeform prose,
  so the agent can paste numbers once and fan them into the correct files.

### 2. Add the maintainer-facing seed updater

- Add `scripts/update_eval_seed_cad_model.py`.
- Make it follow the same row-selection conventions as the other seed
  maintenance scripts, including `--agent` and `--task-id`.
- Make it write only the writable CAD-derived files for the selected role.
- Make `--no-update-renders` suppress render refresh and keep the default path
  render-updating.
- Route render refresh through the existing seed-render machinery rather than
  inventing a second render contract.
- Integrate the new maintainer script into the seed-update autopilot so the
  autopilot can refresh CAD values before the validation/render passes.

### 3. Add the workspace-copied CAD helper

- Add `shared/agent_templates/codex/scripts/update_cad_model.py`.
- Add a shell bridge alongside it if the command surface needs one in the
  copied workspace.
- Gate the helper on `.manifests/current_role.json`.
- Fail closed for non-CAD roles and malformed role manifests.
- Restrict writes to the role's explicit writable CAD target set.
- Copy the helper into CAD-editing workspaces through
  `evals/logic/codex_workspace.py`.

### 4. Update docs and skills

- Update `specs/devtools.md` to document the maintainer script and its default
  render behavior.
- Update `specs/architecture/agents/tools.md` to document the workspace helper
  as a checked-in command-like bridge for CAD-editing roles.
- Update `specs/architecture/agents/artifacts-and-filesystem.md` to make the
  writable-only boundary explicit for the updater and to name the helper as
  runtime-owned workspace tooling.
- Update `.agents/skills/eval-creation-workflow/SKILL.md` so seed authors use
  the new maintainer script instead of manually syncing CAD-derived files.
- Update `.agents/skills/runtime-script-contract/SKILL.md` so workspace authors
  know the CAD updater is role-gated and writable-file scoped.

## Non-Goals

- Do not change the seeded eval row schema.
- Do not change validation semantics or the meaning of `current_role.json`.
- Do not add a new render backend or a second preview contract.
- Do not let the updater write read-only benchmark-owned context from an
  engineer-planner workspace.
- Do not rewrite markdown plans, todo lists, journals, or prompt files through
  this helper.
- Do not make the updater a substitute for validation, simulation, or
  submission.

## Sequencing

The safe order is:

1. Add the shared writable-target registry and updater core.
2. Add the maintainer script and wire it into the seed-update autopilot path.
3. Add the workspace-copied helper and the role gate based on
   `current_role.json`.
4. Update the docs and skills.
5. Verify engineer-planner rows first, then confirm the helper fails closed
   for a non-CAD role.

## Acceptance Criteria

1. Running the maintainer script on a seed row updates only the row's
   writable CAD-derived files and leaves markdown untouched.
2. Running the maintainer script with `--no-update-renders` suppresses render
   refresh, while the default path refreshes renders through the existing seed
   render machinery.
3. Running the workspace helper in a non-CAD role workspace fails closed on
   the current-role manifest and writes nothing.
4. Running the workspace helper in an engineer-planner workspace cannot modify
   read-only benchmark-owned files such as `benchmark_assembly_definition.yaml`
   or `benchmark_script.py`.
5. The updater and the validator agree on the canonical numeric values and
   schema output for the refreshed CAD files.
6. The docs and skills name the maintainer script, the workspace helper, and
   the writable-file boundary in the same terms as the code contract.

## Migration Checklist

### Core contract

- [ ] Add the shared writable CAD target registry.
- [ ] Extract the shared CAD-update core used by both scripts.
- [ ] Reuse validation-side canonicalization instead of hand-rolled value
  serialization.

### Maintainer script

- [ ] Add `scripts/update_eval_seed_cad_model.py`.
- [ ] Make the maintainer script row-selectable with `--agent` and
  `--task-id`.
- [ ] Make render refresh opt-out through `--no-update-renders`.
- [ ] Wire the maintainer script into the seed-update autopilot path.

### Workspace helper

- [ ] Add `shared/agent_templates/codex/scripts/update_cad_model.py`.
- [ ] Add the workspace shell bridge if the command surface needs one.
- [ ] Copy the helper into CAD-editing workspaces through `codex_workspace`.
- [ ] Fail closed for non-CAD roles and malformed current-role manifests.

### Docs and skills

- [ ] Update `specs/devtools.md`.
- [ ] Update `specs/architecture/agents/tools.md`.
- [ ] Update `specs/architecture/agents/artifacts-and-filesystem.md`.
- [ ] Update `.agents/skills/eval-creation-workflow/SKILL.md`.
- [ ] Update `.agents/skills/runtime-script-contract/SKILL.md`.

## File-Level Change Set

The implementation should touch the smallest set of files that actually
enforce the new contract:

- `scripts/update_eval_seed_cad_model.py`
- `evals/logic/cad_model_update.py`
- `shared/eval_artifacts.py`
- `dataset/evals/eval_seed_update_autopilot_per_seed.py`
- `shared/agent_templates/codex/scripts/update_cad_model.py`
- `shared/agent_templates/codex/scripts/update_cad_model.sh`
- `evals/logic/codex_workspace.py`
- `specs/devtools.md`
- `specs/architecture/agents/tools.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `.agents/skills/eval-creation-workflow/SKILL.md`
- `.agents/skills/runtime-script-contract/SKILL.md`
