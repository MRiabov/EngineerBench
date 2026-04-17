---
title: Tube-Guided Synthetic Rigid-Body Corpus Generation Migration
status: work in progress
agents_affected:
  - benchmark_planner
  - benchmark_plan_reviewer
  - benchmark_coder
  - benchmark_reviewer
  - engineer_planner
  - engineer_plan_reviewer
  - engineer_coder
  - engineer_execution_reviewer
added_at: '2026-04-17T00:00:00Z'
---

<!-- Major migration. The tube is a scratch scaffold, not a published corpus artifact. -->

# Tube-Guided Synthetic Rigid-Body Corpus Generation Migration

## Purpose

This migration defines a synthetic corpus-generation policy for rigid-body-only
benchmarks and engineer solutions. The generator may use a tube-like corridor
as an intermediate scaffold while it builds a waypoint chain, derives a point
map, and tests contact order, but the published dataset must not keep the tube
as a final artifact.

The build zone for each synthetic candidate is expanded to cover the full
waypoint length plus the tube envelope before acceptance runs begin. That
enlarged build zone is part of the generation contract, not a convenience for
one lucky trajectory.

The target corpus accepts only candidates that survive batched runtime
randomization in MuJoCo or Genesis. A candidate is retained only when the
payload reaches the final waypoint, or terminal contact, in more than 80% of
10-20 jittered trials. After that pass, the scaffold is decomposed into simpler
primitives or simple primitive combinations and retested. Only the decomposed
result is published.

The migration composes with
[`payload-trajectory-rotation-envelope-and-swept-clearance-migration.md`](./payload-trajectory-rotation-envelope-and-swept-clearance-migration.md)
and
[`payload-trajectory-runtime-fail-fast-monitoring.md`](./payload-trajectory-runtime-fail-fast-monitoring.md).
Those migrations define motion correctness and runtime supervision. This
migration adds the corpus-generation and publication policy that decides which
candidate shapes are worth keeping.

## Problem Statement

The current seed and trajectory contracts can represent a valid route, but they
do not define a corpus-level generation loop that separates exploratory geometry
from final publication geometry.

1. A tube scaffold can be useful while generating waypoints, contact maps, and
   clearance candidates, but there is no explicit contract saying that the tube
   is scratch-only.
2. Without a separate publication rule, a dataset can accidentally teach the
   final model to emit a tube as if it were the target geometry, instead of
   decomposed primitives.
3. A single nominally successful simulation can overfit to one seed. The corpus
   needs a batched jitter filter so accepted examples are mechanically robust,
   not lucky.
4. The build zone must cover the entire waypoint chain and the tube envelope
   during generation. If the build zone is too small, the scratch scaffold and
   its decomposed replacement can become impossible to place.
5. The existing runtime validators establish correctness for a given artifact,
   but they do not define how to curate a training-ready corpus from a family of
   candidate artifacts.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `dataset/data/seed/readme.md` and `dataset/data/seed/role_based/*.json` | Seed rows are described as curated examples and seeds, but there is no corpus-level rule for tube scaffold versus final geometry. | The synthetic corpus needs a scratch/publish split so the tube does not leak into final outputs. |
| `dataset/data/seed/artifacts/**` | Artifact directories currently store the final handoff bundle for each role. | The corpus needs a published primitive-only output shape, plus scratch-only generation state that never enters the bundle. |
| `dataset/evals/materialize_seed_workspace.py` and `evals/logic/workspace.py` | Workspace materialization assumes the seed directory already contains the final contract-valid files. | The generator notebook still needs a clean way to emit final seeds after an exploratory scratch pass. |
| `shared/models/schemas.py`, `worker_heavy/utils/file_validation.py`, `worker_heavy/utils/payload_trajectory_validation.py`, `worker_heavy/simulation/payload_trajectory_monitor.py` | These files already validate trajectory shape, endpoint proof, clearance, and runtime contact order. | They do not define corpus acceptance across multiple jittered simulations or a tube-ablation publication rule. |
| `specs/architecture/simulation-and-rendering.md` and `specs/architecture/agents/definitions-of-success-and-failure.md` | These docs define backend split, general simulation assumptions, and runtime success/failure. | They do not specify the synthetic corpus policy for batched acceptance, build-zone expansion, or primitive-only publication. |
| Existing major migrations for payload-trajectory clearance and runtime fail-fast monitoring | They establish motion correctness and runtime supervision. | They do not say how to curate a training corpus from a tube-guided exploratory scaffold. |

## Proposed Target State

1. The generator may use a tube-like corridor only as an intermediate scaffold.
   The scaffold may exist in notebook-local state, scratch plots, or helper
   sidecars, but it is not a final dataset artifact.
2. The final published corpus contains only decomposed primitives or simple
   primitive combinations. The point map and contact map may survive as
   metadata, but the tube shape itself does not.
3. Candidate acceptance uses batched runtime randomization. The generator runs
   10-20 jittered simulations in MuJoCo or Genesis and retains only candidates
   that deliver the payload to the final waypoint or terminal contact in more
   than 80% of the trials.
