---
title: Payload Trajectory Rotation Envelope and Swept Clearance Migration
status: migration
agents_affected:
  - engineer_planner
  - engineer_plan_reviewer
  - engineer_coder
  - engineer_execution_reviewer
added_at: '2026-04-05T19:27:22Z'
---

# Payload Trajectory Rotation Envelope and Swept Clearance Migration

<!-- Major migration. The orientation contract, swept-clearance validator, and seed refresh are the long pole. -->

## Purpose

This migration makes payload-path grounding orientation-explicit and swept-
clearance safe. The payload-path contract is mandatory baseline behavior for
every engineer handoff. The current contract can still leave room for an implied
`(0,0,0)` orientation, which is not strong enough for downstream users when a
nominally safe path becomes colliding at a different allowed rotation.

The target behavior is simple: every payload-path step must either declare an
exact rotation or declare an explicit admissible rotation envelope, and the
validator must prove that the payload does not intersect any fixed part for
every rotation admitted by that step. It must also prove that the payload
remains within the allowed objective bounds and does not enter forbid zones at
any checked pose. Omitted rotation is not a default.

The contract applies to engineer-owned motion artifacts that already live in
`motion_forecast` and `payload_trajectory_definition.yaml`. It keeps
build123d as the canonical geometry source, allows cached mesh acceleration
for repeated checks, and fails closed when the admissible rotation domain
cannot be proven safe.

The authoritative surrounding contracts live in:

- [Artifacts and Filesystem](../../architecture/agents/artifacts-and-filesystem.md)
- [Simulation and Rendering](../../architecture/simulation-and-rendering.md)
- [Tools](../../architecture/agents/tools.md)
- [Definitions of Success and Failure](../../architecture/agents/definitions-of-success-and-failure.md)

## Problem Statement

The repository already has a motion-path contract, but it is not yet strong
enough to prevent orientation-sensitive collisions.

1. `MotionForecastAnchor` still allows orientation to be omitted on path
   anchors, so a handoff can remain syntactically valid without proving a
   rotation-safe envelope.
2. `validate_payload_trajectory_definition_yaml()` checks cadence, endpoint
   proof, and moving-part parity, but it does not yet prove swept clearance
   against fixed geometry.
3. `validate()` already performs exact geometry validation for a loaded
   component, but that validation is static; it does not walk the payload
   through an admissible orientation domain.
4. A path can be correct at one nominal pose and invalid at another allowed
   rotation. That is a downstream correctness bug, not a rendering quirk.
5. A path can also be geometrically safe against fixed parts while still
   leaving the allowed objective envelope or crossing a forbid zone. That is a
   separate failure mode that must be checked on the same step samples.
6. The feature must work for arbitrary build123d geometry, not just boxes or
   a narrow family of symmetric parts.
7. The check must remain fast enough for submit-time validation, which means
   static geometry caching and parallel evaluation of independent samples
   matter.
8. Planner prompts and seed fixtures must teach a world in which the nominal
   pose can never be assumed. This feature removes that assumption.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `shared/models/schemas.py` | `MotionForecastAnchor` still permits optional `rot_deg` and optional `rotation_tolerance_deg` on shared motion anchors. | A payload path can remain valid without explicit orientation semantics. |
