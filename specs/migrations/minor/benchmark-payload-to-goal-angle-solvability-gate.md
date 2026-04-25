---
title: Benchmark Payload-to-Goal Angle Solvability Gate
status: implemented
agents_affected:
  - benchmark_planner
  - benchmark_plan_reviewer
  - benchmark_coder
  - benchmark_reviewer
added_at: '2026-04-23T00:00:00Z'
---

# Benchmark Payload-to-Goal Angle Solvability Gate

<!-- Migration doc. The rule is implemented in code and specs; keep this file as the migration record. -->

## Purpose

This migration records the benchmark-side static solvability check added to
the YAML validation path. The benchmark generator should not be allowed to
publish a task instance that is formally well-formed but effectively
impossible to drive with the gravity-only mechanism the repo currently relies
on.

This work composes with the existing benchmark simulation/review contract and
the engineer-side motion-forecast migration. Those documents already define
benchmark stability, benchmark motion evidence, and the engineer payload-path
proof; this migration only adds the missing static solvability precondition for
the benchmark definition itself.

The target contract is:

1. benchmark solvability is validated from `benchmark_definition.yaml`,
2. the rule is config-driven from `config/agents_config.yaml`,
3. the payload start position must have at least a minimum downhill slope
   toward the bottom center of the goal objective,
4. the threshold is fail-closed and easy to audit, and
5. the benchmark planner, benchmark coder, and benchmark reviewer all see the
   same rejection reason before handoff or node entry continues.

Follow-on correction:

- benchmark objective zones are interpreted as millimeters and must fail
  closed when any declared goal/build/forbid zone spans less than 3 mm on its
  largest axis,
- the validator must not auto-scale tiny coordinates as a unit guess, and
- the 3 mm floor is a heuristic guard against forgotten units, not a
  manufacturing tolerance rule.

This is intentionally a benchmark-definition gate, not a CAD-geometry gate.
`validate_benchmark()` on authored `Compound` geometry should stay focused on
the benchmark assembly itself. The new rule belongs in the YAML validation
chain that already reads `benchmark_definition.yaml`, because that is the
surface that owns task solvability and benchmark objective placement.

## Problem Statement

The current benchmark-definition validator already enforces the obvious static
contracts:

1. goal, build, and forbid boxes are internally consistent,
2. the payload has a declared spawn position,
3. runtime jitter stays inside the build zone,
4. the spawned payload does not overlap benchmark-owned fixtures at start, and
5. the benchmark stays inside the broader simulation bounds.

What it does not yet enforce is a slope-based solvability precondition. A
benchmark can be structurally valid while still placing the payload so flatly
relative to the goal zone that the only available mechanism, gravity, cannot
reasonably move it forward. The generator may still hand such a benchmark off,
and the downstream roles would then be forced to discover the unsolvability
after the fact.

This migration records the missing check so the repo can add it without
guessing at the scope later.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `worker_heavy/utils/validation.py::_validate_benchmark_definition_consistency` | Enforces zone overlap, spawn containment, runtime envelope bounds, and other AABB-based consistency rules. | It does not yet measure whether the spawn-to-goal geometry gives gravity enough slope to be plausibly solvable. |
| `worker_heavy/utils/file_validation.py::validate_benchmark_definition_yaml` | Parses `benchmark_definition.yaml` and forwards the structural consistency result. | The new solvability gate needs to live in this path so every caller inherits it. |
| `shared/agents/config.py` and `config/agents_config.yaml` | Already carry benchmark policy knobs such as render policy, payload observation window, and trajectory budgets. | They do not yet expose a benchmark-specific minimum-angle policy for solvability. |
| `controller/agent/benchmark_handover_validation.py` | Re-validates benchmark definition semantics before planner handoff approval. | The new failure must surface here automatically once the shared validator has it. |
| `controller/agent/node_entry_validation.py` | Replays benchmark YAML validation during seeded preflight. | Seeded evals need the same solvability rejection before node execution starts. |
| `specs/architecture/agents/handover-contracts.md` | Describes the benchmark planner handoff package and the benchmark-owned `benchmark_definition.yaml` contract. | The handover contract needs the new solvability rule so the planner-facing narrative matches validation. |
| `specs/architecture/agents/agent-artifacts/benchmark_definition_yaml_acceptance_criteria.md` | Describes geometry validity, randomization, and benchmark-contract fidelity, but not a slope-based solvability rule. | The file-level contract needs to say that gravity-only solvability is part of benchmark validity. |
| `specs/architecture/agents/roles-detailed/benchmark-planner.md` and `benchmark-coder.md` | Tell the benchmark team to produce valid benchmark geometry and preserve it exactly. | The role guidance needs to teach the solvability threshold so the benchmark side does not author flat, unsolvable instances. |
| `specs/architecture/agents/definitions-of-success-and-failure.md` and `specs/architecture/evals-architecture.md` | Describe payload motion, spawn overlap, and runtime failure conditions, but not the benchmark-side angle threshold. | The architecture needs a canonical reference for the bottom-center angle rule so the calculation is not left to interpretation. |

## Proposed Target State

1. `benchmark_definition.yaml` validation rejects any benchmark whose payload
   start position is too shallow relative to the goal objective's bottom
   center.
2. The angle is computed from the payload spawn position to the bottom center
   of the goal zone, using a single documented geometric projection rather
   than ad hoc per-caller logic.
3. The default implementation should treat the angle as the downhill slope
   from the payload spawn toward the goal bottom center. A benchmark passes
   only when that angle is greater than or equal to the configured threshold.
4. The threshold value comes from `config/agents_config.yaml`; the validator
   must not hardcode `25deg`.
