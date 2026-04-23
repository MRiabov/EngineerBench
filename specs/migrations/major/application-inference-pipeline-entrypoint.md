---
title: Application Inference Pipeline Entrypoint Migration
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
added_at: '2026-04-23T00:00:00Z'
---

# Application Inference Pipeline Entrypoint Migration

<!-- Major migration. The implementation may be a small script, but the
application contract is larger than a seed-only helper. -->

## Purpose

This migration promotes the current seed-oriented agent loop into a formal
application inference pipeline.

The core execution model does not change:

1. materialize a workspace,
2. spawn the same agents and reviewer roles as before,
3. let those agents complete the task through the existing tool and review
   flow,
4. validate and review the outputs,
5. optionally persist validated and reviewed benchmark bundles into
   `engineer_planner` seed storage.

What changes is the application contract around that loop. The pipeline becomes
an explicit entrypoint for stage-driven inference jobs with internal state and
graph progression, not just a seed generator or seed maintenance script. The
migration removes the current `engineer_planner`-only hardcoding, makes the
benchmark plan-review and benchmark execution-review stages explicit runnable
stages, and turns seed persistence into one optional, gated sink instead of the
whole reason for the pipeline to exist.

This migration is intentionally compatible with the current quick-prototype
workflow. The existing seed-autopilot path remains available. The new contract
adds a formal application entrypoint that can be used for larger batch work,
replayable job progression, and optional eval-seed backfill from validated and
reviewed outputs.

The application inference pipeline is a distinct pipeline from the seed-update
autopilot. The application entrypoint must not depend on
`dataset/evals/eval_seed_update_autopilot_per_seed.py` as a runtime path. Any
shared workspace, validation, review, or copy-back behavior must live in
extracted shared helpers under the library surface and be imported by both
pipelines directly.

## Execution Contract

The migration is executed by extending shared runner primitives rather than
routing the application pipeline through the seed-update autopilot devtool.

1. Load `inference_config.yaml` through `evals.logic.inference_pipeline`.
2. Resolve the requested `stage_name` against the config and build a stage
   executor registry from `InferenceStageConfig.executor`.
   The entrypoint may also accept a `--run-until-stage` cutoff so a run can
   drain downstream stages only through a chosen reachable stage without
   mutating the config.
3. Load `logs/evals/inference_pipeline/task_state.json` as the authoritative
   application resume state and
   `logs/evals/seed_update_autopilot/task_state.json` as the compatibility
   mirror.
4. Select jobs from the requested seed rows, artifact directories, or derived
   jobs using the declared `workspace_source` type and the deduplication
   policy.
5. Materialize the workspace with shared helpers, run the application
   pipeline's worker/review loop, advance the internal job graph, and convert
   the result into
   `InferenceJobResult` and `InferenceJobState`.
6. Write the per-job state and run summary after each completion.
7. Copy successful outputs back into `engineer_planner` seed storage only when
   `persist_results` is enabled and the normal validation/review gates have
   passed.
8. Refresh the compatibility seed-state only after copy-back succeeds.

The pipeline must fail closed on unknown stage names, unknown executor names,
stale resume tokens, missing `workspace_source` fields, or a mismatch between
the selected mode and the stage graph. `planned` remains a declaration-only
executor value until a real adapter is wired.

## Pipeline Shape

At a high level, the application inference pipeline looks like this:

```text
job request
  -> resolve stage / mode / workspace source
  -> load progression state
  -> select the next eligible job
  -> materialize a workspace
  -> dispatch the stage executor
  -> run the existing validate / review / repair loop
  -> classify outcome
  -> optionally persist validated and reviewed results to eval seeds
  -> write job summary + updated resume state
```

The entrypoint keeps an internal job graph and resume state. Persistence to
the seed corpus is an optional sink off that graph, not the graph itself.

The entrypoint is not a new solver. It is a stateful orchestrator around the
existing agent workflow.

### Job Request Contract

Each inference job should carry, at minimum:

- `job_id`: a stable identifier for the run or batch
- `stage_name`: the declared stage to execute; unknown stage names fail closed
- `mode`: `application`, `eval_seed_backfill`, or
  `compatibility_seed_autopilot`
