---
title: Seeded Eval Validation Scope Contract
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
added_at: '2026-04-15T14:23:40Z'
---

# Seeded Eval Validation Scope Contract

<!-- Migration spec. Should be already implemented. -->

## Purpose

This migration defines an explicit validation-depth handle for
`scripts/validate_eval_seed.py` and the shared preflight helpers it calls.

The goal is to let seed validation choose between:

1. current-node entry validation only,
2. current-node validation plus all predecessor gate checks required by the
   chain, and
3. the same as (2) plus the heavy simulation gates that downstream nodes rely
   on.

The standard seed-validation behavior is option 2. That makes the maintainer
tool strict by default without forcing the normal eval runtime to pay for the
same depth unless a caller opts in.

This is a contract migration, not a new validation algorithm. The system
already has the underlying benchmark and engineering gates:

- `validate_benchmark()`
- `validate_engineering()`
- `simulate_benchmark()`
- `simulate_engineering()`
- `submit_benchmark_plan()`
- `submit_engineering_plan()`
- `submit_benchmark_for_review()`
- `submit_solution_for_review()`

The missing piece is an explicit scope handle that decides which of those
existing gates are replayed during seeded preflight.

## Problem Statement

`scripts/validate_eval_seed.py` currently runs one fixed preflight path. That
path validates the current node contract and seeded handoff artifacts, but it
does not let the caller ask for the deeper predecessor gate chain.

That is too weak for real seed validation.

The current failure mode is visible on benchmark-backed engineer seeds:

1. a seeded engineer-coder row can pass the current validator,
2. the carried benchmark script can still fail the real
   `validate_benchmark()` geometry gate, and
3. the seed validator never exercised that gate because it did not know to
   replay the predecessor contract chain.

The same issue exists for planner submission gates. A planner seed is not
really valid if it only has the files on disk. It must also satisfy the same
terminal contract that `submit_benchmark_plan()` or
`submit_engineering_plan()` enforces.

The current implementation also exposes only immediate predecessor maps. That
is not enough for the seed validator because the seed validator needs to know
which terminal gate is reused by downstream nodes, not just which node came
immediately before the current node.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `scripts/validate_eval_seed.py` | Seeds a workspace and then calls one fixed `_preflight_seeded_entry_contract(...)` path. | The CLI cannot choose a validation depth, so it cannot distinguish smoke-only checks from deeper contract replay. |
| `evals/logic/workspace.py` | Owns `preflight_seeded_entry_contract(...)`, but the helper has no explicit validation-scope parameter. | The shared seam needs a scope handle so the caller can select current-node, predecessor, or heavy-simulation behavior. |
| `controller/agent/node_entry_validation.py` | Defines current-node contracts and immediate predecessor maps. | The seed validator needs a chain-aware contract resolver, not only a one-step map. |
| `controller/agent/benchmark_handover_validation.py` | Already knows how to validate benchmark planner handoff semantics. | Scope 2 and 3 should reuse this logic instead of duplicating benchmark-specific checks in the CLI. |
| `controller/agent/review_handover.py` | Already knows how to validate reviewer handoff, planner submission, and simulation evidence. | Scope 2 and 3 should reuse this logic for planner and reviewer chains instead of inventing a new validation path. |
| `evals/logic/runner.py` and `evals/logic/runner_execution.py` | Call the same shared preflight helper during eval startup. | They must stay on the narrow runtime path unless a caller explicitly opts into deeper seed-style validation. |
| `specs/devtools.md` | Describes seed validation as a seeded-entry contract check without a scope handle. | The developer docs must describe the new depth option and its default. |
| `specs/architecture/evals-architecture.md` | Describes eval validation as fail-closed, but not as a depth-selectable seed contract. | The architecture docs must record the seed-validation depth contract so the behavior is not implicit. |

## Validation Scope Contract

The new handle is a closed enum, not a freeform string and not a boolean.
Unknown values must fail closed.

| Scope | Required behavior | Concrete examples |
| -- | -- | -- |
| `current-node` | Validate only the current node's own entry contract and same-node seeded handoff checks. Do not replay predecessor terminal gates. Do not run heavy simulation for ancestor nodes. | A `benchmark_coder` row is checked only as the current node. A lightweight smoke validation can use this mode. |
| `current-and-previous-nodes` | Validate the current node and all predecessor gate checks required by the chain. This includes the actual terminal gate that downstream roles depend on, not just artifact existence. This is the standard seed-validation mode. | `benchmark_coder` descendants must prove the carried benchmark output passes `validate_benchmark()`. Planner rows must prove the relevant planner submission contract (`submit_benchmark_plan()` or `submit_engineering_plan()`). |
| `current-and-previous-nodes-with-heavy-simulation` | Do everything in `current-and-previous-nodes`, then also replay the heavy simulation gate(s) required by the predecessor chain. This is the most expensive mode and should stay opt-in. | `engineer_execution_reviewer` must be able to force the engineer-coder chain through `simulate_engineering()`. Benchmark review paths can also require `simulate_benchmark()` when the chain depends on simulation evidence. |

