---
title: Controller and Worker-Light Pruning After Pi SDK API Backend
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
added_at: '2026-04-16T07:20:00Z'
---

# Controller and Worker-Light Pruning After Pi SDK API Backend

<!-- Follow-on investigation. No behavior change yet. -->

## Purpose

This follow-on migration tracks the question of what the controller and
`worker-light` still need to own after `PiSdkApiBackend` exists and has parity.
The upstream backend migration owns the agent-session/runtime swap and the
tool-registration cleanup. This doc owns the later pruning decision: which
controller and worker-light responsibilities stay repo-owned, which become
compatibility-only, and which can be deleted when the Pi-backed path proves
itself.

The pruning goal is narrow. We are not trying to delete the control plane
because it exists. We are trying to remove duplicated runtime plumbing while
preserving the repo-owned contracts that make the system reproducible:

- workspace containment and path policy
- manifest ownership and handoff files
- review gates and submission semantics
- trace promotion and persistence for replay, debugging, and GRPO/fine-tuning

Relevant architecture context:

- [Pi SDK API Backend for Agent Tool Boilerplate](./pi-sdk-api-backend-for-agent-tool-boilerplate.md)
- [Agent harness](../../architecture/agents/agent-harness.md)
- [Agent artifacts and filesystem](../../architecture/agents/artifacts-and-filesystem.md)
- [Observability](../../architecture/observability.md)
- [Server-to-server networking](../major/server-to-server-networking.md)

## Problem Statement

The current runtime has three overlapping layers:

1. Pi or CLI providers handle the agent loop and model interaction.
2. The controller handles orchestration, persistence, routing, and tracing.
3. `worker-light` handles workspace CRUD, git, runtime execution, validation,
   preview/render, bundle export, and render-query.

That overlap is acceptable during the transition to Pi, but it is too much to
keep if Pi already covers containerized runtime isolation and the tool loop.
The repo needs a boundary that says:

1. what Pi owns
2. what the controller must still own
3. what `worker-light` can keep only for compatibility
4. what can be removed once the Pi-backed path is proven

Without that boundary, the codebase keeps duplicating runtime plumbing and the
pruning question never closes.

## Current-State Inventory

| Area | Current role | Pruning relevance |
| -- | -- | -- |
| `controller/api/main.py` and `controller/api/routes/*` | Expose control-plane routes for episodes, benchmarks, skills, and script tools. | Keep only the routes that remain repo-owned after Pi parity; the rest are candidates for collapse into a thinner coordination shell. |
| `controller/api/manager.py` | Tracks websocket connections and tasks for episode updates. | Keep if the controller remains the event hub; prune or simplify if Pi supplies equivalent session-level event delivery. |
| `controller/clients/worker.py` | Routes control traffic to worker-light and worker-heavy and manages transport details. | Strong candidate for shrinking once Pi owns the production runtime boundary. |
| `controller/middleware/remote_fs.py` | Enforces repo-owned filesystem policy and dispatches remote file operations. | Keep the policy layer; prune only transport-specific glue if Pi can execute the same operations natively. |
| `controller/observability/*` | Promotes traces, assets, and event records into repo-owned persistence. | Repo-owned persistence likely remains, but backend-specific glue may shrink. |
| `controller/agent/tools.py`, `controller/agent/benchmark/tools.py`, `controller/tools/fs.py` | Build the current runtime tool surface by hand. | Already upstream cleanup territory; this doc treats them as boilerplate to be removed before broader pruning starts. |
| `controller/api/routes/script_tools.py` | Bridges controller script-tool calls to worker-light for validation, simulation, and preview. | Candidate for simplification or removal if Pi provides direct isolated execution and render/validation parity. |
| `worker_light/api/routes.py` | Owns workspace CRUD, git, runtime execute, lint, validation, preview/render, render-query, and bundle export. | The clearest production-surface prune target if Pi can cover the same isolated runtime contract natively. |
| `worker_light/runtime/executor.py` | Executes commands in the worker-light runtime. | Keep only if the Pi-backed runtime cannot replace it for production or replay. |
| `worker_light/utils/filesystem/*` and `worker_light/utils/git/*` | Manage workspace files, local git state, and compatibility helpers. | These are likely compatibility-only once Pi owns the workspace container. |
| `worker_light/agent_files/` | Legacy compatibility mirror for bootstrap and local inspection. | Already documented as non-canonical; should remain only while needed for compatibility. |
| `evals/logic/codex_workspace.py`, `evals/logic/runner.py`, `evals/logic/stack_profiles.py` | Provide local CLI debug execution and stack wiring. | Keep for developer workflows until the production runtime no longer depends on them. |
| `shared/workers/filesystem/policy.py`, `config/agents_config.yaml` | Define repo-owned path permissions and tool access policy. | Never prune from the authoritative contract. |

