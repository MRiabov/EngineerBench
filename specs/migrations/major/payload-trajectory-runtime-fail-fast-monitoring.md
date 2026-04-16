---
title: Payload Trajectory Runtime Fail-Fast Monitoring
status: migration
agents_affected:
  - engineer_planner
  - engineer_plan_reviewer
  - engineer_coder
  - engineer_execution_reviewer
added_at: '2026-04-08T17:53:27Z'
---

# Payload Trajectory Runtime Fail-Fast Monitoring

<!-- Major migration. Static payload proof already exists; this migration adds runtime fail-fast enforcement. -->

## Purpose

This migration makes the engineer-owned payload trajectory a mandatory runtime stop condition. The simulation loop should fail fast when the realized motion can no longer stay inside the approved trajectory corridor, satisfy the required first-contact order, or prove the terminal goal-zone state. The target behavior completes the mandatory static payload-trajectory contract already defined in `specs/migrations/major/payload-trajectory-rotation-envelope-and-swept-clearance-migration.md` and the file-level acceptance criteria in `specs/architecture/agents/agent-artifacts/payload_trajectory_definition_yaml_acceptance_criteria.md`.

The runtime monitor applies only to engineer-owned motion. Benchmark-owned motion remains governed by the benchmark motion contract and does not become part of this monitor.

## Status

The runtime monitor, failure enum, structured state, config policy, observability mapping, docs, and regression coverage are in place. This file now records the completed migration rather than an open design.

## Problem Statement

The repository already validates the payload path statically, but the execution path does not yet enforce that path as a live runtime contract.

1. `payload_trajectory_definition.yaml` proves a build-safe start, terminal `goal_zone_entry` / `goal_zone_contact` via `terminal_event`, and swept clearance, but that proof is static and always required.
2. `worker_heavy/simulation/loop.py` currently stops on generic simulation success and failure conditions only.
3. A payload can drift away from the intended anchor sequence and continue running until an unrelated terminal event occurs.
4. The current runtime does not expose a dedicated payload-trajectory failure reason or structured observability payload for the last checked anchor.
5. The docs already describe fail-fast behavior in broad terms, but the runtime contract is not yet concrete enough to enforce or inspect deterministically.

## Current-State Inventory

The inventory below is the pre-cutover snapshot retained for traceability.

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `worker_heavy/simulation/loop.py` | Stops on generic physics failures, goal reach, out-of-bounds, overload, and wire failure. It does not supervise the realized payload against the approved trajectory monitor. | Runtime can drift off the intended path without a trajectory-specific stop. |
| `shared/enums.py` | `FailureReason` has no payload-trajectory contract violation reason. | The runtime needs a dedicated machine-readable stop reason. |
| `shared/models/simulation.py` | `SimulationFailure` and `SimulationResult` carry coarse failure data only. | Review and replay need a dedicated stop symbol and structured details. |
| `shared/observability/schemas.py` | `SimulationMetadata` and `SimulationResultEvent` record generic failure data only. | Observability needs the last checked anchor and deviation context. |
| `config/agents_config.yaml` | Motion policy exists for static validation budgets, but no runtime monitor policy or `consecutive_miss_count` threshold exists. | The early-stop rule must be fail-closed and policy-driven, not hardcoded. |
| `worker_heavy/utils/payload_trajectory_validation.py` | Proves the static trajectory proof and swept clearance. | The runtime monitor must consume that proof, not silently duplicate or replace it. |
| `specs/architecture/simulation-and-rendering.md` | Describes fail-fast behavior in prose, but not as a concrete `payload_trajectory_monitor` contract. | The runtime semantics need to be explicit and testable. |
| `specs/architecture/agents/agent-artifacts/payload_trajectory_definition_yaml_acceptance_criteria.md` | Requires the path to be safe and coherent, but does not describe the runtime stop condition. | The file-level contract should match the execution behavior. |

## Proposed Target State

1. The simulation runtime resolves the finest available engineer motion artifact for the current workflow and treats it as the live `payload_trajectory_monitor`.
2. The monitor checks the realized payload reference point against the next expected anchor at `monitor_sample_stride_s`, not as a full per-timestep replay of the physics engine.
3. The monitor fails closed after `consecutive_miss_count` exceeds a configurable threshold and stops simulation immediately with a dedicated `PAYLOAD_TRAJECTORY_CONTRACT_VIOLATION` failure reason.
4. The monitor also fails closed when the remaining required first-contact order or terminal goal-zone proof (`goal_zone_entry`, `goal_zone_contact`, or `terminal_event`) is no longer reachable from the current state.
5. The stop payload records `last_checked_anchor_index`, `last_checked_anchor_t_s`, the observed deviation, `consecutive_miss_count`, and the configured threshold values so the failure is reproducible.
6. Static validation remains separate. This migration does not replace `validate_payload_trajectory_definition_yaml()` or the swept-clearance proof.
7. Benchmark-owned motion remains untouched.

## Required Work

### Contract plumbing

- [x] Add a dedicated runtime monitor policy to `config/agents_config.yaml`.
- [x] Keep the policy fail-closed and explicit about `monitor_sample_stride_s`, anchor tolerances, and `consecutive_miss_count`.
- [x] Update `specs/architecture/simulation-and-rendering.md` so the `payload_trajectory_monitor` is a runtime contract, not a vague implementation note.

### Runtime enforcement

- [x] Extend `FailureReason` with a dedicated `PAYLOAD_TRAJECTORY_CONTRACT_VIOLATION` failure mode or an equivalent explicit runtime stop reason.
- [x] Thread `payload_trajectory_monitor` through `worker_heavy/simulation/loop.py` and a dedicated helper module owned by the simulation runtime.
- [x] Update `shared/models/simulation.py` and `shared/observability/schemas.py` so the stop payload includes `last_checked_anchor_index`, `last_checked_anchor_t_s`, observed deviation, and threshold values.
- [x] Keep the monitor deterministic and fail closed when payload path metadata is missing, ambiguous, or inconsistent with the approved trajectory artifacts.