5. Missing, malformed, or contradictory angle-policy config fails closed
   rather than silently disabling the solvability gate.
6. The rejection propagates through `validate_benchmark_definition_yaml()`,
   benchmark planner handoff validation, and seeded node-entry validation
   without each caller re-implementing the angle math.
7. The benchmark planner and benchmark coder skills/documents describe the
   rule as a solvability precondition, not as a review-side guess.
8. The benchmark-side `validate_benchmark()` CAD gate remains separate from
   this YAML solvability check.

## Required Work

### 1. Define the policy surface

- Add a benchmark solvability policy to `shared/agents/config.py`.
- Add the corresponding `config/agents_config.yaml` entry with the minimum
  angle threshold.
- Decide the canonical policy name once and use the same name in docs,
  config, and validation code.

### 2. Add the YAML solvability check

- Extend the benchmark-definition validation helper in
  `worker_heavy/utils/validation.py` so it computes the angle from
  `payload.start_position_mm` to the bottom center of
  `objectives.goal_zone_mm`.
- Fail closed when the computed angle is below the configured threshold.
- Keep the check in the benchmark YAML validation chain so
  `validate_benchmark_definition_yaml()`, controller handoff validation, and
  node-entry preflight all inherit it automatically.
- Keep the existing AABB and runtime-envelope checks intact.

### 3. Refresh benchmark-facing docs and guidance

- Update `specs/architecture/agents/agent-artifacts/benchmark_definition_yaml_acceptance_criteria.md`
  so the file-level contract explicitly includes the solvability angle gate.
- Update the benchmark planner and benchmark coder role docs so the new rule
  is visible to the generator side before handoff.
- Update the relevant benchmark skills in `.agents/skills/benchmark-planner/`
  and `.agents/skills/benchmark-coder/` so they teach the same threshold and
  failure behavior.
- Add a short architecture note in the success/failure docs so the angle
  calculation is not left implicit.

### 4. Add regression coverage

- Add a benchmark-definition regression that fails when the start-to-goal
  angle is below the threshold.
- Add a boundary regression that confirms the exact threshold value is
  accepted when all other geometry checks pass.
- Add a node-entry or handoff regression that proves the shared validation
  chain surfaces the same failure without custom per-caller logic.

## Best-Guess Answers

- Use a dedicated top-level benchmark policy section named
  `benchmark_solvability`. Keep it separate from the generic payload
  observation and trajectory policy blocks so the new rule is easy to find and
  does not get conflated with runtime monitoring.
- Measure the angle as the downhill slope from the payload spawn position to
  the goal zone bottom center, i.e. `atan2(payload_spawn_z - goal_bottom_z, horizontal_distance)`. That is the simplest geometry definition and matches
  the plain-English rule in the request.
- Treat the goal zone bottom center as the canonical target point for the
  first implementation. An explicit objective anchor can be added later if the
  geometry contract ever needs a richer target representation.
- Do not block implementation on the coordinate-frame comment in
  `specs/architecture/evals-architecture.md`. The solvability gate can rely on
  the existing world-frame benchmark coordinates and the derived goal-bottom-
  center calculation, while the spec comment is cleaned up as a follow-on
  documentation fix.

## Non-Goals

- Do not change `validate_benchmark()` on authored CAD compounds to become a
  YAML solvability validator.
- Do not change the benchmark payload observation window or benchmark-side
  simulation stability semantics.
- Do not add a runtime trajectory monitor or a per-timestep replay loop.
- Do not hardcode the threshold in the validator.
- Do not relax the existing AABB, spawn-overlap, or runtime-envelope checks.

## Sequencing

The safe order is:

1. Decide the policy name and canonical angle formula.
2. Add the policy model and config entry.
3. Wire the solvability helper into the benchmark YAML validation path.
4. Update the benchmark-facing docs and role guidance.
5. Add the integration regressions and threshold-boundary coverage.

## Acceptance Criteria

1. Benchmark YAML validation fails closed when the payload spawn-to-goal angle
   is below the configured minimum.
2. The minimum angle is configurable from `config/agents_config.yaml`.
3. The same failure is visible in planner handoff validation and seeded
   node-entry validation because they reuse the shared benchmark-definition
   gate.
4. Benchmark planner and coder guidance describe the same solvability rule as
   the runtime validator.
5. The implementation remains fail-closed for missing config, malformed
   geometry, or ambiguous angle inputs.

## File-Level Change Set

The implementation should touch the smallest realistic set of files that
enforce the new contract:

- `shared/agents/config.py`
- `config/agents_config.yaml`
- `worker_heavy/utils/validation.py`
- `worker_heavy/utils/file_validation.py`
- `controller/agent/benchmark_handover_validation.py`
- `controller/agent/node_entry_validation.py`
- `specs/architecture/agents/agent-artifacts/benchmark_definition_yaml_acceptance_criteria.md`
- `specs/architecture/agents/roles-detailed/benchmark-planner.md`
- `specs/architecture/agents/roles-detailed/benchmark-coder.md`
- `specs/architecture/agents/definitions-of-success-and-failure.md`
- `specs/architecture/evals-architecture.md`
- `specs/architecture/agents/handover-contracts.md`
- `.agents/skills/benchmark-planner/SKILL.md`
- `.agents/skills/benchmark-coder/SKILL.md`
- `tests/integration/architecture_p0/test_int_008_objectives_validation.py`
- `tests/integration/architecture_p0/test_node_entry_validation.py`
- `tests/integration/architecture_p0/test_planner_gates.py`

## Notes

This rule is intentionally small enough to implement as a bounded follow-up
after the benchmark validation plumbing is settled. The important part is to
lock down the geometry definition and the config surface before any code
lands, so the threshold does not get hardcoded into a one-off validator path.
