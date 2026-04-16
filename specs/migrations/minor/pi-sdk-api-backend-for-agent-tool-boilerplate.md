---
title: Pi SDK API Backend for Agent Tool Boilerplate
status: investigation
agents_affected:
  - benchmark_planner
  - benchmark_plan_reviewer
  - benchmark_coder
  - benchmark_reviewer
  - engineer_planner
  - engineer_plan_reviewer
  - engineer_coder
  - engineer_execution_reviewer
added_at: '2026-04-16T06:04:41Z'
---

# Pi SDK API Backend for Agent Tool Boilerplate

<!-- Investigation doc. No behavior change yet. -->

## Purpose

This migration replaces the duplicated agent-tool boilerplate with a
`PiSdkApiBackend` implementation that owns agent-session setup, prompt/tool
transport, and the standard tool registration path for API-backed runs.

The repository still owns workspace policy, file ownership, handoff gates, and
permission enforcement. If Pi exposes native filesystem or sandbox hooks, this
migration uses them only as adapters around repo policy, not as a second source
of truth.

The target state is described in:

- [Agent harness](../../architecture/agents/agent-harness.md)
- [Agent tools](../../architecture/agents/tools.md)
- [Prompt management](../../architecture/agents/prompt-management.md)
- [Agent artifacts and filesystem](../../architecture/agents/artifacts-and-filesystem.md)

## Problem Statement

The current agent runtime repeats the same tool and filesystem boilerplate in
multiple places. The common filesystem tools are assembled manually in
`controller/tools/fs.py`, the controller agent runtime repeats the same tool
surface in `controller/agent/tools.py`, and the benchmark path re-exports a
similar surface in `controller/agent/benchmark/tools.py`.

Prompt assembly also still teaches the boilerplate back to the model through
`config/prompts.yaml` and `controller/agent/prompt_manager.py`. That makes the
tool surface feel like prompt content instead of runtime registration.

At the same time, the repository already has a fail-closed policy layer for
path containment, workspace ownership, review artifacts, and `.manifests/`
access. That policy lives in repo-owned config and middleware, so the backend
swap must not move it into the SDK or make it dependent on Pi defaults.

The result is duplicated code, duplicated prompt text, and a blurry boundary
between runtime plumbing and policy. The migration should remove the boilerplate
without changing the repository-owned contract.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `controller/tools/fs.py` | Builds a plain callable filesystem tool set by hand. | The standard filesystem tool surface should be registered once by the backend, not copied into a helper wrapper. |
| `controller/agent/tools.py` | Assembles the common controller-side tool list and mixes runtime helpers with boilerplate tool wiring. | The backend should own the shared tool registration path instead of each runtime layer rebuilding it. |
| `controller/agent/benchmark/tools.py` | Recreates the same shared tool surface for the benchmark graph and adds planner-specific wrappers on top. | The benchmark path should consume the same backend-owned tool surface rather than carrying a separate copy. |
| `controller/agent/nodes/base.py` | Applies tool-call handling, visual-inspection enforcement, and runtime prompt wiring. | Backend plumbing should stay thin so this file can focus on node behavior instead of tool bootstrapping. |
| `controller/agent/prompt_manager.py` and `config/prompts.yaml` | Still carry backend-specific prompt reminders and tool-surface wording. | Prompt text should stop re-teaching boilerplate that the backend can register directly. |
| `config/agents_config.yaml` | Centralizes filesystem permissions, tool allowlists, and role policy. | This must remain the authoritative policy source even if Pi exposes native enforcement hooks. |
| `controller/middleware/remote_fs.py` and `shared/workers/filesystem/policy.py` | Enforce path containment, read/write restrictions, and repo-owned workspace policy. | These checks remain the contract boundary and must not be replaced by SDK defaults. |

## Proposed Target State

1. `CustomApiBackend` remains the current repository-owned implementation, and
   `PiSdkApiBackend` becomes the new SDK-backed implementation for API runs.
2. The backend owns agent-session startup, tool registration, and prompt/tool
   transport. The runtime no longer reassembles the same boilerplate in
   multiple controller modules.
3. Repo-owned filesystem policy remains authoritative. `config/agents_config.yaml`,
   `controller/middleware/remote_fs.py`, and `shared/workers/filesystem/policy.py`
   continue to define what is allowed.
4. If Pi offers filesystem or sandbox hooks, they are used only as enforcement
   adapters around the repo policy. They do not broaden access and they do not
   become the canonical policy definition.
5. Prompt sources stay thin. They can mention the active backend family, but
   they do not restate the full standard tool list or the permission contract.
6. Submission helpers, review routing, manifest ownership, and workspace
   artifact names remain unchanged.

## Required Work

### Backend seam

- Define a small `ApiBackend` contract that covers session setup, tool
  registration, prompt/tool transport, and any backend-specific environment
  preparation.