| `worker_heavy/utils/file_validation.py` | Validates motion cadence, ordered anchors, endpoint proof, and moving-part parity for `payload_trajectory_definition.yaml`. | It does not prove that every admissible rotation is clear of fixed geometry. |
| `worker_heavy/utils/validation.py` | Validates static component geometry and exact solid intersections for a loaded compound. | It does not yet validate swept clearance along a path through an orientation domain. |
| `worker_heavy/workbenches/analysis_utils.py` | Exposes `part_to_trimesh()` for build123d-to-trimesh conversion. | It is the obvious reuse point for cached broad-phase and repeated intersection checks. |
| `controller/agent/node_entry_validation.py` | Surfaces the current payload trajectory validator at node entry. | The new swept-clearance failure must appear at the same gate. |
| `benchmark_definition.yaml` objective contract | Defines build-zone and forbid-zone geometry for the scenario. | The swept-clearance validator must continue to enforce those objective envelopes at every checked pose. |
| `config/prompts.yaml` | Teaches general motion forecast and build-zone rules. | It does not yet tell planners that orientation must be explicit and swept-safe. |
| `config/agents_config.yaml` | Holds motion forecast budgets and planner policy knobs. | The new feature may need explicit budget or sampling policy, and any such policy must be visible here. |
| `dataset/data/seed/**` and `tests/integration/mock_responses/**` | Existing seeds and mock responses still encode the current motion contract. | They will need updates when the contract stops tolerating implicit rotation. |
| `tests/integration/architecture_p0/test_node_entry_validation.py` | Covers motion-forecast endpoint failures such as build-zone and goal-zone proof checks. | It does not yet cover a path that is safe at one orientation and colliding at another. |

## Proposed Target State

01. Every path step in the payload trajectory contract states explicit
    orientation semantics. A missing rotation is a validation failure for new
    handoffs, not a silent default to identity orientation.
02. If the planner wants a single pose, that pose is explicit. If the planner
    wants freedom, the admissible rotation envelope is explicit.
03. The validator proves clearance against all fixed parts in the composed
    scene, where fixed means zero motion regardless of ownership.
04. The validator also proves that the payload stays inside the allowed
    objective envelope and outside forbid zones at each checked pose.
05. The validator checks every sampled path step against every admissible
    orientation in that step's domain. A nominally safe pose is not sufficient
    if any allowed rotation collides or leaves the objective envelope.
06. The final decision remains conservative. If the admissible rotation domain
    cannot be proven within the available budget, the handoff fails closed.
07. build123d remains the source of truth for geometry, while cached trimesh
    data may accelerate broad-phase rejection and repeated intersection checks.
08. The swept-clearance logic stays behind a narrow validation boundary with a
    shared validator path and optional config gate. That keeps the feature easy
    to prune or disable later without refactoring unrelated planner, renderer,
    or benchmark code.
09. Planner prompts, review gates, and seeded workspaces all teach the same
    contract so invalid plans fail before downstream users inherit them.
10. The validator does not brute-force a dense three-axis rotation grid. It
    treats each admissible envelope as a bounded search region, accepts or
    rejects cells early with conservative proxies, and subdivides only
    ambiguous cells until the exact leaf budget is reached.

## Definitions

1. `explicit rotation` means the path step names the required orientation
   directly. There is no implied default orientation.
2. `admissible rotation envelope` means the explicit set or bounded range of
   rotations the step allows.
3. `fixed part` means any part in the assembled scene that resolves to zero
   motion axis, including benchmark fixtures and solution parts that are locked in
   place.
4. `objective-envelope proof` means the claim that the payload remains within
   the allowed objective bounds and outside forbid zones at every sampled
   pose.
5. `swept-clearance proof` means the claim that the payload, at every sampled
   step and every allowed rotation, does not intersect any fixed geometry and
   satisfies the objective-envelope proof.
6. `nominal pose` means one representative orientation only. It is not proof
   of safety by itself.

## Design Notes

01. Temporal spacing and orientation coverage are separate concerns. The
    existing `sample_stride_s` contract can continue to define the temporal
    sampling density, but it must not be used as a proxy for orientation
    completeness.
02. The exact collision rule is conservative: if the payload overlaps a fixed
    solid beyond modeling tolerance for any sampled step and any admissible
    rotation, the path is invalid.
03. The objective-envelope rule is equally conservative: if the payload leaves
    the allowed objective bounds or enters a forbid zone at any sampled step,
    the path is invalid.
04. The fixed-part set should be derived from the scene graph and the zero-motion
    contract, not from a filename list or a hand-maintained ownership table.
05. `trimesh` is an acceleration layer only. It may cache broad-phase bounds and
    repeated intersection queries, but it does not replace the canonical
    build123d geometry decision.