- `workspace_source`: a typed `InferenceWorkspaceSource` that declares one of
  `seed_row`, `artifact_dir`, `derived_job`, or `bundle`, plus the fields
  required by that source type
- `persist_results`: the explicit copy-back decision for the run; copy-back is
  permitted only for outputs that pass validation and review
- `resume_token`: optional resume pointer; persisted state remains authoritative
  when the token is absent or stale
- `metadata`: structured provenance fields for observability, including family,
  variant, complexity level, and upstream job id when present

### Pipeline Stages

1. **Resolve**: load the current job request, resolve the requested stage,
   and bind the executor registry for that stage.
2. **Select**: choose the next eligible job from the requested source using
   the stage's workspace source type, the resume state, and the deduplication
   policy.
3. **Materialize**: build the workspace through the current seed helper or
   the stage-specific materializer owned by the executor registry.
4. **Execute**: dispatch the wired executor; declared-but-unwired stages must
   not be run.
5. **Validate**: run the existing validation gates without inventing a new
   contract.
6. **Review**: run the existing review gates.
7. **Persist**: if the job policy asks for it and the gates pass, copy the
   results back into eval seed storage and then refresh the compatibility
   seed-state.
8. **Record**: write the run summary, job outcome, and next resume point.

### Outcome States

The pipeline should surface these job-level outcomes:

- `queued`
- `running`
- `validated`
- `reviewed`
- `persisted`
- `skipped`
- `failed`
- `interrupted`

Those states are application-level bookkeeping. They do not replace the
existing per-seed validation and review semantics.

## Inference Config

The pipeline is configured by `inference_config.yaml`, which is parsed into
the strict `InferencePipelineConfig` model in
`evals/logic/inference_pipeline.py`. The schema uses `extra=forbid`; unknown
keys are configuration errors, not soft defaults.

The current schema owns these top-level fields:

- `pipeline_name`
- `version`
- `mode`
- `entry_stage_name`
- `stages`
- top-level `worker_hints`
- `retry_policy`
- `resume_policy`
- `deduplication`

Each `stages[]` entry owns these fields:

- `name`
- `agent_name`
- `outputs_per_success`
- `persist_back_to_seed`
- `downstream_stage_names`
- `executor`
- `worker_hints`
- `description`

The config must express:

1. fan-out from one successful upstream output to multiple downstream jobs,
2. different multiplicities per stage,
3. which stages persist back into eval seeds and which seed corpus they feed,
4. the operational controls needed for long-running batch inference.

`executor: planned` means the stage is declarative only. It must not be
treated as runnable. `executor: seed_worker` means the current compatibility
worker path is wired.

The first executable benchmark release must add explicit
`benchmark_plan_reviewer` and `benchmark_reviewer` entries to `stages[]` and
wire them through the executor registry before any engineer-only stage is
treated as part of the executable pipeline.

The checked-in config is therefore incomplete until it declares the full
benchmark chain. The current file still hardcodes only the benchmark
planner/coder placeholders plus the engineer_planner compatibility path, so
the migration must widen the graph instead of just renaming the existing
entrypoint.

The benchmark-side persistence sink is separate from the executable graph:

- the approved benchmark bundle can be copied forward into
  `engineer_planner` seed storage when persistence is enabled,
- the benchmark reviewer output is the canonical persisted form of that
  bundle, and
- the benchmark coder output is eligible only when it corresponds to a
  validated and reviewed bundle and the review artifact is intentionally
  omitted from the persisted copy.

That sink is a family-plan-backed corpus-generation step, not a new solver
stage. If the pipeline ever needs more than one persistence target, add a
schema-declared `persistence_targets` section and keep it fail-closed rather
than inferring sinks from prompt text or worker behavior.

The stage graph is declarative even when a stage is not yet executable. Each
stage names an executor adapter so the pipeline can distinguish between a
declared stage and a wired stage.

The first executable release must wire the full benchmark graph:
`benchmark_planner`, `benchmark_plan_reviewer`, `benchmark_coder`, and
`benchmark_reviewer`. Engineer stages may remain declared but inert until a
later release, but the first release is not complete until the benchmark
nodes are runnable end to end.

