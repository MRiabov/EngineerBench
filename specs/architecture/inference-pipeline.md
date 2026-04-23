# Inference Pipeline

## Scope Summary

The application inference pipeline is the canonical stage-driven entrypoint for benchmark generation, benchmark review, and compatibility seed backfill. It owns stage selection, fan-out, job-state persistence, resume behavior, and optional copy-back into seed storage.

The pipeline reuses the existing seed-worker execution loop and the existing validation and review helpers. It does not introduce a new solver path, a new prompt contract, or a new reviewer rubric.

This file is the source of truth for the pipeline contract. `specs/devtools.md` is the operator-facing summary, and `specs/architecture/agents/handover-contracts.md` owns the review-manifest and handoff artifact names.

## Canonical Surfaces

- `dataset/evals/eval_inference_pipeline.py`
- `evals/logic/inference_pipeline.py`
- `inference_config.yaml`
- `logs/evals/inference_pipeline/`
- `logs/evals/seed_update_autopilot/task_state.json`

The application entrypoint is a pipeline wrapper around the existing seeded workspace workflow. The pipeline state is not derived from prompt text or log filenames; it is derived from the typed config and the persisted job-state file.

## Data Flow

```text
seed row / artifact bundle
  -> stage selection
  -> isolated workspace
  -> CLI provider worker
  -> role-scoped validation
  -> optional copy-back
  -> job state + run summary
  -> downstream job fan-out
```

The graph is internal to the pipeline. Persistence to the seed corpus is an optional sink on top of that graph, not the graph itself.

## Config Contract

`inference_config.yaml` is parsed into the strict `InferencePipelineConfig` model in `evals/logic/inference_pipeline.py`. The schema uses `extra=forbid`; unknown keys fail closed.

The current top-level contract is:

| Field | Current value | Contract effect |
| -- | -- | -- |
| `pipeline_name` | `application_inference` | Names the run family and the summary payload. |
| `version` | `1` | Versions the pipeline contract explicitly. |
| `mode` | `application` | Marks the checked-in operating mode. |
| `entry_stage_name` | `benchmark_planner` | Declares the default start stage. |

The remaining top-level fields are `stages`, `worker_hints`, `retry_policy`, `resume_policy`, and `deduplication`.

The current top-level worker hints are:

- `seed_workers = 4`
- `author_retries = 1`

The current policy objects are:

- `retry_policy.max_attempts_per_job = 2`
- `retry_policy.retry_failed_validation = true`
- `retry_policy.retry_failed_review = true`
- `resume_policy.checkpoint_on = validated, reviewed, persisted, failed`
- `deduplication.skip_existing_clean_rows = true`
- `deduplication.skip_existing_repaired_rows = false`
- `deduplication.skip_existing_outputs = false`

The pipeline models reserve the modes `application`, `eval_seed_backfill`, and `compatibility_seed_autopilot`, but the checked-in config runs in `application` mode.

## Hint Resolution

The pipeline resolves execution hints by precedence. The order is CLI flag, then stage hints, then pipeline hints, then hardcoded default.

The resolved hints include:

- `seed_workers`
- `author_retries`
- `queue`
- `skip_env_up`
- `validation_scope`
- `update_manifests`

`persist_results` follows the same pattern, except the stage's `persist_back_to_seed` value acts as the default when the CLI does not override it.

## Stage Graph

The current graph is explicit and declarative. Stage names must be unique, every downstream stage must resolve to a declared stage, and the entry stage must exist in the stage list.

| Stage | Agent | Outputs per success | Persist back to seed | Executor | Notes |
| -- | -- | -- | -- | -- | -- |
| `benchmark_planner` | `benchmark_planner` | 3 | false | `seed_worker` | Default entry stage. |
| `benchmark_plan_reviewer` | `benchmark_plan_reviewer` | 1 | false | `seed_worker` | Benchmark plan approval gate. |
| `benchmark_coder` | `benchmark_coder` | 2 | false | `seed_worker` | Benchmark implementation stage. |
| `benchmark_reviewer` | `benchmark_reviewer` | 1 | true | `seed_worker` | Canonical benchmark persistence sink. |
| `engineer_planner` | `engineer_planner` | 1 | true | `seed_worker` | Compatibility sink for seed storage. |
| `engineer_coder` | `engineer_coder` | 1 | true | `planned` | Declared only until a real adapter is wired. |

The current downstream edges are:

- `benchmark_planner -> benchmark_plan_reviewer`
- `benchmark_plan_reviewer -> benchmark_coder`
- `benchmark_coder -> benchmark_reviewer`
- `benchmark_reviewer -> engineer_planner`
- `engineer_planner -> engineer_coder`

Each success queues downstream jobs with the deterministic id format `source_job_id->downstream_stage#NN`. The queued job count is driven by `outputs_per_success`, not by prompt text or ad hoc worker behavior.

## Typed Job Model

The pipeline models are strict Pydantic objects. They reject unknown fields and do not accept open-ended extra keys unless a field is intentionally modeled as a map.