The scope contract is chain-driven. It must not depend only on the immediate
`PREVIOUS_NODE_MAPS` lookup, because that is too shallow for the benchmark ->
reviewer -> engineering reuse chain.

## Target State

1. `scripts/validate_eval_seed.py` accepts an explicit `--validation-scope`
   handle with the three values above.
2. `current-and-previous-nodes` is the default mode for seed validation.
3. `preflight_seeded_entry_contract(...)` threads the scope into the shared
   seeded-workspace validation logic instead of hard-coding one path.
4. The shared validation path replays the same terminal gates the runtime
   depends on:
   - benchmark coder rows reuse `validate_benchmark()`
   - engineer coder rows reuse `validate_engineering()`
   - planner rows reuse the relevant planner submission contract
   - reviewer rows reuse the relevant review handoff and simulation evidence
     checks
5. `current-and-previous-nodes-with-heavy-simulation` replays the heavy simulation gates
   required by the chain, not just the structural entry checks.
6. The shared preflight helper keeps the current-node default for backward
   compatibility, and the normal eval runtime keeps its narrow behavior unless
   a caller explicitly opts into a deeper scope.
7. The docs and integration coverage describe the scope contract in the same
   terms as the implementation.

## Required Work

### 1. Add a closed validation-scope handle

- Add a `validation_scope` enum for seeded preflight.
- Expose it on `scripts/validate_eval_seed.py` as `--validation-scope`.
- Make unknown values fail closed with a clear argument error.
- Keep the handle explicit. Do not infer scope from agent name, task id, or
  seed contents.

### 2. Thread the scope through the shared preflight seam

- Extend `evals/logic/workspace.py::preflight_seeded_entry_contract(...)` so it
  accepts the new scope handle.
- Keep the current-node entry contract as the base layer.
- Layer predecessor checks on top of that base layer only when the selected
  scope asks for them.
- Keep the shared helper default at `current-node` so existing runtime callers
  stay narrow unless they pass a broader scope explicitly.

### 3. Replay the real predecessor gates

- For benchmark-side descendants, replay the benchmark validation chain
  instead of only checking that the benchmark script exists.
- For engineering-side descendants, replay the engineering validation chain
  instead of only checking that the solution script exists.
- For planner rows, validate the same terminal contract that
  `submit_benchmark_plan()` or `submit_engineering_plan()` enforces.
- For reviewer rows, validate the same handoff and evidence contract that the
  reviewer would rely on before approval.

### 4. Add the heavy-simulation depth

- Scope 3 must trigger the heavy simulation gate wherever the predecessor
  chain already depends on it.
- Benchmark review paths must be able to force benchmark simulation replay.
- Engineering review paths must be able to force engineering simulation
  replay.
- Do not make scope 3 the default. It is a high-cost validation mode.

### 5. Keep the chain contract reusable

- Encode the scope-aware chain in the shared validation layer, not as a one-
  off CLI hack.
- Reuse the existing benchmark and review handover helpers where possible.
- Keep the implementation fail-closed. If a terminal gate cannot be replayed,
  the seed must fail instead of silently falling back to a weaker check.

### 6. Refresh docs and regression coverage

- Update `specs/devtools.md` so the seed validator documents the new scope
  handle and its default.
- Update `specs/architecture/evals-architecture.md` so the seed contract is
  described as depth-selectable and fail-closed.
- Add regression coverage for the known false-negative case where a seeded
  engineer-coder row passes the current validator but the carried benchmark
  script fails `validate_benchmark()`.
- Add a regression that proves the default mode is `current-and-previous-nodes`, not
  `current-node`.
- Add a regression that proves scope 3 actually exercises the heavy-simulation
  gate.

## Non-Goals

- Do not change the benchmark or engineering runtime tool names.
- Do not change the current role manifest contract.
- Do not change the evaluation data model or seeded row schema.
- Do not broaden the normal eval runtime preflight by default.
- Do not rewrite the benchmark or engineering validation logic itself.
- Do not introduce a boolean flag that can only express yes/no depth choices.

## Sequencing

The safe order is:

1. Add the closed validation-scope enum and CLI flag.
2. Thread the scope into the shared seeded preflight helper.
3. Teach the shared validation layer how to replay predecessor terminal gates.
4. Add the heavy-simulation scope on top of the predecessor replay path.
5. Update docs and integration tests.
6. Verify the known false-negative seed now fails in the stricter mode while
   the current-node smoke mode still works.

## Acceptance Criteria

1. `scripts/validate_eval_seed.py` accepts `--validation-scope` and rejects
   unknown values.
2. The default seed-validation mode is `current-and-previous-nodes`.
3. A seed that is only structurally valid but fails the real predecessor
   terminal gate is rejected under the default mode.
4. The benchmark-coder false negative is closed: the carried benchmark script
   must fail the stricter mode when `validate_benchmark()` fails.
5. Planner rows are rejected if their terminal submission contract is invalid.
6. Scope 3 fails when the required heavy simulation gate fails or cannot be
   replayed.
7. The normal eval runner path keeps its current behavior unless explicitly
   pointed at a deeper scope.
8. The docs and regression tests describe the same three scopes that the code
   implements.