## Investigation Findings

### What Pi seems to cover

- Pi is a plausible runtime substrate for isolated agent sessions and tool
  transport.
- Pi can cover the agent container, SDK/RPC loop, and the session boundary
  needed for production runs.
- Pi does not replace the repo-owned workflow contract. The repo still owns
  policy, persistence, and handoff semantics.

### What the controller still owns

- The controller remains the control plane: episode/session identity,
  websocket/task tracking, worker routing, persistence, and trace promotion.
- GRPO and fine-tuning still need durable run records. The reproducibility
  record remains the persisted trace and artifact trail, not just the live
  runtime session.
- The current eval stack still publishes separate controller and worker-light
  URLs, so the split remains until Pi parity is proven.

### What worker-light is doing today

- `worker-light` is not just a file proxy. It currently exposes workspace CRUD,
  git, runtime execution, lint, validation, preview/render, render query, and
  bundle export.
- The architecture docs still treat `worker-light` as the worker-plane route
  family under controller orchestration.
- `worker_light/agent_files/` is already a legacy compatibility mirror, not the
  canonical workspace source of truth.

### What can be pruned

- High confidence now: duplicated tool-wrapper boilerplate in
  `controller/agent/tools.py`, `controller/agent/benchmark/tools.py`, and
  `controller/tools/fs.py`.
- Medium confidence later: the `worker-light` route families once Pi proves
  parity for file ops, git, execution, lint, and preview/validation.
- Keep for now: `config/agents_config.yaml`, `.manifests/`, `PromptManager`, and
  anything that enforces path policy or promotes traces.

### Transmission model

- Seed the workspace into the Pi container or session.
- Let the agent mutate only that workspace.
- Export the allowed workspace tree, manifests, and trace bundle back to
  repo-owned storage.
- The controller then acts as an importer and orchestrator, not a byte relay.
- Pi likely owns the runtime and isolation layer; the repo still owns policy,
  persistence, and reproducibility.

### Bottom line

- The current engineering looks overbuilt in runtime and tool plumbing, not in
  the workflow contract.
- The right path is to keep the controller thin, prune `worker-light`
  aggressively once Pi parity is proven, and leave repo-owned
  policy/observability/handoff logic intact.
- The backend seam is already the right one: `cli_based` versus `api_based`.
- Pi fits as a backend, not as a new architecture layer.

## Proposed Target State

1. Pi owns the isolated agent container, tool execution, and session/runtime
   loop wherever it can do so natively.
2. The controller keeps only repo-owned coordination: episode/session
   correlation, persistence, trace promotion, handoff validation, and policy
   enforcement.
3. `worker-light` keeps only compatibility/debug surfaces until the Pi-backed
   runtime proves it can replace them safely.
4. The local CLI-provider path remains available for development, debugging, and
   reproducibility, but it is not the production control plane.
5. The repository's policy source of truth remains
   `config/agents_config.yaml` plus the filesystem middleware and filesystem
   policy implementation.
6. Production does not keep duplicate tool registration or duplicate workspace
   execution stacks once Pi parity is established.

## Required Work

### Controller scope

- Inventory the controller responsibilities that must stay repo-owned after Pi
  parity.
- Classify each controller route family as `keep`, `simplify`, or `remove`.
- Keep the controller as the authoritative place for persistence, trace
  promotion, and handoff validation if those concerns are still required.
- Remove controller-side transport glue only when Pi replaces the corresponding
  runtime capability directly.

### Worker-light scope

- Inventory the `worker-light` route families that are production runtime
  surfaces versus debug-only compatibility surfaces.
- Classify the following as explicit prune candidates:
  - `/fs/*`
  - `/git/*`
  - `/runtime/execute`
  - `/lint`
  - `/benchmark/validate`
  - `/benchmark/preview`
  - `/render/*`
  - `/topology/inspect`
- Keep only the compatibility paths needed for local CLI debugging, historical
  eval replay, or any route Pi cannot yet replace.
- Remove `worker-light` production surfaces only after the Pi-backed path proves
  equivalent isolation, observability, and artifact export.