`persist_results` is a pipeline-level decision, but the worker path still has
to receive it as an explicit execution flag so the same loop can run either as
run-only inference or as eval-seed backfill without changing the prompt
contract.

The pipeline also needs two separate persisted state surfaces:

- `logs/evals/inference_pipeline/task_state.json` for application job resume
  and deduplication, and
- `logs/evals/seed_update_autopilot/task_state.json` for compatibility with the
  current seed-update autopilot skip logic.

## Problem Statement

The repository already has row-level seed selection, repair, validation, and
copy-back logic. That is useful, but it reads like a maintainer script rather
than a product-level inference pipeline.

That creates three problems:

1. The job flow is framed as seed maintenance, so the application surface looks
   smaller than it is.
2. Progression state exists at the row level, but not as a first-class
   application job model.
3. Optional persistence back into eval seeds is implicit instead of being a
   documented sink in the pipeline contract.

The result is that we already have most of the machinery needed for inference
jobs, but not the formal application entrypoint that should own it.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `evals/logic/inference_pipeline.py` | Strict typed pipeline config, job request/result/state models, and pipeline run-state path helpers. | The application entrypoint needs a typed contract boundary instead of ad hoc dicts, and the contract must stay fail-closed on unknown fields. |
| `dataset/evals/eval_inference_pipeline.py` | Canonical application-facing entrypoint that loads `inference_config.yaml`, records pipeline job state, dispatches a stage executor registry, and persists resume/checkpoint metadata under `logs/evals/inference_pipeline/`. | This is the formal application surface, and the current implementation keeps the benchmark graph and job state internally while queueing downstream jobs instead of auto-executing the full transitive graph in one invocation. |
| `dataset/evals/eval_seed_update_autopilot_per_seed.py` | Runs seed selection, workspace bootstrap, Codex CLI spawning, validation, review, and copy-back for one canonical seed row at a time. | This is a separate maintenance pipeline; any reusable behavior must be extracted into shared helpers before the application pipeline can use it. |
| `dataset/evals/eval_seed_update_autopilot.py` | Thin compatibility wrapper around the per-seed implementation. | It preserves the old path, but it does not define a formal application contract and must not become the application pipeline's runtime dependency. |
| `inference_config.yaml` | Declarative stage graph, fan-out policy, retry policy, resume policy, and executor names, including the benchmark plan-review and benchmark execution-review nodes and the engineer compatibility sink. | The graph is now versioned with the application rather than implied by code paths. |
| `dataset/evals/materialize_seed_workspace.py` | Materializes a seed workspace for inspection or CLI launch. | It is the right workspace primitive, but it needs to be owned by a broader pipeline contract. |
| `scripts/internal/eval_seed_selection.py` | Resolves seed datasets and canonical task ids. | It is selection plumbing, not application job progression. |
| `shared/eval_artifacts.py` | Manages seed artifact registries, manifests, and workspace helpers. | It lacks an explicit application-level job/persistence sink model. |
| `dataset/evals/run_e2e_seed.py` | Replays the end-to-end seed flow with resume support. | It is close to the right shape, but it is still a seed-specific runner, not a formal application entrypoint. |
| `specs/devtools.md` | Documents the application inference entrypoint, but still needs sharper separation between the stage-driven pipeline and the seed-autopilot compatibility wrapper. | The developer instrumentation doc must mirror the new stage contract exactly. |
| `evals/logic/runner.py` and `evals/logic/runner_execution.py` | Coordinate eval-style execution and resume behavior. | These are useful building blocks, but they do not yet define the top-level application inference contract. |

## Proposed Target State

1. The application exposes a canonical inference pipeline entrypoint with a
   documented job contract, internal state graph, and stage executor registry.
2. The pipeline accepts an inference job description, materializes the
   workspace, dispatches the registered stage executor, and runs the existing
   validation/review flow unchanged.
3. Seed persistence becomes an optional sink. When enabled, only validated and
   reviewed jobs can write back the approved benchmark bundle into
   `engineer_planner` seed storage.
4. The pipeline records progression state at the job level so long-running or
   interrupted runs can resume cleanly.
