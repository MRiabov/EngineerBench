---
title: Planner Motion Forecast Build and Goal Anchor Contract
status: investigation
agents_affected:
  - benchmark_planner
  - engineer_planner
  - engineer_coder
added_at: '2026-04-03T15:11:03Z'
---

# Planner Motion Forecast Build and Goal Anchor Contract

<!-- Investigation doc. No behavior change yet. -->

## Purpose

This migration tightens the engineer-side motion forecast contract described in
[Simulation and Rendering](../../architecture/simulation-and-rendering.md)
and the handoff gates that consume it.

The target contract is that a planner-authored `motion_forecast` is not just a
sparse path sketch with tolerance bands. It must also make the endpoints
reviewable:

1. the first anchor must be build-zone valid for the moving engineer-owned
   solution, and
2. the terminal anchor must explicitly prove goal-zone entry or contact, either
   in the terminal anchor itself or in an equivalent structured terminal event.

This migration applies to engineer-owned moving parts, and every engineering
handoff includes them. Benchmark-owned fixtures continue to use the benchmark motion contract in
`benchmark_definition.yaml` and `benchmark_assembly_definition.yaml`.

The contact-probe boundary for this work is the existing
`shared/simulation/backends.py` `PhysicsBackend` protocol. Genesis and MuJoCo
already hang off that shared seam, so the migration should prove backend
contact behavior first instead of inventing a new abstraction path from scratch.

This is a low-confidence decision by design: if the planner cannot express the
collision/contact setup cleanly enough, the downstream engineer-coder may need
to refuse the plan rather than guess at the missing contact semantics. The
reviewer is a fallback validation layer, not a substitute for a precise
planner-facing contract.

The precise payload trajectory must live in the engineer-coder path, not in
the planner-owned forecast. The planner sets the coarse, reviewable intent; the
engineer-coder expands that into backend-specific payload trajectory/contact
evidence and initial pose/orientation details. The hard consistency gate stays
at `validate()`: if the engineer has deviated too far from the approved plan,
the episode should stop there rather than trying to paper over the mismatch
later in review.

In concrete terms, the planner forecast should stay coarse: fewer anchors,
slower waypoint cadence, and wider tolerance bands. The engineer-owned path
lives in a separate `payload_trajectory_definition.yaml` artifact for the
backend-specific, higher-resolution path and contact proof.

Cadence and tolerance policy for the planner and coder layers is config-driven
in `config/agents_config.yaml`; the artifact files carry the contract shape,
while config sets the frequency and tolerance budgets. The benchmark planner
is the outermost coarse layer for benchmark-owned moving fixtures and defines
the course at the loosest cadence/tolerance envelope permitted by policy,
potentially on the order of multi-second waypoints when appropriate. The
engineer planner sits one layer finer than that, and the engineer coder refines
the final backend-specific path in `payload_trajectory_definition.yaml`.

## Problem Statement

The current motion forecast contract already requires ordered anchors, world
coordinates, tolerance bands, and first-contact ordering. That is necessary,
but it is still incomplete for review.

Without explicit endpoint assertions:

1. the reviewer can infer the start and finish conditions only from prose or
   from later simulation success,
2. a forecast can look structurally valid even when it never states that the
   mechanism begins in a build-safe state, and
3. a forecast can look structurally valid even when the terminal goal-zone hit
   is only implied by the narrative rather than recorded in the structured
   contract.