## File-Level Change Set

The implementation should touch the smallest set of files that actually
enforce the new contract:

| File | Change |
| -- | -- |
| `scripts/validate_eval_seed.py` | Add the CLI handle, default it to `current-and-previous-nodes`, and pass it into the shared preflight helper. |
| `evals/logic/workspace.py` | Thread the scope through `preflight_seeded_entry_contract(...)` and the seeded supplemental validation layer. |
| `controller/agent/node_entry_validation.py` | Add the scope-aware chain resolver and any shared predecessor-gate helpers needed by the seeded preflight path. |
| `controller/agent/benchmark_handover_validation.py` | Reuse benchmark validation and benchmark-planner handoff checks as scope-aware predecessor gates. |
| `controller/agent/review_handover.py` | Reuse planner submission, reviewer handoff, and simulation-evidence checks as scope-aware predecessor gates. |
| `specs/devtools.md` | Document the new seed-validation handle and its default. |
| `specs/architecture/evals-architecture.md` | Record the depth-selectable seed contract and fail-closed semantics. |
| `tests/integration/architecture_p0/test_codex_runner_mode.py` | Add or extend the seed-validator regressions, including the known false-negative case and scope-default assertions. |

## Risks

1. If the implementation only checks the immediate predecessor map, the known
   benchmark-coder false negative will stay hidden.
2. If scope 3 is made implicit instead of opt-in, the seed validator will
   become unnecessarily expensive.
3. If the scope is threaded through the CLI but not the shared preflight
   helper, the runner and the seed validator will drift.
4. If the new path falls back to a weaker validation when a terminal gate is
   unavailable, the contract will no longer be fail-closed.

## Implementation Checklist

### Contract plumbing

- [ ] Add a closed `validation_scope` enum with `current-node`,
  `current-and-previous-nodes`, and
  `current-and-previous-nodes-with-heavy-simulation`.
- [ ] Add `--validation-scope` to `scripts/validate_eval_seed.py`.
- [ ] Default `--validation-scope` to `current-and-previous-nodes` in the
  seed validator.
- [ ] Keep unknown scope values fail-closed.
- [ ] Keep prompt-only rows bypassed exactly as they are today.

### Shared preflight seam

- [ ] Thread `validation_scope` through
  `evals/logic/workspace.py::preflight_seeded_entry_contract(...)`.
- [ ] Keep the current-node entry contract as the base layer.
- [ ] Keep the base layer composed of `evaluate_node_entry_contract(...)` and
  `validate_seeded_workspace_handoff_artifacts(...)`.
- [ ] Make `current-node` stop after the base layer.
- [ ] Make `current-and-previous-nodes` add predecessor-gate replay on top of
  the base layer.
- [ ] Make `current-and-previous-nodes-with-heavy-simulation` add
  heavy-simulation replay on top of `current-and-previous-nodes`.
- [ ] Keep `evals/logic/runner.py` and `evals/logic/runner_execution.py` on
  `current-node` behavior unless explicitly passed a deeper scope.

### Predecessor-gate replay

- [ ] Add a chain-aware predecessor helper in
  `controller/agent/node_entry_validation.py`.
- [ ] Stop relying only on the one-step `PREVIOUS_NODE_MAPS` lookup for the
  seed validator.
- [ ] Reuse the benchmark planner and benchmark coder gate helpers for
  benchmark-side descendants.
- [ ] Reuse the planner submission and review handoff helpers for planner and
  reviewer descendants.
- [ ] Reuse the engineering validation and simulation helpers for
  engineering-side descendants.
- [ ] Reuse existing helpers from
  `controller/agent/benchmark_handover_validation.py` and
  `controller/agent/review_handover.py` instead of copying gate logic into
  the CLI.

### Heavy simulation replay

- [ ] Make scope 3 trigger `simulate_benchmark()` where benchmark-chain
  validation depends on simulation evidence.
- [ ] Make scope 3 trigger `simulate_engineering()` where engineer-chain
  validation depends on simulation evidence.
- [ ] Keep scope 3 opt-in and do not make it the seed-validator default.
- [ ] Fail closed if the requested simulation gate cannot be replayed.

### Regression coverage

- [ ] Add the `ec-002` false-negative regression where the current validator
  passes but `validate_benchmark()` fails.
- [ ] Add a regression proving `current-and-previous-nodes` is the default
  seed-validation mode.
- [ ] Add a regression proving `current-node` remains available as the smoke
  mode.
- [ ] Add a regression proving
  `current-and-previous-nodes-with-heavy-simulation` reaches the heavy
  simulation gate.
- [ ] Add a regression proving invalid `--validation-scope` values are
  rejected.

### Docs and rollout

- [ ] Update `specs/devtools.md` with the three scopes and the seed-validator
  default.
- [ ] Update `specs/architecture/evals-architecture.md` with the depth-
  selectable, fail-closed seed contract.
- [ ] Verify the new strict path with the narrowest integration slice first.
- [ ] Widen verification only if a regression points at another layer.
- [ ] Keep the normal eval runtime narrow unless a caller explicitly opts in
  to a deeper scope.