5. The current seed-autopilot behavior remains available as a compatibility
   mode or wrapper over the pipeline, not as the only conceptual contract.
6. No new agent role or custom reasoning path is introduced. The pipeline is
   orchestration, not a solver.
7. The entrypoint can be used both for evaluation-oriented seed work and for
   broader application inference jobs that do not persist back into the seed
   corpus.
8. The formal entrypoint owns the job lifecycle, while the per-seed execution
   loop remains the worker-facing unit of work and the compatibility shim.
9. The first release must wire `benchmark_planner`, `benchmark_plan_reviewer`,
   `benchmark_coder`, and `benchmark_reviewer` end to end, while the engineer
   graph may remain declared but not yet wired.

## Required Work

### 1. Define the application inference entrypoint

- Add a canonical top-level entrypoint for inference jobs.
- Add `evals/logic/inference_pipeline.py` with typed pipeline config, job
  request/result, and job state models.
- Keep the pipeline models strict and fail closed on unknown fields.
- Make the entrypoint load `inference_config.yaml` as part of startup.
- Give the entrypoint an explicit job model with:
  - job identity
  - stage name
  - mode
  - workspace source
  - persistence policy
  - resume information
  - run metadata
- Keep the job model explicit. Do not infer the contract from ad hoc CLI flags
  or from log filenames alone.

### 2. Reuse the existing agent execution flow

- Keep the underlying materialize-launch-validate-review-copy-back primitives
  intact by extracting them into shared helpers.
- Continue spawning the same agents as before.
- Continue using the same workspace materialization and validation helpers
  where possible, but import them from shared library code rather than from
  `dataset/evals/eval_seed_update_autopilot_per_seed.py`.
- Add an executor registry so the pipeline can distinguish declarative stages
  from wired stages. Replace the current `engineer_planner` / `seed_worker`
  hardcoding in `dataset/evals/eval_inference_pipeline.py`.
- The first release must wire the full benchmark graph through the existing
  agent and reviewer paths.
- Propagate `persist_results` from the pipeline entrypoint into the worker
  execution path so the same loop can run in backfill or run-only mode.
- Do not add a new solver path or custom agent semantics for the new entrypoint.

### 3. Make persistence optional and explicit

- Add an explicit persistence sink for eval seed artifacts that accepts only
  validated and reviewed benchmark outputs.
- When persistence is enabled, write the approved benchmark bundle back into
  the `engineer_planner` seed corpus after the normal validation/review gates
  pass.
- When persistence is disabled, treat the run as a normal application
  inference job and preserve only the run artifacts and job state.
- Keep persistence decisions out of the worker prompt. They belong in the
  pipeline contract.
- Treat benchmark reviewer output as the canonical persisted bundle. Benchmark
  coder output is only eligible as the same bundle when it corresponds to a
  validated and reviewed run and the review document is intentionally omitted
  by policy.

### 4. Promote progression state to a first-class job concept

- Record selected jobs, skipped jobs, completed jobs, and failed jobs in a
  run summary or equivalent persisted state.
- Make resume behavior deterministic from the persisted job state.
- Use `inference_config.yaml` to determine which downstream jobs should be
  spawned from each successful upstream output, including the benchmark
  reviewer chain and any later engineer fan-out.
- Keep row-level skip/repair behavior, but treat it as a detail of the
  pipeline rather than the whole application surface.
- Avoid silent retries or silent fallback when a job is already known to be
  clean, exhausted, or intentionally excluded.
- Keep the application pipeline resume file separate from the seed-update
  autopilot task-state file, and treat the compatibility file as a mirror that
  is refreshed only after a successful copy-back.

### 5. Update docs and contracts

- Update `specs/devtools.md` so the canonical entrypoint is described as an
  application inference pipeline, not only as a seed generator.
- Update any architecture or handover docs that still imply the loop is seed
  maintenance only, especially the docs that describe the benchmark review
  chain and reviewer manifest ownership.
- Keep the existing seed-specific documentation, but classify it as one mode
  of the broader pipeline.

### 6. Add regression coverage

- Add a regression that proves the pipeline can spawn the same agents and
  complete a job without persisting back into eval seeds.