| Model | Purpose | Key fields |
| -- | -- | -- |
| `InferenceWorkspaceSource` | Declares where a job workspace comes from. | `source_type`, `task_id`, `seed_artifact_dir`, `upstream_job_id`, `notes` |
| `InferenceJobRequest` | Describes a runnable job. | `job_id`, `stage_name`, `mode`, `workspace_source`, `persist_results`, `resume_token`, `metadata` |
| `InferenceJobResult` | Captures the outcome of one job run. | `status`, `task_id`, `workspace_dir`, `run_dir`, `copied_back`, `validation_passed`, `review_passed`, `bundle_fingerprint`, `failure_reason`, `output_job_ids` |
| `InferenceJobState` | Persists the resume and dedup state. | `status`, `bundle_fingerprint`, `last_validation_passed`, `last_review_passed`, `source_run_started_at`, `source_run_finished_at`, `recorded_at` |
| `InferenceRunSummary` | Captures the run-local summary. | `selected_job_ids`, `skipped_job_ids`, `queued_job_ids`, `completed_job_ids`, `failed_job_ids`, `persisted_job_ids`, `jobs`, `success` |

The supported workspace source types are `seed_row`, `artifact_dir`, `derived_job`, and `bundle`.

The current CLI path selects seed rows from the role-based seed datasets. The other source types exist so shared helpers and future callers can express artifact-backed and derived jobs without changing the root contract.

`job_id` is stage-scoped and deterministic:

```text
job_id = <stage_name>:<task_id>
downstream_job_id = <job_id>-><downstream_stage>#<NN>
```

## Selection and Resume Rules

- Stage selection reads the role-based seed datasets under `dataset/data/seed/role_based/<agent>.json`.
- `--task-id`, `--family`, `--level`, and `--limit` filter the candidate set before execution.
- `--family` only applies when the selected stage agent is `engineer_planner`.
- If no stage is passed, the pipeline starts at `entry_stage_name`.
- `--resume-token` trims the candidate list at the matching job id and fails closed if the token does not match a candidate.
- The summary records both the input `resume_token` and the next resume cursor.
- Terminal states `validated`, `reviewed`, `persisted`, and `skipped` are not retryable.
- Retryable states are `queued`, `running`, `failed`, and `interrupted`.
- For `engineer_planner`, the current compatibility mirror is consulted so already clean rows do not rerun when the bundle fingerprint and the last validation and review flags still match.

Resume is a selection policy, not an execution shortcut. The persisted job-state file remains the authoritative resume surface across runs.

## Execution Flow

01. Load the config and the current job-state file.
02. Resolve the selected stage and validate the requested downstream cutoff, if any.
03. Resolve worker hints by precedence: CLI flag, then stage hints, then pipeline hints, then hardcoded default.
04. Build the run summary and the per-job request list.
05. Write queued job state before dispatch so a crash does not erase progress.
06. Run the selected stage batch with the wired executor.
07. Materialize a workspace, launch the provider session, and verify the workspace with the role-scoped validation helper.
08. Copy back only when persistence is enabled and the run is not in validate-only mode.
09. Refresh manifests and the compatibility mirror only after a successful copy-back.
10. Queue downstream job states from the declared graph and write the updated state file.
11. Drain downstream stages in graph order until the declared cutoff or the first declared-only stage.

The runtime is concurrent within a stage. The resolved `seed_workers` value bounds the thread pool that executes the selected jobs for that stage.

The pipeline supports a dry-run mode. In dry-run mode it writes the summary and planned fan-out, but it does not launch the worker loop or copy back any artifacts.

## Persistence And Copy-Back

Persistence is an explicit pipeline-level decision. The `persist_results` flag defaults to the selected stage's `persist_back_to_seed` value unless the caller overrides it.

- `--validate-only` suppresses copy-back even when persistence is enabled.
- `persist_results = false` means the run records validation and review results but does not write back to the seed corpus.
- `persist_results = true` means the run may copy back validated outputs when the normal validation and review gates pass.

The success status reported by `InferenceJobResult` reflects that distinction:

- `validated` means validation passed and the run stopped before review.
- `reviewed` means validation and review passed, but copy-back did not occur.
- `persisted` means the bundle passed validation and review and the copy-back succeeded.

The benchmark reviewer output is the canonical persisted benchmark bundle. The benchmark coder output is eligible for copy-back only when it corresponds to a validated and reviewed bundle whose review document is intentionally omitted from the persisted copy.

The persistence target depends on the stage:

- Benchmark stages copy into `dataset/data/seed/artifacts/engineer_planner/<task_id>`.
- `engineer_planner` copies into its own seed-artifact directory when used as the compatibility maintenance sink.

The copy-back path applies the seed artifact manifest refresh helper after the files are copied. The `update_manifests` flag only controls that refresh step; it does not change whether the job was validated or reviewed.

When copy-back succeeds into engineer seed storage, the compatibility mirror at `logs/evals/seed_update_autopilot/task_state.json` is refreshed with:

- `task_id`
- `bundle_fingerprint`
- `last_validation_passed`
- `last_review_passed`
- `source_run_started_at`
- `source_run_finished_at`
- `recorded_at`

The compatibility mirror is a derived cache, not the authoritative resume state.