4. The build zone for an accepted candidate encloses the full waypoint polyline
   plus the tube envelope and the decomposition clearance margin. Accepted
   candidates never rely on geometry outside that enlarged build zone, and the
   build zone spans the entire waypoint chain rather than only the terminal
   region.
5. After a candidate passes the tube-scaffold test, the generator decomposes
   the scaffold into simpler parts and reruns the same acceptance batch on the
   decomposed geometry. If the decomposed geometry fails, the generator retries
   the candidate under a different decomposition or geometry configuration
   before publication. The published result must still pass the same batch.
6. The published corpus remains compatible with the existing role-based seed
   layout and `seed_artifact_dir` materialization path.
7. The generator records which backend, MuJoCo or Genesis, produced the
   accepted candidate, but the corpus contract remains backend-agnostic at the
   publication layer.

## Required Work

### Generator surface

- Author a self-contained Jupyter notebook prototype for exploratory corpus
  generation.
- Generate waypoints, a point map, and a tube-scaffold candidate in scratch
  state.
- Export only the decomposed primitive geometry and the final trajectory
  metadata to the publishable seed directory.

### Acceptance filtering

- Run 10-20 jittered simulations per candidate using the repository's existing
  runtime randomization logic.
- Reject candidates that do not clear the >80% success threshold to the final
  waypoint or terminal contact.
- Record backend choice, sample count, success rate, and terminal outcome for
  every accepted candidate.

### Decomposition and retest

- Decompose each tube scaffold into simpler primitives or primitive
  combinations before publication.
- Rerun the same batched acceptance on the decomposed geometry.
- Reject any candidate whose decomposed geometry no longer meets the success
  threshold.

### Geometry bounds

- Derive a build zone that encloses the entire waypoint path, the tube radius,
  and the decomposition margin.
- Fail closed when a candidate cannot fit inside the enlarged build zone.

### Validation and docs

- Update seed guidance so the scratch tube scaffold and the published primitive
  corpus are clearly separated.
- Add regression coverage that proves the final published artifacts do not
  contain tube-only geometry.
- Keep the existing trajectory-clearance and runtime-monitor migrations as the
  source of truth for motion correctness.

## Non-Goals

- Do not publish the tube scaffold as a final seed artifact.
- Do not replace the trajectory validation or runtime-monitor contracts with a
  corpus heuristic.
- Do not introduce a new public dataset format outside the existing
  role-based seed layout.
- Do not add motors, deformables, fluids, or other non-rigid-body behavior to
  the synthetic corpus.
- Do not accept a candidate on a single successful run.

## Sequencing

1. Prototype the notebook-level generator and point-map capture.
2. Add the batched MuJoCo or Genesis acceptance loop with the >80% threshold.
3. Add the tube-to-primitives decomposition pass and rerun logic.
4. Publish only decomposed primitives into the seed artifact layout.
5. Add regression coverage and seed guidance updates.

## Acceptance Criteria

1. A candidate is not accepted unless it succeeds in more than 80% of 10-20
   jittered simulation runs.
2. The final published artifact set contains only decomposed primitives or
   simple primitive combinations.
3. The tube scaffold may exist in notebook scratch state, but it never appears
   in the final dataset output directory.
4. The accepted build zone covers the entire waypoint and tube envelope,
   including the decomposition clearance margin.
5. A candidate that passes with the tube scaffold but fails after decomposition
   is not published; it is retried under a different configuration and only
   published if a decomposed variant clears the batch.
6. The corpus still materializes through the existing seed workspace contract
   without a parallel public format.

## Test Impact

- Add or refresh a regression that checks the final corpus does not publish a
  tube-only artifact.
- Add or refresh a regression for the enlarged build-zone envelope.
- Add or refresh a regression proving the decomposed primitive output still
  passes the batched acceptance rule.

## Migration Checklist

### Corpus shape

- [ ] Define the scratch-only tube scaffold and the final primitive-only
      publication shape.
- [ ] Keep the point map and contact order in notebook-local or sidecar form
      only.
- [ ] Extend the build-zone derivation to cover the full waypoint and tube
      envelope.

### Simulation filtering

- [ ] Implement batched MuJoCo or Genesis evaluation over 10-20 jittered
      trials.
- [ ] Enforce the >80% success threshold to the final waypoint or terminal
      contact.
- [ ] Record backend and success-rate metadata for accepted candidates.

### Decomposition

- [ ] Add the tube-to-primitives decomposition pass.
- [ ] Rerun the same batched acceptance after decomposition.
- [ ] Reject candidates whose decomposition breaks the success threshold.

### Publication and validation

- [ ] Ensure final dataset export never serializes tube geometry.
- [ ] Refresh seed guidance and regression coverage for the new corpus
      contract.
- [ ] Keep the existing motion-validation migrations as the source of truth
      for path correctness.

## File-Level Change Set

- `specs/migrations/major/tube-guided-synthetic-rigid-body-corpus-generation.md`
- `dataset/data/seed/readme.md`
- `dataset/data/seed/role_based/*.json`
- `dataset/data/seed/artifacts/**`
- A self-contained Jupyter notebook or equivalent exploratory generator
  module for corpus synthesis
- Regression coverage under `tests/integration/**` for the primitive-only
  publication rule and enlarged build-zone envelope