06. The implementation may parallelize independent pose/orientation checks.
    Deterministic final reporting still matters more than speculative speed.
07. If the orientation domain is too broad to prove exactly within the budget,
    the validator fails closed rather than silently narrowing the domain.
08. `build123d.revolve()` is not a valid general-purpose swept-clearance proof
    for arbitrary shapes. It may be a modeling operation in other contexts, but
    it does not satisfy this contract.
09. Broad-phase rejection should use conservative cached proxies such as AABB,
    OBB, bounding spheres, or convex hulls. Ambiguous orientation cells should
    be split recursively and only then promoted to exact build123d checks.
10. Keep the implementation localized to one dedicated validation module that
    is reached through narrow call sites from the existing gates. If the
    feature is disabled or removed later, the change should not require
    cross-cutting edits in planner, renderer, or benchmark code.
11. The adaptive search should split along the widest remaining angular span
    first so the validator spends exact geometry work where the admissible
    envelope is still uncertain.
12. Cache transformed payload geometry and proxy results by orientation cell
    and job scope so repeated checks do not re-run the same geometry work.
13. Load trimesh and build123d geometry once per validation job and keep the
    hot path CPU-bound. Do not export meshes or reinitialize the trimesh
    environment inside the orientation loop.
14. The reference performance experiment is
    `scripts/experiments/performance/payload-rotation-envelope-pruning/benchmark_payload_rotation_envelope_pruning.py`,
    with results in
    `scripts/experiments/performance/payload-rotation-envelope-pruning/results-20260408T095646Z.json`.
    It loads trimesh once per scenario, keeps the search loop in-memory, and
    records `setup_sec` separately from search timing.

## Required Work

### 1. Make orientation explicit in path artifacts

The path contract needs to stop tolerating implicit orientation. New authored
files must spell out the rotation semantics on every path step, and the
validator must treat missing rotation as invalid.

1. Make the payload path contract require explicit orientation metadata for
   every step in `motion_forecast` and `payload_trajectory_definition.yaml`.
2. Allow either an exact rotation or an explicit admissible envelope, but do
   not allow a missing rotation to degrade silently into `(0,0,0)`.
3. Keep any legacy compatibility bridge narrow and temporary. If a legacy file
   still omits orientation, it must fail closed unless the validator can prove
   the full allowed rotation domain.
4. Keep the contract shape general enough for arbitrary build123d solids and
   compounds.

### 2. Add budgeted swept-clearance validation

The validator needs to prove that the payload stays clear of all fixed parts
at every sampled step and every admissible rotation. The implementation should
prune obvious misses cheaply, recurse only where a cell remains ambiguous, and
reserve exact build123d work for the surviving leaf cells.

1. Load the payload geometry and the fixed scene geometry once per validation
   job.
2. Derive conservative broad-phase proxies once per job, then evaluate the
   full admissible orientation region as a bounded cell tree instead of a
   dense angular grid.
3. For each sampled path step, start with one cell that covers the whole
   admissible envelope. If the proxy result is clearly safe, accept that cell
   without exact geometry work. If the proxy result is clearly colliding,
   reject that cell immediately. If the result is ambiguous, split the cell
   along the widest remaining angular span and recurse.
4. Use exact build123d intersection semantics only on leaf cells that survive
   broad-phase pruning.
5. Cache transformed payload geometry and proxy results by orientation cell
   so repeated evaluations do not rebuild the same shape state.
6. Keep per-anchor caps for orientation cells, recursion depth, and exact
   booleans in config so proof cost is predictable.
7. Parallelize independent pose/orientation checks where practical.
8. Reject any path whose admissible domain cannot be proven safe with the
   available budget.
9. Do not rebuild trimesh scenes, export/import STL files, or recreate mesh
   adapters inside the cell recursion. Geometry conversion belongs at job
   setup, not inside the search loop.

### 3. Thread the contract through the existing gates

The new failure needs to show up everywhere the current motion contract is
already enforced. The feature should not create a second, inconsistent gate.

1. Extend the shared validator path so `payload_trajectory_definition.yaml`
   rejects underspecified orientation and swept-clearance violations.