That weakens fail-closed review because a moving solution can appear complete
while still leaving the start or end conditions ambiguous.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `specs/architecture/simulation-and-rendering.md` | Defines sparse, ordered motion forecasts with tolerance bands and contact order, but does not explicitly require the first anchor to be build-safe or the terminal anchor to assert goal-zone contact. | The architecture target needs explicit endpoint semantics so the reviewer does not infer them from prose. |
| `specs/architecture/agents/handover-contracts.md` | Requires a reviewable `motion_forecast` for moving engineer-owned parts. | The handoff contract must stay aligned with the new endpoint assertions. |
| `specs/architecture/agents/tools.md` | Planner submission already gates on the presence of a `motion_forecast`, but the wording stops at ordered anchors and first-contact order. | The planner gate needs to reject motion forecasts that omit explicit build/goal endpoint assertions. |
| `shared/models/schemas.py` | `AssemblyDefinition` has typed sections for drafting and totals, but no typed motion-forecast section yet. | The new endpoint contract should be schema-backed instead of living only in free-form YAML. |
| `shared/simulation/backends.py` and `worker_heavy/simulation/{genesis_backend.py,mujoco_backend.py}` | The shared `PhysicsBackend` protocol already exists, and both backends expose contact data through backend-specific implementations. | The migration needs to validate that a shared collision/contact seam is enough before any planner-facing contract is tightened. |
| `config/agents_config.yaml` | Currently owns execution, render, and visual-inspection policy, but not motion cadence/tolerance budgets. | The motion-layer frequency and tolerance knobs should be centralized there instead of hardcoded. |
| `shared/assets/template_repos/engineer/assembly_definition.yaml` | The starter engineer assembly template does not yet expose the required `motion_forecast` section. | Seeded workspaces need a visible template slot for the new contract. |
| `Engineer-coder` precise-path artifact (`payload_trajectory_definition.yaml`) | The starter engineer workspace does not yet teach the always-required precise path artifact explicitly. | The coarse planner forecast needs a distinct engineer-owned path file for higher-resolution payload trajectory proof. |
| `worker_heavy/utils/file_validation.py` | Validates `assembly_definition.yaml` and the planner cross-contract, but does not yet enforce endpoint assertions on the engineer motion forecast. | This is the main fail-closed validation seam for the contract. |
| `controller/agent/node_entry_validation.py` | Seeded preflight validates planner handoffs and review manifests. | Seeded entry must reject endpoint-ambiguous motion forecasts before node execution continues. |
| `controller/agent/review_handover.py` and `controller/agent/tools.py` | Route planner submission and reviewer entry through the existing handoff gates. | Their gate messaging and error propagation must reflect the new endpoint requirement. |
| `tests/integration/architecture_p0/test_planner_gates.py` | Covers planner gate behavior for current assembly contracts. | It needs a regression that proves the new motion endpoint assertion is enforced. |
| `tests/integration/architecture_p0/test_node_entry_validation.py` | Covers seeded node-entry preflight. | It needs a seeded rejection case for missing or contradictory endpoint assertions. |
| `tests/integration/architecture_p0/test_int_008_objectives_validation.py` | Covers build-zone and goal-zone objective semantics. | It is the right place to anchor the new endpoint assertions against the existing objective-zone rules. |
| `tests/integration/architecture_p1/test_engineering_loop.py` and `tests/integration/architecture_p1/test_script_tools_proxy.py` | Cover the live engineering submission and validation path. | They need coverage that proves the new contract survives the end-to-end planner/reviewer flow. |

## Proposed Target State

1. `motion_forecast` remains sparse and ordered, but the first anchor is
   explicitly build-zone valid for the moving engineer-owned solution.
2. The terminal anchor explicitly records goal-zone entry or contact, either
   as contact data on the final anchor or through an equivalent structured
   terminal event.
3. Reviewers and validators reject motion forecasts that force them to infer
   either endpoint from prose, from simulation success, or from a vague
   mechanism description.
4. The planner gate stays fail-closed: a moving engineer-owned solution cannot
   pass if the contract omits the build-safe start or the explicit goal-contact
   finish.
5. Benchmark fixtures remain governed by the benchmark motion contract and are
   not pulled into the engineer motion-forecast rules.
6. The benchmark planner remains the coarsest course-setting layer for
   benchmark-owned moving fixtures, with its own config-driven cadence and
   tolerance budget, so downstream engineering intake sees a course rather than
   a replay.
7. Static preview may optionally carry a motion-path overlay when
   `render_cad(..., payload_path=True)` is requested. The renderer selects the
   finest available motion artifact for the current workflow, and the overlay
   is display-only review context rather than validation evidence.

## Required Work

### 0. Prove the backend contact seam

