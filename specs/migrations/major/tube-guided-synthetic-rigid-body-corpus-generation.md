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
benchmarks and engineer solutions. The source input is the full benchmark-owned
bundle plus a predefined path / waypoint trace. The generator may use a
tube-like corridor as an intermediate scaffold while it builds a waypoint
chain, derives the wall-contact cloud, and tests contact order, but the
published dataset must not keep the tube as a final artifact.

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

The role split is explicit:

1. `engineer_planner` rows own the geometry plan, the evidence plan script, and
   the completed `assembly_definition.yaml` geometry bundle.
2. `engineer_coder` rows own `solution_script.py` and the refined
   `payload_trajectory_definition.yaml` that mirrors the planner geometry.
3. Render bundles are optional, regenerable review artifacts for either stage.

## Problem Statement

The current seed and trajectory contracts can represent a valid route, but they
do not define a corpus-level generation loop that separates benchmark-owned
input, planner geometry, and coder implementation geometry.

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
6. The repo does not yet define the input bundle shape for these synthetic
   rows, so planner and coder outputs can drift away from the benchmark-owned
   path trace.

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
   primitive combinations. The wall-contact point cloud and contact map may
   survive as metadata, but the tube shape itself does not.
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
- Start from the benchmark-owned input bundle and a manually supplied path
  trace, not from a prior engineer row.
- Generate waypoints, a wall-contact point cloud, and a tube-scaffold candidate
  in scratch state.
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

### Input Bundle Contract

- Consume the benchmark-owned bundle as the source of objectives, fixtures,
  build-zone context, and benchmark geometry.
- Consume a manually authored route trace or waypoint list as the source of the
  path shape.
- Treat the planner row as the first exportable synthesis of that input bundle.
- Treat the coder row as the second exportable synthesis of the planner row.
- Keep the input bundle separate from both row outputs so the path trace can be
  revised without rewriting the benchmark-owned fixtures.

### Point-Cloud Contract

- Treat the point cloud as the ordered set of payload-to-wall collision points
  produced by the scratch tube run.
- Preserve the contact cloud as validation metadata for the published corpus.
- Require the decomposed primitive geometry to reproduce the same collision
  cloud within the notebook's explicit tolerance budget.
- Keep at least one retained primitive for every collision cluster that is
  required to reproduce the cloud.

### CAD Lowering Contract

- Lower the scratch tube into a stack of box primitives arranged around the
  waypoint polyline, not into a single tube solid.
- Use four-sided box coverage along the route so the envelope is represented by
  separate geometric primitives on the surrounding sides.
- Randomly split the box stack along waypoint intervals so long routes become a
  sequence of shorter boxes instead of long monolithic bars.
- Prune boxes that never contribute to the collision cloud or to the support
  chain needed to reproduce it.
- Keep the primitive family simple and fail closed if the box template cannot
  reproduce the cloud within tolerance.

### Retry Policy

- Retry failed decompositions with a different segment partition or box
  template layout.
- Change the segmentation or primitive template on retry; do not rely on scale
  factor tweaks alone.
- Stop retrying only after the candidate budget is exhausted or a decomposed
  variant clears the batch.

### Export Bundle Contract

- Materialize accepted planner-stage candidates into
  `dataset/data/seed/artifacts/engineer_planner/<row-id>/`.
- Materialize accepted coder-stage candidates into
  `dataset/data/seed/artifacts/engineer_coder/<row-id>/`.
- Treat the `.solution/` subtree as the exportable bundle for either row.
- Preserve the copied benchmark-owned input files inside both row bundles as
  read-only context: `benchmark_script.py`, `benchmark_definition.yaml`, and
  `benchmark_assembly_definition.yaml`.
- Preserve the planner-stage machine outputs as
  `assembly_definition.yaml` and `solution_plan_evidence_script.py`.
- Preserve the coder-stage machine outputs as
  `solution_script.py` and `payload_trajectory_definition.yaml`.
- Treat `engineering_plan.md`, `solution_description.md`, `journal.md`, and
  `todo.md` as human-fillable review artifacts that may be written manually
  after the first machine export pass.
- Keep `reviews/` and render sidecars when they exist, but treat them as stage
  review evidence rather than authored CAD.
- Represent planner rows in `dataset/data/seed/role_based/engineer_planner.json`
  and coder rows in `dataset/data/seed/role_based/engineer_coder.json`, using
  the existing row fields for each.
- Delay export until the relevant batch passes, but keep each resulting bundle
  directly materializable without manual renaming or ad hoc file creation.

### File Production Split

- Benchmark-owned files are input context copied into the row bundle, not
  authored by the synthetic generation pipeline.
- Planner-stage machine generation produces the geometry contract and the plan
  evidence script.
- Coder-stage machine generation produces the solution implementation and the
  refined payload-trajectory proof.
- Narrative Markdown files are ordinary workspace files that can be created as
  placeholders and then edited in place in the materialized bundle.
- The notebook is the synthesis interface for geometry and proof generation;
  the filesystem editor is the authoring interface for Markdown.

### Visualization Contract

- Produce persistent render bundles for the accepted primitive-only candidate,
  not just notebook screenshots.
- Render the route, the wall-contact cloud, the decomposed primitive assembly,
  and the payload-path overlay as separate review cues.
- Keep the render output in the existing staged render layout with a manifest
  and the relevant image sidecars so reviewers can inspect it without rerunning
  the notebook.