## Run State Surfaces

- `logs/evals/inference_pipeline/task_state.json` is the authoritative resume and dedup file for the application pipeline.
- `logs/evals/inference_pipeline/current` points to the latest run directory.
- `logs/evals/inference_pipeline/runs/run_<timestamp>_<pipeline_name>/` stores each run's artifacts.
- `inference_pipeline_summary.json` is the per-run summary payload.
- `logs/evals/seed_update_autopilot/task_state.json` mirrors only the compatibility backfill state after a successful copy-back.

The state file is keyed by job id. It is updated incrementally so a crash between jobs does not erase already recorded progress.

## Job Lifecycle And Summary Semantics

- A job enters `queued` state before dispatch and `running` state just before execution.
- Successful jobs end in `validated`, `reviewed`, or `persisted`.
- `validated` means the run stopped after deterministic validation.
- `reviewed` means the run passed validation and review but did not copy back.
- `persisted` means the copy-back succeeded.
- `failed` records a hard failure with a reason string.
- `skipped` records a deliberate omission and remains terminal for dedup.
- `interrupted` is reserved for in-flight work that did not complete cleanly.
- `summary.completed_job_ids` includes every successful job, including persisted jobs.
- `summary.persisted_job_ids` is a subset of `summary.completed_job_ids`.
- `summary.next_resume_token` is the final job id processed in the run when one exists, otherwise it matches the input resume token.
- `summary.success` is true only when the run finished without failures.

The run summary is a run-local report. The persisted job-state file is the cross-run source of truth.

## Executor Semantics

The wired `seed_worker` executor keeps the current worker loop intact:

- materialize a workspace
- launch the CLI provider
- verify the workspace with the role-scoped validator
- copy back only when the persistence policy allows it

The `planned` executor is declarative only. If it is selected directly, the runtime fails closed instead of inventing a fallback adapter.

The pipeline does not invoke `dataset/evals/eval_seed_update_autopilot_per_seed.py` as a runtime dependency. Any shared helper behavior must come from the library surface.

## Failure Rules

- Unknown stage names fail closed.
- Unknown downstream stage references fail closed at config load time.
- Duplicate stage names fail closed at config load time.
- Unknown executor names fail closed when the stage is selected.
- Stale resume tokens fail closed.
- Invalid `--limit`, `--seed-workers`, or `--author-retries` values fail closed.
- `--family` on a non-`engineer_planner` stage fails closed.
- `--run-until-stage` fails closed if the named stage is not reachable from the selected start stage.
- Missing config files fail closed.
- Declared-only stages do not become runnable just because they appear in the graph.
- Validation or review failure blocks copy-back and blocks compatibility mirror refresh.

The pipeline does not invent fallback stages, fallback executors, or fallback resume cursors.

## Operator Controls

The CLI contract is intentionally explicit:

- `--stage` selects the start stage.
- `--run-until-stage` limits downstream draining to a named reachable stage.
- `--persist-results` and `--no-persist-results` override the stage default.
- `--validate-only` forces a validation-only run.
- `--dry-run` emits the planned graph without executing it.
- `--resume-token` trims the current candidate set.
- `--queue` waits for the shared eval lock instead of failing fast.
- `--skip-env-up` assumes the eval stack is already running.
- `--validation-scope` forwards the validation scope to the role-scoped validator.
- `--update-manifests` controls post-copy manifest refresh.
- `--provider` selects the CLI provider used for the worker session.
- `--author` is required; the entrypoint is exposed only through the authoring path.

The current provider default is `codex`, with `qwen` available as an alternate provider.

## Relationship To Other Contracts

- `specs/architecture/agents/handover-contracts.md` defines the benchmark and engineering handoff artifacts, review manifests, and reviewer routing.
- `specs/architecture/evals-architecture.md` defines the broader eval and fail-closed policy.
- `specs/devtools.md` documents the developer-facing CLI wrapper and points at this pipeline contract.
- `specs/migrations/major/application-inference-pipeline-entrypoint.md` records the historical migration rationale for this contract.

The inference pipeline is orchestration around the existing agent graph. It is not a substitute for the role contracts, the reviewer contracts, or the benchmark handoff contracts.

## Non-Goals

- Do not define prompts or reviewer rubrics here.
- Do not move the stage gate definitions out of the handover contract.
- Do not turn the pipeline into a general queueing system or database service.
- Do not remove the seed-autopilot compatibility path.
- Do not add a new solver model or a new reasoning path.
- Do not make `engineer_coder` runnable before its executor adapter exists.

## Acceptance Criteria

1. The config is strict, versioned, and fails closed on unknown fields or unknown stage references.
2. The current benchmark chain runs in order from `benchmark_planner` through `benchmark_reviewer`.
3. `engineer_planner` remains the compatibility sink, and `engineer_coder` remains declared-only.
4. The pipeline keeps a separate resume state from the compatibility mirror.
5. Persistence is optional, explicit, and gated by validation and review results.
6. Resume and dedup behavior are deterministic from persisted state, not from ad hoc prompt text.
7. The docs point readers at this file as the canonical pipeline contract.