- Create a syntax experiment under `scripts/experiments/syntax/collision-detection/`
  that probes Genesis and MuJoCo contact behavior through the shared
  `PhysicsBackend` boundary.
- Verify whether `get_contact_forces()`, `check_collision()`, or a small shared
  helper is enough to express "this body collided with anything else" in both
  engines.
- Verify how the experiment supplies the object's initial pose, including
  explicit rotation or quaternion, so the starting state is not silently left
  at the backend default orientation.
- Record the result before any planner validation change so the migration
  chooses the right shared contract instead of guessing from backend
  implementation details.

### 0a. Define the motion cadence/tolerance policy

- Add the motion cadence and tolerance policy knobs to `config/agents_config.yaml`
  for the benchmark planner, engineer planner, and engineer coder layers.
- Keep the motion contract itself in the YAML artifacts; use config only for the
  frequency and tolerance budgets.
- Treat the benchmark planner as the coarsest course-setting layer, the
  engineer planner as the intermediate coarse layer, and the engineer coder as
  the precise backend-specific layer.
- Make the benchmark planner envelope loose enough to set the course without
  pretending to be a full replay; think multi-second waypoint cadence when the
  benchmark motion contract allows it.

### 1. Define a typed motion-forecast schema

- Add a strict `MotionForecast` model, anchor model, and terminal contact/event
  model in `shared/models/schemas.py` or an equivalent schema module.
- Add `motion_forecast` to `AssemblyDefinition` as a typed section rather than a
  free-form YAML blob.
- Keep the schema strict so missing endpoint data, unknown fields, or malformed
  contact assertions fail closed.
- Keep `motion_forecast` intentionally coarse: fewer anchors, wider tolerance
  bands, and lower waypoint density than the engineer-owned precise path.

### 1b. Define the engineer-owned payload trajectory artifact

- Add the engineer-owned `payload_trajectory_definition.yaml` artifact for the
  backend-specific higher-resolution payload trajectory and contact proof.
- Treat this artifact as implementation-facing, not planner-facing: it should
  refine the coarse motion forecast rather than duplicate it.
- Make the payload trajectory the place where initial pose/orientation detail and
  contact sequencing are tightened beyond the planner forecast.

### 2. Seed the engineer template with the new contract

- Add a visible `motion_forecast` section to
  `shared/assets/template_repos/engineer/assembly_definition.yaml`.
- Keep the starter example sparse and readable.
- Show a build-safe first anchor and an explicit goal-contact terminal anchor
  so seeded workspaces teach the contract instead of hiding it.

### 3. Enforce endpoint assertions in planner validation

- Extend `worker_heavy/utils/file_validation.py` so the engineer planner handoff
  validator rejects moving solutions whose forecast does not prove a build-safe
  start and an explicit goal-contact finish.
- Keep the existing ordered-anchor and tolerance-band validation in place.
- Do not replace endpoint assertions with a softer prose-only reminder.

### 4. Fail closed in seeded preflight and reviewer routing

- Update `controller/agent/node_entry_validation.py` so seeded workspaces fail
  closed when the motion forecast is present but endpoint-ambiguous.
- Ensure reviewer gating and submission routing propagate the new failure
  reason clearly.
- Keep the benchmark-side motion contract untouched.

### 5. Update docs and examples

- Update the motion forecast contract text in
  `specs/architecture/simulation-and-rendering.md`.
- Update the preview helper contract so `payload_path=True` is documented as
  an optional static overlay that renders the finest available motion artifact
  for the current workflow.
- Align the handover and tool-gate wording in
  `specs/architecture/agents/handover-contracts.md` and
  `specs/architecture/agents/tools.md`.
- Add a concise example that shows the terminal goal-contact assertion in
  structured form.

### 6. Add regression coverage

- Add an engineering-planner regression that proves a forecast without a build
  safe start is rejected.
- Add a regression that proves a forecast without explicit goal-zone contact is
  rejected.
- Keep the existing build-zone and goal-zone objective tests as the semantic
  foundation for the new endpoint assertions.

## Non-Goals