### Pruning criteria

- A controller or worker-light capability is removable only if Pi can provide
  the same function inside an isolated session/container.
- The replacement must preserve workspace containment and repo-owned policy.
- The replacement must preserve the observability trail needed for replay and
  GRPO/fine-tuning.
- The replacement must pass the same integration boundary checks that currently
  defend the runtime contract.
- If a capability is about persistence, identity, or review gating, it likely
  remains repo-owned even if Pi owns the runtime loop.

## Non-Goals

- Do not remove controller persistence or observability.
- Do not remove repo-owned filesystem policy.
- Do not change the Pi backend seam or the prompt-source model.
- Do not remove the local CLI-provider debug path in this migration.
- Do not remove `worker-light` until the Pi-backed replacement has parity.
- Do not make Pi the source of truth for repository permissions or handoff
  semantics.
- Do not conflate this pruning investigation with the backend-swap migration.

## Sequencing

1. Wait for `PiSdkApiBackend` parity on the relevant tool surfaces.
2. Classify controller responsibilities into repo-owned keepers and prune
   candidates.
3. Classify `worker-light` route families into production, compatibility-only,
   and removable sets.
4. Remove controller-side wrapper duplication that Pi already replaces.
5. Remove `worker-light` production routes that the Pi-backed runtime fully
   covers.
6. Retain only the compatibility/debug surfaces that are still needed for
   development and replay.

## Acceptance Criteria

1. The repo contains an explicit keep/prune list for controller
   responsibilities.
2. The repo contains an explicit keep/prune list for `worker-light` route
   families.
3. Repo-owned filesystem policy and manifest ownership remain unchanged.
4. Every pruned runtime capability has a Pi-backed replacement that preserves
   containment, observability, and artifact export.
5. The production path no longer requires both controller and worker-light to
   duplicate the same runtime plumbing.
6. Local CLI debugging still works.
7. Reproducibility for GRPO/fine-tuning remains intact through persisted traces
   and artifacts.

## Migration Checklist

### Controller inventory

- [ ] Classify controller routes and helpers as `keep`, `simplify`, or `remove`.
- [ ] Confirm which controller duties remain required for persistence and trace
  promotion.
- [ ] Mark the controller transport glue that can disappear after Pi parity.

### Worker-light inventory

- [ ] Classify `worker-light` route families as production, compatibility-only,
  or removable.
- [ ] Confirm which worker-light runtime helpers are still needed for local
  debugging.
- [ ] Mark the worker-light production routes that Pi can replace natively.

### Decision gate

- [ ] Define the exact parity gate that must pass before any controller or
  worker-light pruning starts.
- [ ] Define the exact replay/trace requirement for GRPO and fine-tuning.
- [ ] Confirm the remaining repo-owned control plane is the smallest safe
  boundary.

## File-Level Change Set

The implementation should touch the smallest realistic set of files that would
actually enforce this follow-on pruning decision:

| Category | Files |
| -- | -- |
| Controller routing | `controller/api/main.py`, `controller/api/routes/script_tools.py`, `controller/api/routes/episodes.py`, `controller/api/routes/benchmark.py`, `controller/api/routes/skills.py` |
| Controller orchestration | `controller/api/manager.py`, `controller/clients/worker.py`, `controller/middleware/remote_fs.py`, `controller/observability/*` |
| Worker runtime | `worker_light/api/routes.py`, `worker_light/runtime/executor.py`, `worker_light/utils/filesystem/*`, `worker_light/utils/git/*`, `worker_light/config.py` |
| CLI/debug compatibility | `evals/logic/codex_workspace.py`, `evals/logic/runner.py`, `evals/logic/stack_profiles.py` |
| Policy source of truth | `config/agents_config.yaml`, `shared/workers/filesystem/policy.py` |
| Upstream dependency | `specs/migrations/minor/pi-sdk-api-backend-for-agent-tool-boilerplate.md` |

## Open Questions

- Which controller duties remain truly required if Pi provides containerized
  isolation and session observability?
- Which `worker-light` route families are pure compatibility and which are
  still production requirements?
- Can the controller be reduced to persistence and policy glue without losing
  replayability or trace fidelity?
- Can `worker-light` be removed from production entirely, or does the repo need
  a thin compatibility bridge for long-term debugging?
- Which runtime pieces are still needed specifically for GRPO/fine-tuning
  repeatability once the agent loop moves into Pi?