- Allow scratch-only previews of the tube scaffold during exploration, but keep
  those previews outside the published seed row.

### Human Review Contract

- Write `solution_description.md` as the reviewer-facing explanation of the
  decomposition choice, retry history, and why the final primitive layout was
  retained.
- Write `journal.md` as the provenance log of candidate variants, batch
  outcomes, backend choice, and retry reasons.
- Keep `todo.md` as the remaining work record until the row is exported.
- Keep the final bundle self-contained enough that a reviewer can inspect the
  CAD, the trajectory proof, and the render evidence without reconstructing the
  notebook.
- Allow the narrative Markdown files to be populated manually later if the
  machine export pass only emits the geometry, YAML, and script files first.

### Markdown Authoring Contract

- Treat Markdown files as plain text artifacts in the row bundle, not as
  notebook outputs.
- Write Markdown files directly in the materialized `.solution/` directory, or
  emit them as placeholder files that are then edited in place in the same
  workspace.
- Use the notebook for geometry synthesis, simulation, and export decisions;
  do not use it as the authoring interface for `engineering_plan.md`,
  `solution_description.md`, `journal.md`, or `todo.md`.
- If a machine export pass omits narrative Markdown, the follow-up interface is
  the filesystem editor against the row bundle, not a separate notebook stage.

### Solution-Code Shape Contract

- Put the planner-stage geometry construction in the planner row and the coder
  stage transformation in `solution_script.py`.
- Structure the generated CAD code with named helpers for route segmentation,
  box-template generation, pruning, and export.
- Allow the code to consume waypoint and collision data, but do not encode the
  transformation as a direct waypoint-to-box one-liner.
- Keep `solution_plan_evidence_script.py` as a thin build and preview stub that
  reflects the final geometry, not the decomposition algorithm itself.
- Favor explicit geometric helpers and intermediate named variables so the code
  reads like authored CAD instead of notebook debris.

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

1. Prototype the notebook-level generator and wall-contact cloud capture from
   the benchmark-owned input bundle.
2. Add the planner-stage geometry export and the batched MuJoCo or Genesis
   acceptance loop with the >80% threshold.
3. Add the coder-stage primitive lowering pass and rerun logic.
4. Publish planner and coder rows into their respective seed artifact layouts.
5. Add regression coverage, seed guidance updates, and export-bundle checks.

## Acceptance Criteria

01. A candidate is not accepted unless it succeeds in more than 80% of 10-20
    jittered simulation runs.
02. The final published artifact set contains only decomposed primitives or
    simple primitive combinations.
03. The tube scaffold may exist in notebook scratch state, but it never appears
    in the final dataset output directory.
04. The accepted build zone covers the entire waypoint and tube envelope,
    including the decomposition clearance margin.
05. A candidate that passes with the tube scaffold but fails after decomposition
    is not published; it is retried under a different configuration and only
    published if a decomposed variant clears the batch.
06. The corpus still materializes through the existing seed workspace contract
    without a parallel public format.
07. The accepted planner row can be exported into the existing engineer-planner
    `.solution` bundle shape without manual file surgery.
08. The accepted coder row can be exported into the existing engineer-coder
    `.solution` bundle shape without manual file surgery.
09. The published bundles include reviewer-friendly render evidence and the
    human-readable summary files needed to inspect the result downstream.
10. The planner evidence script remains a thin preview artifact, and the coder
    solution script remains a real authored CAD lowering implementation.
11. Narrative Markdown files may be written manually after the first export
    pass and still count as valid completion of the row contract.
12. Copied benchmark-owned files remain read-only context inside both bundles
    and are not rewritten by the synthetic generator.

## Test Impact

- Add or refresh a regression that checks the final corpus does not publish a
  tube-only artifact.
- Add or refresh a regression for the enlarged build-zone envelope.
- Add or refresh a regression proving the decomposed primitive output still
  passes the batched acceptance rule.
- Add or refresh a regression that the exported engineer-planner and
  engineer-coder rows contain the expected `.solution/` file sets and render
  evidence.
- Add or refresh a regression that `solution_plan_evidence_script.py` remains
  planner-evidence-only and does not own the coder lowering logic.
- Add or refresh a regression that the machine export pass still succeeds when
  the narrative Markdown files are deferred to manual fill-in.

## Migration Checklist

### Corpus shape

- [ ] Define the scratch-only tube scaffold and the final primitive-only
  publication shape.
- [ ] Keep the wall-contact cloud and contact order in notebook-local or sidecar form
  only.
- [ ] Define the benchmark-owned input bundle and the manual path trace source.
- [ ] Split the export surface into planner-stage and coder-stage row bundles.
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
- [ ] Add seed-row coverage for both `engineer_planner.json` and
  `engineer_coder.json`.

## File-Level Change Set

- `specs/migrations/major/tube-guided-synthetic-rigid-body-corpus-generation.md`
- `dataset/data/seed/readme.md`
- `dataset/data/seed/role_based/engineer_planner.json`
- `dataset/data/seed/role_based/engineer_coder.json`
- `dataset/data/seed/artifacts/engineer_planner/**/.solution/**`
- `dataset/data/seed/artifacts/engineer_coder/**/.solution/**`
- `shared/assets/template_repos/engineer/solution_plan_evidence_script.py`
- A self-contained Jupyter notebook or equivalent exploratory generator
  module for corpus synthesis
- Regression coverage under `tests/integration/**` for the primitive-only
  publication rule, enlarged build-zone envelope, export bundle shape, and
  evidence-script split