- Add a regression that proves the optional persistence sink writes back only
  after the normal validation/review gates pass.
- Add a regression that proves resume state survives interruption and does not
  duplicate already-completed jobs.
- Add a regression that proves the compatibility seed-autopilot path still
  works as a thin wrapper or mode on top of the pipeline.
- Add a regression that proves the first release can wire the full benchmark
  graph before any engineer stages are promoted.
- Add a regression that proves benchmark reviewer output can be copied into
  `engineer_planner` seed storage and that benchmark coder output is accepted
  only when it corresponds to a validated and reviewed bundle whose review
  document is intentionally omitted.

## Implementation Checklist

### Phase 1: Define the contract

- [x] Add `evals/logic/inference_pipeline.py` with typed pipeline config,
  request, result, state, and summary models.
- [x] Add `inference_config.yaml` to the repo and make its schema explicit,
  including the benchmark reviewer chain.
- [x] Define the top-level inference job model, including mode, workspace
  source, persistence policy, and resume state.
- [x] Define the stage executor registry and document which stage names are
  wired in the first release, including the benchmark plan-review and
  benchmark execution-review stages.
- [x] Decide which existing CLI or module will be the canonical application
  entrypoint.
- [x] Add `dataset/evals/eval_inference_pipeline.py` as the canonical
  application entrypoint.

### Phase 2: Wire the execution path

- [x] Load `inference_config.yaml` at pipeline startup.
- [x] Reuse the existing workspace materialization path.
- [x] Reuse the existing agent spawning path.
- [x] Reuse the existing validation, review, and copy-back gates.
- [x] Extract the shared workspace, validation, review, and copy-back helpers
  out of `dataset/evals/eval_seed_update_autopilot_per_seed.py` so
  `dataset/evals/eval_inference_pipeline.py` does not depend on the
  seed-maintenance devtool at runtime.
- [x] Remove the application pipeline runtime dependency on
  `dataset/evals/eval_seed_update_autopilot_per_seed.py` by extracting the
  shared workspace, validation, review, and copy-back helpers into the
  library surface.
- [x] Replace the `dataset/evals/eval_inference_pipeline.py`
  `engineer_planner` / `seed_worker` hardcoding with stage registry
  dispatch.
- [x] Wire benchmark_planner, benchmark_plan_reviewer, benchmark_coder, and
  benchmark_reviewer end to end before declaring the first release
  complete.
- [x] Add `--persist-results` / `--no-persist-results` to the worker path and
  forward that policy from the pipeline entrypoint.
- [x] Persist application pipeline runs under `logs/evals/inference_pipeline/`
  with separate run and state files from the seed-update autopilot.
- [x] Keep the current seed-autopilot loop available as compatibility
  plumbing.

### Phase 3: Make fan-out data-driven

- [x] Read stage fan-out from `inference_config.yaml`.
- [x] Support downstream multiplicity per successful upstream output.
- [x] Support stage-specific persistence policies.
- [x] Support stage-specific queue or worker hints if needed.
- [x] Allow stages to be declared before they are executable so the graph can
  be versioned ahead of adapter wiring.

### Phase 4: Persist state and outputs

- [x] Record job status transitions in persisted run state.
- [x] Record selected, skipped, completed, failed, and persisted jobs.
- [x] Make resume deterministic from persisted job state.
- [x] Add optional eval-seed persistence as a post-validation sink.
- [x] Refresh the seed-update autopilot task-state file only when persistence
  is enabled and a run was copied back into the corpus.

### Phase 5: Update docs and tests

- [x] Update `specs/devtools.md` to describe the pipeline as an application
  inference entrypoint.
- [x] Update any handover or architecture docs that still frame the flow as
  seed maintenance only, especially the benchmark review-chain and
  reviewer-manifest docs.
- [x] Add regression coverage for fan-out, resume, the internal job graph,
  optional persistence, and compatibility mode.
- [x] Add regression coverage that proves a non-persisting application run
  still executes the same worker loop, records the graph state, and writes
  a pipeline summary.
- [x] Document the `--run-until-stage` cutoff so a run can stop after a named
  downstream stage without changing the declarative graph.