2. Surface the same failure at node entry through
   `controller/agent/node_entry_validation.py`.
3. Keep the submit-time and reviewer-time gates aligned so the same invalid
   path fails before execution, not after.
4. Keep the failure deterministic and readable so the planner can correct the
   contract instead of guessing which orientation was checked.
5. Keep the geometry checker behind a single validation entry point and a
   dedicated module boundary so it can be disabled or pruned without
   cross-cutting changes to unrelated code paths.

### 4. Update docs and prompt policy

The planners need to be taught the new rule before they hand off a path that
looks plausible but is unsafe under rotation.

1. Update `config/prompts.yaml` so the planner instructions say that payload
   path orientation must be explicit and that the payload must remain inside
   the objective envelope while avoiding forbid zones.
2. Update the relevant architecture docs so the admissible rotation domain and
   swept-clearance rule are stated as contract language, not as an implied
   implementation detail.
3. Keep the prompt text and architecture docs aligned so the planners do not
   receive contradictory guidance about when a default pose is acceptable.
4. If a sampling-budget knob or feature gate is needed, define it in
   `config/agents_config.yaml` and document the fail-closed behavior and
   disable path alongside the existing motion policy knobs.
5. If the validator needs cached mesh state, define the cache scope as
   per-job and in-memory only. The implementation should never pay repeated
   I/O costs in the inner loop.

### 5. Refresh seeds and integration tests

The existing seeds and tests encode the older world where the nominal pose was
enough. They need to be refreshed so the new contract is visible at the system
boundary.

1. Update role-based seed workspaces and mock responses that still rely on
   implicit rotation or incomplete envelopes.
2. Add a negative integration case where the path is clear at the nominal
   orientation but collides at a permitted rotated orientation or exits the
   objective envelope.
3. Add a positive integration case where the path names an explicit
   orientation or envelope and remains clear across the admissible domain
   while staying inside build-zone and outside forbid zones.
4. Keep the integration verification path at the system boundary, using
   `./scripts/run_integration_tests.sh` for any new end-to-end checks.

## Non-Goals

1. Do not treat `(0, 0, 0)` as an implicit default when rotation is omitted.
2. Do not use `build123d.revolve()` as a general swept-clearance proof for
   arbitrary shapes.
3. Do not specialize the validator to boxes, cylinders, or any single shape
   family.
4. Do not change render overlay semantics or make the payload-path overlay a
   validation dependency.
5. Do not broaden benchmark-side motion semantics as a side effect of this
   migration.
6. Do not add a new agent-facing tool surface for the feature.
7. Do not thread the swept-clearance checker through unrelated planner,
   renderer, or benchmark flows; keep it removable behind the validation gate.

## Sequencing

1. Define the explicit orientation contract and the fail-closed behavior for
   missing rotation.
2. Implement the budgeted swept-clearance validator with cached geometry,
   broad-phase pruning, and parallel sample evaluation.
3. Thread the failure through node entry and submit-time validation.
4. Update prompts, architecture docs, and config policy text.
5. Refresh seeded workspaces, mock responses, and integration coverage.
6. Remove any temporary compatibility bridge only after the new contract is
   stable.

## Acceptance Criteria

1. A payload path that is clear at one orientation but collides at another
   allowed orientation or leaves the objective envelope is rejected.
2. A payload path artifact that omits required orientation metadata is
   rejected.
3. The validation logic handles arbitrary build123d solids and compounds.
4. The implementation may use cached trimesh acceleration, but the final
   decision remains conservative and grounded in build123d geometry.
5. The validator can parallelize independent checks without changing the
   failure semantics or hiding ambiguous results.
6. Planner-facing prompts and architecture docs state explicitly that
   orientation must be declared.
7. Seeded workspaces and integration tests cover both the rotated-collision
   failure and the explicit-rotation success case.
8. The swept-clearance validator can be disabled or removed by changing a
   single configuration or call-site boundary, without editing unrelated
   planner, renderer, or benchmark code.