- Do not turn the forecast into a full per-timestep replay of the physics
  engine.
- Do not change the 30 second simulation hard cap or any wall-clock timeout
  policy.
- Do not move the motion contract structure into `config/agents_config.yaml`;
  only cadence and tolerance policy may live there.
- Do not require the solution to dwell inside the goal zone after contact
  unless the benchmark objective explicitly says so.
- Do not alter the benchmark-side motion contract.

## Sequencing

The safe implementation order is:

1. Run the backend contact experiment and capture the initial-pose/orientation
   requirement.
2. Add the motion cadence/tolerance policy config entries.
3. Add the schema model and assembly-definition field.
4. Add the engineer-owned precise path artifact and the contract that refines
   the coarse forecast.
5. Seed the engineer starter template with the visible motion forecast section.
6. Wire the planner validation helper to enforce the endpoint assertions.
7. Update node-entry validation and reviewer routing to fail closed on the new
   error.
8. Add integration coverage and refresh any seeded workspace examples.
9. Update the architecture docs and the integration-test catalog to match the
   final contract wording.

## Acceptance Criteria

1. A moving engineer-owned planner handoff cannot pass validation unless the
   first motion anchor is build-zone valid.
2. A moving engineer-owned planner handoff cannot pass validation unless the
   terminal anchor or terminal event explicitly records goal-zone entry or
   contact.
3. Seeded node-entry preflight rejects the same missing-endpoint cases before
   node execution.
4. Reviewer routing and submission gates surface the same failure as a
   fail-closed contract error, not as a soft warning.
5. Benchmark motion validation continues to work under the benchmark-specific
   contract without inheriting the engineer endpoint rules.
6. The integration suite proves the new contract through live planner,
   reviewer, and seeded-preflight paths.

## Migration Checklist

### Contract

- [ ] Add typed motion-forecast models to the assembly schema.
- [ ] Add the `motion_forecast` field to `AssemblyDefinition`.
- [ ] Add the engineer-owned `payload_trajectory_definition.yaml` artifact as the
  higher-resolution path contract.
- [ ] Update the engineer starter assembly template with a visible forecast
  section and explicit endpoint assertions.
- [ ] Mark the coarse planner forecast as intentionally lower-frequency and
  looser than the precise path artifact.

### Validation

- [ ] Enforce build-safe first-anchor validation in the planner handoff
  validator.
- [ ] Enforce explicit goal-contact validation for the terminal anchor or
  terminal event.
- [ ] Validate that the engineer-owned precise path refines the coarse planner
  forecast without diverging too far.
- [ ] Propagate the new failure through planner submission and reviewer entry
  gates.

### Docs

- [ ] Update the motion forecast contract in the architecture docs.
- [ ] Align the handover/tool gate wording with the new endpoint requirement.

### Tests

- [ ] Add a planner-gate regression for missing build-safe start anchors.
- [ ] Add a planner-gate regression for missing goal-contact terminal
  assertions.
- [ ] Add a seeded preflight regression for the same missing-endpoint cases.
- [ ] Add or refresh the live engineering-loop coverage that exercises the new
  contract end to end.

## File-Level Change Set

The implementation should touch the smallest realistic set of files that
enforce the new contract:

- `shared/models/schemas.py`
- `shared/simulation/backends.py`
- `config/agents_config.yaml`
- `shared/assets/template_repos/engineer/assembly_definition.yaml`
- `payload_trajectory_definition.yaml` or the eventual engineer-owned schema file
  name
- `worker_heavy/utils/file_validation.py`
- `controller/agent/node_entry_validation.py`
- `controller/agent/review_handover.py`
- `controller/agent/tools.py`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/simulation-and-rendering.md`
- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/tools.md`
- `tests/integration/architecture_p0/test_planner_gates.py`
- `tests/integration/architecture_p0/test_node_entry_validation.py`
- `tests/integration/architecture_p0/test_int_008_objectives_validation.py`
- `tests/integration/architecture_p1/test_engineering_loop.py`
- `tests/integration/architecture_p1/test_script_tools_proxy.py`
- `specs/integration-test-list.md`