- [ ] Add regression coverage that proves copy-back is blocked when
  validation or review fails, and that the compatibility mirror is not
  refreshed in that case.
- [x] Add regression coverage that proves the canonical pipeline entrypoint
  can wire the full benchmark graph before any engineer stages are
  promoted.

### Phase 6: Lock the stateful graph and gated sink semantics

- [x] Treat the application inference pipeline as a stateful job graph with
  first-class persisted transitions, not as a one-shot batch runner.
- [x] Model `queued`, `running`, `validated`, `reviewed`, `persisted`,
  `skipped`, `failed`, and `interrupted` as explicit job states in the
  persisted pipeline state.
- [x] Derive downstream queue entries from the config-driven graph and the
  persisted resume state rather than recomputing them from seed rows alone.
- [x] Copy benchmark results back into `engineer_planner` only after the
  normal validation and review gates have passed.
- [x] Treat benchmark reviewer output as the canonical persisted bundle.
- [x] Allow benchmark coder output to persist only when the review document is
  intentionally omitted from an otherwise validated and reviewed bundle.
- [x] Refresh `logs/evals/seed_update_autopilot/task_state.json` only after a
  successful copy-back into the corpus.

## Non-Goals

- Do not change the agent prompts, worker semantics, or validation criteria.
- Do not introduce new agent roles or a new solver model.
- Do not require seed persistence for every inference job.
- Do not remove the current quick-prototype seed-autopilot path.
- Do not broaden the pipeline into an unrelated queueing system or database
  service.
- Do not turn the pipeline into a custom derivation engine that bypasses the
  existing agent execution flow.

## Sequencing

The safe order is:

1. Extend `InferencePipelineConfig` and `InferenceJobRequest` so the stage
   graph, mode, workspace source, and persistence intent are explicit.
2. Replace the `dataset/evals/eval_inference_pipeline.py` hardcoded
   `engineer_planner` / `seed_worker` path with stage registry dispatch.
3. Add the benchmark plan-review and benchmark execution-review stage rows and
   wire their executor adapters.
4. Add the optional eval-seed persistence sink and compatibility mirror write
   path.
5. Persist job progression and resume state.
6. Update docs and compatibility wrappers.
7. Add regression coverage for persisted and non-persisted runs.

## Acceptance Criteria

1. The application exposes a formal inference entrypoint with a documented job
   contract, internal state graph, and stage executor registry.
2. The entrypoint spawns the same agents as the current seed flow and uses the
   same validation/review gates.
3. `inference_config.yaml` drives downstream fan-out, persistence policy, and
   the benchmark reviewer chain.
4. Seed persistence is optional and explicit, and only validated/reviewed
   outputs are eligible for copy-back.
5. Progression and resume state are persisted at the job level.
6. The existing seed-autopilot path remains available as compatibility
   plumbing.
7. The docs describe the pipeline as an application feature rather than only
   as seed maintenance.
8. The first release wires `benchmark_planner`, `benchmark_plan_reviewer`,
   `benchmark_coder`, and `benchmark_reviewer` before any engineer stages are
   treated as part of the executable pipeline.

## File-Level Change Set

The implementation should touch the smallest set of files that establish the
new application contract:

- `inference_config.yaml`
- `evals/logic/inference_pipeline.py`
- `dataset/evals/eval_inference_pipeline.py`
- `dataset/evals/eval_seed_update_autopilot_per_seed.py` only as the source for
  extracting shared helpers, not as a runtime dependency
- `dataset/evals/eval_seed_update_autopilot.py`
- `dataset/evals/materialize_seed_workspace.py`
- `dataset/evals/run_e2e_seed.py`
- `scripts/internal/eval_seed_selection.py`
- `shared/eval_artifacts.py`
- `evals/logic/runner.py`
- `evals/logic/runner_execution.py`
- `specs/devtools.md`
- `specs/architecture/agents/handover-contracts.md`
- `tests/integration/architecture_p0/test_inference_pipeline.py`
- `tests/integration/architecture_p1/test_benchmark_workflow.py`
- `tests/integration/architecture_p1/test_handover.py`