### Validation boundary

- [x] Keep `worker_heavy/utils/file_validation.py` and `worker_heavy/utils/payload_trajectory_validation.py` as static proof layers.
- [x] Consume their output from `payload_trajectory_monitor` instead of creating a separate, conflicting contract.
- [x] Do not use the render overlay path as the monitor source of truth; `render_cad(..., payload_path=True)` remains review context only.

### Documentation

- [x] Update `specs/architecture/agents/agent-artifacts/payload_trajectory_definition_yaml_acceptance_criteria.md` so the file-level contract explicitly includes runtime fail-fast behavior.
- [x] Update `specs/architecture/agents/tools.md` so the engineering coder gate clearly distinguishes static trajectory validation from runtime monitor enforcement.
- [x] Update the relevant engineer role skills so planner and coder guidance do not imply that static validation alone proves runtime compliance.

### Tests and fixtures

- [x] Add or update regressions around anchor drift, required first-contact order impossibility, and successful monitor-compliant execution.
- [x] Refresh any seeded fixtures or mock responses that assume the simulation only stops on generic goal, forbid, or out-of-bounds conditions.
- [x] Extend the integration catalog entry that describes simulation failure taxonomy.

## Non-Goals

- Do not turn the monitor into a full per-timestep physics replay.
- Do not change benchmark-owned motion behavior.
- Do not relax the static swept-clearance validator.
- Do not require the payload to dwell in the goal zone after contact unless the benchmark objective explicitly says so.
- Do not treat the preview overlay as execution evidence.

## Sequencing

1. Define the runtime failure reason and metadata payload first.
2. Add the `payload_trajectory_monitor` policy to `config/agents_config.yaml`.
3. Thread the monitor through the simulation loop and any helper module it needs.
4. Update observability and simulation-result schemas to carry the stop context.
5. Refresh the architecture docs and role skills.
6. Add the integration regressions and refresh seeded examples last.

## Acceptance Criteria

1. A simulation run that drifts outside the approved payload trajectory or misses the next anchor beyond the configured threshold terminates early and does not continue to the simulation time cap.
2. The termination payload includes `last_checked_anchor_index`, `last_checked_anchor_t_s`, the observed deviation, `consecutive_miss_count`, and the configured threshold values.
3. A run that remains anchor-compliant until terminal `goal_zone_entry` / `goal_zone_contact` still succeeds and is not penalized by the monitor.
4. Missing or ambiguous payload trajectory metadata fails closed rather than silently disabling the monitor.
5. The failure mode is visible in the simulation result and observability payloads, and the docs describe the same behavior.

## Test Impact

- `INT-020` needs a trajectory-specific failure taxonomy update if the new runtime stop reason is surfaced there.
- `tests/integration/architecture_p1/test_engineering_loop.py` needs a run that fails fast on anchor drift.
- `tests/integration/architecture_p1/test_episode_replay.py` needs a replayable failure payload for the new monitor reason.
- `tests/integration/architecture_p1/test_handover.py` and `tests/integration/architecture_p1/test_reviewer_evidence.py` need to keep the latest-revision simulation evidence aligned with the new stop reason.

## Migration Checklist

### Contract

- [x] Add the runtime monitor policy to `config/agents_config.yaml`.
- [x] Add a dedicated payload-trajectory contract violation reason to the shared failure enums.
- [x] Extend the simulation result metadata with `last_checked_anchor_index`, `last_checked_anchor_t_s`, and deviation context.

### Runtime

- [x] Thread `payload_trajectory_monitor` through `worker_heavy/simulation/loop.py` or a dedicated helper module.
- [x] Make the runtime consume the approved payload trajectory artifacts and stop fail-closed on ambiguity.
- [x] Keep the monitor separate from the static validation path.

### Docs

- [x] Update `specs/architecture/simulation-and-rendering.md` with concrete runtime fail-fast semantics.
- [x] Update `specs/architecture/agents/agent-artifacts/payload_trajectory_definition_yaml_acceptance_criteria.md`.
- [x] Update `specs/architecture/agents/tools.md` and the relevant engineer role skills so the contract is not described as validation-only.

### Tests

- [x] Add an anchor-drift regression that terminates early.
- [x] Add a successful monitor-compliant regression.
- [x] Update integration catalog entries and seeded examples that encode the old generic-only stop behavior.

## File-Level Change Set

- `worker_heavy/simulation/loop.py`
- `worker_heavy/simulation/payload_trajectory_monitor.py`
- `controller/observability/middleware_helper.py`
- `shared/enums.py`
- `shared/agents/config.py`
- `shared/models/simulation.py`
- `shared/observability/schemas.py`
- `config/agents_config.yaml`
- `specs/architecture/simulation-and-rendering.md`
- `specs/architecture/agents/tools.md`
- `specs/architecture/agents/agent-artifacts/payload_trajectory_definition_yaml_acceptance_criteria.md`
- `.agents/skills/engineer-planner/SKILL.md`
- `.agents/skills/engineer-coder/SKILL.md`
- `.agents/skills/engineer-plan-reviewer/SKILL.md`
- `.agents/skills/engineer-execution-reviewer/SKILL.md`
- `tests/integration/architecture_p0/test_architecture_p0.py`
- `tests/integration/architecture_p1/test_engineering_loop.py`
- `tests/integration/architecture_p1/test_episode_replay.py`
- `tests/integration/architecture_p1/test_handover.py`
- `tests/integration/architecture_p1/test_reviewer_evidence.py`
- `specs/integration-test-list.md`