- Implement `CustomApiBackend` behind that contract as the current behavior.
- Implement `PiSdkApiBackend` behind the same contract.
- Move the common tool registration into the backend layer so the runtime can
  consume one backend-owned tool catalog.

### Policy boundary

- Keep the repo-owned filesystem policy as the source of truth.
- Wire any Pi permission hooks through the repo policy instead of treating Pi as
  the authority for allow/deny decisions.
- Preserve `.manifests/` denial, reviewer-write narrowing, and workspace
  containment checks exactly as they work today.

### Prompt and boilerplate cleanup

- Remove duplicated tool-surface wording from `config/prompts.yaml` and the
  prompt-manager appendices where it is only repeating runtime registration.
- Keep `controller/agent/prompt_manager.py` as the merge point for prompt
  sources and runtime context.
- Collapse the plain filesystem tool wrapper in `controller/tools/fs.py` and
  the shared controller agent wrappers into backend-owned registration.

### Validation

- Add integration coverage for backend selection between `CustomApiBackend` and
  `PiSdkApiBackend`.
- Add integration coverage that proves forbidden paths still fail when the Pi
  backend is active.
- Keep submission and review artifact behavior unchanged while the backend seam
  is introduced.

## Non-Goals

- Do not replace `config/agents_config.yaml` with Pi-managed permissions.
- Do not remove `controller/middleware/remote_fs.py` or
  `shared/workers/filesystem/policy.py`.
- Do not change the CLI-provider seam or `PiCliProvider`.
- Do not change benchmark or engineering handoff semantics.
- Do not change render, simulation, or review artifact naming.
- Do not introduce a new prompt source model or a second prompt manager.
- Do not remove the current custom API backend until the Pi-backed path has
  parity on the relevant tool surfaces.

## Sequencing

1. Define the `ApiBackend` seam and the `PiSdkApiBackend` implementation.
2. Route tool registration through the backend while keeping repo policy
   enforcement in place.
3. Trim prompt and boilerplate repetition once the backend is the source of
   runtime truth.
4. Add backend parity tests for tool registration and filesystem rejection.
5. Remove any temporary compatibility wrappers only after the parity tests pass.

## Acceptance Criteria

1. The agent runtime can run through `PiSdkApiBackend` without rebuilding the
   standard tool boilerplate in multiple controller modules.
2. The repository still rejects forbidden filesystem access according to repo
   policy, even if Pi would otherwise allow it.
3. Prompt text no longer re-teaches the same standard tool boilerplate in
   multiple places.
4. Submission, review, and manifest artifacts still land in the same stage-owned
   files after the backend swap.
5. The custom backend and the Pi-backed backend expose the same supported tool
   surfaces for the roles that rely on them.
6. Integration coverage demonstrates that Pi backend selection does not change
   workspace ownership or policy enforcement.
7. Existing CLI-provider runs continue to work unchanged through
   `PiCliProvider`.

## Migration Checklist

### Backend seam

- [ ] Define the `ApiBackend` contract.
- [ ] Implement `CustomApiBackend` behind that seam.
- [ ] Implement `PiSdkApiBackend` behind that seam.
- [ ] Route the common tool registration through the backend.

### Policy boundary

- [ ] Keep repo-owned filesystem policy as the authoritative allow/deny source.
- [ ] Wire any Pi filesystem or sandbox hooks through repo policy only.
- [ ] Preserve `.manifests/` denial and reviewer-write narrowing.

### Prompt and boilerplate cleanup

- [ ] Remove duplicated tool boilerplate from `config/prompts.yaml`.
- [ ] Collapse the plain filesystem wrapper in `controller/tools/fs.py`.
- [ ] Slim the controller agent tool factories so they consume backend-owned
      registration.

### Validation

- [ ] Add parity coverage for `CustomApiBackend` and `PiSdkApiBackend`.
- [ ] Add a filesystem rejection test for the Pi-backed path.
- [ ] Confirm submission and review artifacts still use the existing file
      contract.

## File-Level Change Set

The implementation should touch the smallest realistic set of files that
actually enforce the new contract:

| Category | Files |
| -- | -- |
| Runtime | `controller/tools/fs.py`, `controller/agent/tools.py`, `controller/agent/benchmark/tools.py`, `controller/agent/nodes/base.py` |
| Prompting | `controller/agent/prompt_manager.py`, `config/prompts.yaml` |
| Policy | `config/agents_config.yaml`, `controller/middleware/remote_fs.py` |
| Docs | `specs/architecture/agents/agent-harness.md`, `specs/architecture/agents/tools.md`, `specs/architecture/agents/prompt-management.md`, `specs/architecture/agents/artifacts-and-filesystem.md` |
| Tests | `tests/integration/architecture_p0/test_int_pi_sdk_api_backend.py` |

## Open Questions

- Should the backend seam be named `ApiBackend` or `AgentBackend` in the code
  to avoid any collision with model-provider terminology?
- Should Pi permission hooks be required for the backend to start, or should the
  runtime always be able to fall back to repo-owned enforcement?
