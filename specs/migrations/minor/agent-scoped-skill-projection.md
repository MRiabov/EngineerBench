---
title: Agent-Scoped Skill Projection
status: completed
agents_affected:
  - benchmark_planner
  - benchmark_plan_reviewer
  - benchmark_coder
  - benchmark_reviewer
  - engineer_planner
  - engineer_plan_reviewer
  - engineer_coder
  - engineer_execution_reviewer
added_at: '2026-04-17T07:52:28Z'
---

# Agent-Scoped Skill Projection

<!-- Implemented. Skill projection now filters role-owned skill directories by agent. -->

## Purpose

This migration refines the worker projection policy described in
[agent-skill-repo-root-and-worker-projection-config.md](./agent-skill-repo-root-and-worker-projection-config.md)
so role-owned skill directories are copied only into the workspaces for the
agent that actually needs them.

The target is narrow on purpose:

- role-specific skills become agent-scoped,
- shared skills keep the existing worker-wide projection behavior,
- `config/skills_config.yaml` becomes the place that says which agent owns a
  given role-specific skill directory.

The immediate context-management goal is to stop copying irrelevant role
guidance into unrelated workspaces. For example, `engineer_coder` should not
be projected into `benchmark_planner` or `engineer_execution_reviewer`
workspaces unless that skill is explicitly assigned there.

## Problem Statement

The current workspace materialization path copies the full `.agents/skills/`
tree into every CLI-backed eval workspace.
That keeps the code simple, but it also spreads role-specific instructions
across agents that do not use them.

The existing projection metadata is too coarse for that problem:

1. `config/skills_config.yaml` only expresses whether a skill is worker-facing.
2. It does not say which agent should receive a role-owned skill directory.
3. The copy step therefore cannot distinguish between a shared skill and a
   skill that is only meaningful to one benchmark or engineer role.
4. The result is unnecessary context noise in agent workspaces and a weaker
   boundary between agent-owned instructions and shared references.

## Current-State Inventory

| Area | Current behavior | Why it matters |
| -- | -- | -- |
| `evals/logic/codex_workspace.py` | `_copy_skills_tree()` copies every skill directory into every materialized workspace. | Role-specific skills are duplicated into unrelated agent workspaces. |
| `config/skills_config.yaml` | Stores a flat `is_for_worker_agents: true` flag per skill. | It cannot declare which agent owns a role-specific skill directory. |
| `shared/skills/catalog.py` | Loads projection policy as a boolean worker flag. | The helper layer has no role-scoped ownership concept. |
| `scripts/update_skills_lock.py` | Warns about missing projection entries, but only at the flat skill level. | The lock-time check is not aligned with agent-specific ownership. |
| `tests/integration/architecture_p0/test_codex_runner_mode.py` | Asserts that a skills tree exists, but not that unrelated role skills are absent. | There is no regression coverage for filtered skill projection. |

## Proposed Target State

1. Role-specific skill directories are copied only into workspaces for the
   agent or agents named in `config/skills_config.yaml`.
2. Shared skills continue to project through the existing worker-wide path and
   are not part of the agent-scoped ownership rule.
3. A `benchmark_planner` workspace does not receive `engineer_coder`-only
   skill directories, and an `engineer_execution_reviewer` workspace does not
   receive `benchmark_planner`-only skill directories.
4. The ownership rule is explicit in `config/skills_config.yaml` and does not
   depend on prompt text, workspace filenames, or other heuristics.
5. Workspace materialization stays deterministic and fail-closed for
   role-owned skills: if a skill is not assigned to the active agent, it is
   not projected into that workspace.

## Required Work

### 1. Define agent ownership in the skill config

- Replace the flat worker flag for role-owned skills with an explicit
  agent-ownership list in `config/skills_config.yaml`.
- Keep the config readable as deployment policy rather than as a second source
  of skill content.
- Leave shared skills on the existing broad projection rule.

### 2. Filter workspace skill copying

- Update `evals/logic/codex_workspace.py` so the skill copy step accepts the
  active agent and skips role-owned skills that do not belong to that agent.
- Keep the copy order and workspace layout stable for the skills that remain
  projected.
- Preserve the current canonical skill source at `.agents/skills/`.

### 3. Align helper checks

- Update `shared/skills/catalog.py` and `scripts/update_skills_lock.py` so the
  projection metadata can answer which agent owns a role-specific skill.
- Keep warning behavior non-destructive.
- Do not reintroduce a second skill source or a prompt-driven projection rule.

### 4. Add narrow integration coverage

- Add a benchmark-role materialization check that proves unrelated engineer
  role skills are absent.
- Add an engineer-role materialization check that proves unrelated benchmark
  role skills are absent.
- Keep the assertions focused on the materialized workspace snapshot rather
  than on mocked path filters.

## Non-Goals

- Do not change the canonical `.agents/skills/` repository root.
- Do not change controller-side prompt assembly or the `/skills` mount.
- Do not remove shared skills from worker workspaces.
- Do not broaden this into a skill promotion or sync redesign.
- Do not change the existing skill content format.

## Sequencing

The safe order is:

1. Define the ownership shape in `config/skills_config.yaml`.
2. Update CLI workspace materialization to filter role-owned skills by active
   agent.
3. Align helper warnings and lock-time checks with the new ownership shape.
4. Add targeted integration coverage for one benchmark role and one engineer
   role.

## Acceptance Criteria

1. Role-specific skill directories are absent from unrelated agent workspaces.
2. Shared skills still appear where they appeared before.
3. The owning agent for each role-specific skill is readable from
   `config/skills_config.yaml`.
4. The filtered projection behavior is covered by the integration suite.
5. No runtime path guesses skill ownership from workspace shape or prompt
   content.

## Migration Checklist

### Skill ownership

- [x] Add explicit agent ownership metadata for role-specific skills in
  `config/skills_config.yaml`.
- [x] Keep shared skills on the current broad projection path.

### Workspace projection

- [x] Filter `evals/logic/codex_workspace.py` by active agent before copying
  role-owned skills.
- [x] Preserve the existing workspace layout for skills that remain projected.

### Verification

- [x] Add an integration assertion for a benchmark role workspace.
- [x] Add an integration assertion for an engineer role workspace.
- [x] Confirm unrelated role skill directories are absent in both cases.

## Completion Note

The runtime now projects role-owned skills only into their owning agent
workspaces, while shared skills remain available to every worker workspace.

## File-Level Change Set

The implementation should touch the smallest set of files that actually
enforce the new contract:

- `evals/logic/codex_workspace.py`
- `shared/skills/catalog.py`
- `config/skills_config.yaml`
- `scripts/update_skills_lock.py`
- `tests/integration/architecture_p0/test_codex_runner_mode.py`
- `specs/integration-test-list.md` if a new or updated row is needed
- `specs/architecture/agents/agent-skill.md`
- `specs/architecture/agents/agent-harness.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
