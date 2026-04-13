# Agent harness

## Scope summary

- Primary focus: the runtime harness for agent workflows, including the prompt/workspace contract, submission helpers, and debug CLI-provider mode.
- Defines the DSPy/LangGraph/LangFuse runtime shape, backend selection, and local eval-debug behavior.
- Covers agent memory, journal/review artifacts, and the runtime contract that feeds the prompt and workspace.
- Use this file for anything that changes how an agent starts, runs, or submits in the workspace.

## Runtime model

We use DSPy.ReAct as the primary agent runtime and LangGraph to manage agent orchestration. LangFuse is used for observability.

The controller can run either:

1. an API-backed model path, or
2. a CLI-provider-backed local workspace path.

The local CLI-provider path is the default eval-debug backend, and the controller-backed API path remains available when a run must use a paid API provider or needs controller-specific orchestration traces. The provider contract owns command shape, prompt transport, and resume syntax; the CLI binary name is not the contract.

## DSPy adapter contract

Adapter choice is an explicit runtime contract:

1. Preferred/default adapter is `dspy.ChatAdapter`.
2. `ChatAdapter` is preferred over `JSONAdapter` for ReAct-style agent nodes because it is the baseline behavior in this dependency/runtime stack and is the most stable path for mixed reasoning + tool-call trajectories.
3. `JSONAdapter` is exception-only and must be justified by a node-specific structured-output requirement that cannot be met by normal typed parsing/validation after model output.
4. Do not silently swap adapters per request. Adapter overrides must be explicit in code/config and visible in observability metadata.
5. Fail closed if adapter selection is invalid or unsupported for a node.

## Debug CLI-provider mode

The debug CLI-provider mode exists to reduce the cost of repeated eval iteration.

It is a local CLI-provider-backed backend for eval debugging and repeated agent runs. It is an application mode, not a new benchmark graph and not a replacement for the controller-backed runtime.

The conceptual split is:

1. `controller` is the orchestration layer and remains the same application responsibility.
2. The LLM/tool substrate can be either API-backed or CLI-provider-backed.
3. Judge and reviewer logic can run against the same deterministic workspace artifacts in CLI-provider mode when the local contracts are satisfied.

## Backend selection

The runner exposes the execution mode as an explicit choice:

1. The configured CLI provider launches a local workspace and runs the task there.
2. `controller` uses the existing HTTP orchestration path and paid model providers.
3. The local CLI-provider path is the default backend.
4. The controller-vs-local execution mode can be selected through `--call-paid-api`, `--runner-backend`, or `EVAL_RUNNER_BACKEND`.
5. `--call-paid-api` flips the runner to the paid-provider/controller path; `--runner-backend` remains the explicit controller-vs-local override. Multi-backend local tools may also expose `--provider` as a separate selector.
6. Role-specific `reasoning_effort` comes from `config/agents_config.yaml`, and the same config file can disable emitting that request parameter for backends or models that do not support it.

## Workspace materialization

The CLI-provider backend materializes a run-local workspace before the agent starts.

The materialized workspace is the source of truth for the session, not the repository root.

The workspace contract is:

01. The workspace root is the current directory for the local CLI-provider process.
02. The initial prompt is written to `prompt.md` at the workspace root.
03. Shared boilerplate starter files and prompt-context material come from `shared/agent_templates/`.
04. Role-specific planner starter files come from the role template repositories under `shared/assets/template_repos/`.
05. Planner workspaces include the role-scoped submission helper from `shared/agent_templates/codex/`: `scripts/submit_benchmark_plan.sh` for benchmark planners and `scripts/submit_engineering_plan.sh` for engineering planners.
06. Coder workspaces include the role-scoped review submission helper from `shared/agent_templates/codex/`: `scripts/submit_benchmark_for_review.sh` for benchmark coders and `scripts/submit_solution_for_review.sh` for engineering coders.
07. Reviewer workspaces include `scripts/submit_review.sh` from `shared/agent_templates/codex/`.
08. Benchmark planner workspaces do not receive `benchmark_script.py`. Benchmark coder and benchmark reviewer workspaces copy `benchmark_script.py` as read-only geometry context after plan approval, and engineer workspaces copy `solution_script.py` as the authored implementation source. Runtime-owned wrappers remain separate from both.
09. Seed-row artifacts are copied into the workspace before prompt generation.
10. The backend writes `.manifests/current_role.json` with the active role before the prompt is rendered and refreshes it whenever the workspace enters a new node.
11. Shared starter templates also include `.admin/clear_env.py`, a local helper that performs a destructive full workspace reset and re-materializes the same seeded row in place; use it only when you intentionally want to discard the current workspace and restart from the seed.
12. The materialized workspace remains local to the run and is not promoted into a canonical shared root.

The workspace materializer in `dataset/evals/materialize_seed_workspace.py` is the inspection helper for this same workspace contract.

## Prompt contract

The prompt is a contract, not a free-form suggestion.

It must describe the workspace in relative-path terms and must not teach the agent to address the filesystem as `/workspace`.

The canonical prompt rules are:

01. The prompt says `Workspace: current directory`.
02. The prompt tells the agent to use workspace-relative paths only.
03. The prompt does not mention `/workspace` as the workspace root.
04. Planner prompts instruct the role-scoped submission command (`bash scripts/submit_benchmark_plan.sh` or `bash scripts/submit_engineering_plan.sh`) as appropriate for the active planner role.
05. Benchmark planner prompts do not include `benchmark_script.py`; that file is introduced only after benchmark plan approval. Coder prompts instruct editing the role-owned authored source file (`solution_script.py` for engineering roles, `benchmark_script.py` for benchmark coder roles) and supporting `*.py` files, then either running `bash scripts/submit_benchmark_for_review.sh` / `bash scripts/submit_solution_for_review.sh` or using the matching Python submission utility from `utils.submission` in a supporting script. In that route, `validate_benchmark()` / `simulate_benchmark()` or `validate_engineering()` / `simulate_engineering()` are intermediate checks before `submit_benchmark_for_review()` / `submit_solution_for_review()`, and benchmark simulation is a stability/evidence pass rather than a goal-reaching pass.
06. Reviewer prompts instruct writing stage-specific review artifacts under `reviews/`, then running `bash scripts/submit_review.sh`.
07. The prompt may advertise `python .admin/clear_env.py` as an explicit full-reset helper, but normal validation/simulation reruns should overwrite their own outputs and do not require clearing the workspace.
08. The prompt includes the task text, agent name, task ID, and seed dataset name when available.
09. The prompt does not need to describe repository-level import paths or module layout.
10. When bug-report mode is enabled, the prompt tells the role to write `bug_report.md` only for infrastructure, harness, workspace materialization, prompt transport, filesystem policy, render plumbing, eval orchestration, or other runtime blockers, and to keep working by default after the report is filed.
11. All starter, non-DSPy-optimized prompt fragments live in `config/prompts.yaml` and `shared/agent_templates/`; see [prompt-management.md](./prompt-management.md) for the unified prompt-source model and [agent-skill.md](./agent-skill.md) for the skill-tree contract.
    PromptManager is the canonical merge point for that prompt text; runtime code such as `evals/logic/codex_workspace.py` only supplies runtime context or template variables.

## Role behavior

Planner roles are the only roles that use the local planner submission helper.

Planner behavior is:

1. Edit the planner-owned workspace files for the current stage.
2. Keep the workspace relative-path contract intact.
3. Run the role-scoped planner submission helper from the materialized workspace (`bash scripts/submit_benchmark_plan.sh` for benchmark planners, `bash scripts/submit_engineering_plan.sh` for engineering planners).
4. Iterate until the helper reports `ok=true` and `status=submitted`.
5. Treat `.manifests/` as system-owned output, not as editable planner input.

Coder roles use the same CLI-provider workspace contract, but they do not submit plans through the planner helper.
The prompt tells them to work in the role-owned authored source file, supporting implementation files, and the local execution-review helper (`bash scripts/submit_benchmark_for_review.sh` or `bash scripts/submit_solution_for_review.sh`).

Reviewer roles operate on the same workspace but write review artifacts instead of planner output.
The CLI-provider prompt must direct reviewers to the stage-specific `reviews/` files and must not ask them to rewrite planner-owned source files.

## Filesystem contract

The CLI-provider backend must follow the same filesystem rules as the rest of the runtime.
Path handling is fail closed.

The filesystem rules are:

1. Workspace-relative paths are canonical.
2. `/workspace` is only a compatibility alias in runtime plumbing.
3. Prompt text must not expand the alias into the canonical contract.
4. Path traversal outside the workspace root is a deterministic error.
5. The local CLI-provider client and the shared filesystem backend both resolve paths by containment against the resolved workspace root.
6. String-prefix checks are not sufficient and are not accepted as the path-safety rule.

The local containment checks live in `evals/logic/codex_workspace.py`.
The shared backend uses the same rule in `shared/workers/filesystem/backend.py`.

## Submission contract

Planner submission is explicit and local in CLI-provider mode.
The agent does not call the controller to submit the handoff.

The submission contract is:

1. The helper validates the required planner files for the active agent role.
2. Benchmark planner submissions canonicalize benchmark constraints before validation.
3. The helper reads `.manifests/current_role.json` and does not infer the planner variant from workspace files or `AGENT_NAME`, so the local launch environment stays generic.
4. A successful submission writes the stage manifest to `.manifests/`.
5. The helper returns structured `PlannerSubmissionResult` JSON on stdout.
6. Success requires `ok=true` and `status=submitted`.
7. Failure remains local to the workspace and does not masquerade as an accepted handoff.
8. Every submission attempt snapshots the workspace in git after the helper finishes when the attempt changed substantive workspace files; clean no-op attempts and runtime scratch-only changes do not force a commit.

The helper script is intentionally simple: it is a local shell/Python command, not a controller API.

## Skill source contract

The skill-tree contract is owned by [agent-skill.md](./agent-skill.md).

The harness only needs the runtime-facing summary:

1. The checked-in `.agents/skills/` tree is the canonical skill source.
2. CLI-provider workspaces read the checked-in `.agents/skills/` tree directly from the run-local workspace checkout.
3. Controller-backed runtime surfaces expose the same content through the `/skills` mount.
4. `suggested_skills/` may be materialized as a writable session-local worktree/checkpoint seeded from the approved `.agents/skills/` tree for skill-training runs.
5. The training loop resolves that overlay first when it exists; canonical `.agents/skills/` remains the published source of truth.
6. Workspace skill copies are read-only runtime inputs from the agent's perspective.

The harness does not own the skill improvement loop, the skill catalog shape, or the promotion policy.

## Agent memory and review artifacts

Agents keep structured runtime memory in `journal.md`, task progress in `todo.md`, and reviewer outputs in `reviews/**`.
When bug-report mode is enabled, `bug_report.md` is a separate workspace-root debug artifact for runtime blockers, not a substitute for `journal.md`, `plan_refusal.md`, or review artifacts.
Those same artifacts are retained as downstream training material, together with prompt snapshots, validation/simulation outputs, render bundles, the local `logs/skill_loop/events.jsonl` sidecar, and the workspace-local skill-loop snapshot files under `logs/skill_loop/`.

Rules:

1. `journal.md` is the episodic memory for the run.
2. `todo.md` is a writable execution plan/progress artifact.
3. `plan_refusal.md` is only created when a coder refuses a planner handoff.
4. Reviewer outputs are stage-scoped YAML pairs and the decision YAML is the routing source of truth.
5. Token compression is configured by `config/agents_config.yaml` and keeps canonical context telemetry available for compaction.
6. Feedback from simulation, cost checks, and manufacturability checks is recorded in markdown for downstream debugging and skill learning.
7. CLI-provider self-improvement runs persist a local `logs/skill_loop/events.jsonl` sidecar so self-reflection text and follow-up skill-update output remain available for later diagnostics, and the runner promotes those structured records into DB traces when an episode-backed path exists.
8. The eval launcher should stay thin; the shared orchestration core in `evals/logic/runner.py` should be split into smaller reusable modules, and a separate `train_skills.py`-style CLI owns the standalone replay/training loop over the retained bundle when skill training is enabled.

## Runner behavior

The runner behavior for CLI-provider mode is:

1. Materialize the workspace for the selected eval row.
2. Launch the configured CLI provider in that workspace with the prompt text.
3. Verify the workspace locally after the provider exits.
4. Optionally run local judge/reviewer passes against the same workspace artifacts when the run requests judge/reviewer mode and the local stage contracts are satisfied. Judge/reviewer sessions are fresh sessions for the reviewer role; they do not inherit the originating coder session.
5. If a failed eval is routed back to the originating agent for another attempt, the runner resumes the prior CLI-provider session and workspace context instead of launching a fresh one. If imported trace capture is unavailable, the runner falls back to the primary session id for that attempt rather than dropping the retained context. Explicit reset helpers are the only path that discard that retained context.
6. Persist session metadata including workspace path, launch return code, verification result, judge/reviewer outcomes when run, and failure reason, then promote queryable observability events into the controller DB when an episode-backed path is available.
7. Fail closed if the local CLI provider is missing or the workspace verification fails.
8. Controller-backed eval runs apply the `eval` stack profile so the eval bootstrap does not tear down or probe the integration stack, the profile skips the frontend dev server because evals do not need it, and the render path still uses the containerized `worker-renderer` service rather than a host-launched Xvfb fallback.
9. Long-running controller-backed eval runs emit the audible reminder `eval setup running` every five minutes until the run exits.

The runner does not require controller/worker orchestration for the agent loop in CLI-provider mode.
The controller-backed preflight and health checks remain part of the paid-provider/controller path only.
The standalone skill-training replay is not the eval launcher’s job; it consumes the retained episode bundle through a separate training entrypoint and may reuse the same session id when one is present.

## Observability

CLI-provider mode emits two observability layers:

1. Raw run artifacts:
   - the CLI session stream under the configured provider home sessions directory
   - the run-local `logs/skill_loop/events.jsonl` sidecar
   - any derived transcript artifacts rendered from those sources
2. Queryable DB traces:
   - structured records promoted into the controller database as `TraceType.EVENT`
   - the DB is the source of truth for later filtering, counting, and cross-run joins

The recorded fields include:

01. `agent_name`
02. `task_id`
03. `session_id`
04. `workspace_dir`
05. `prompt_path`
06. `runner_backend`
07. `launch_return_code`
08. `verification_name`
09. `verification_errors`
10. `verification_details`
11. `failure_reason`

The promotion contract is:

1. Every promoted event must carry `episode_id`, `user_session_id` when available, and a backend/source marker that distinguishes controller-backed runs from CLI-provider-backed runs.
2. The backend/source marker may live in existing JSON metadata for the first pass; a dedicated column is only required if query performance or indexing later justify a migration.
3. Validation and failure families are emitted as individual event rows, not collapsed into a single summary blob, so queries can count validation failures directly.
4. The primary CLI-provider-side structured event families for this path are `submission_validation`, `node_entry_validation_failed`, `logic_failure`, `lint_failure_code`, `lint_failure_docs`, `simulation_instability`, `review_decision`, `excessive_dof_detected`, `skill_self_reflection`, and `skill_update`.
5. The raw session stream under the configured provider home sessions directory remains the replay/debug source; the DB trace stream is the queryable index.

## Validation contract

The accepted CLI-provider-mode behavior is defined by integration coverage, not by unit-only checks.

The current validation contract is:

1. `run_evals --help` exposes the smoke-test defaults (`benchmark_planner`, `--limit 1`, `--concurrency 1`) and the paid-provider `--call-paid-api` handle.
2. Materialized planner workspaces contain the relative-path prompt contract.
3. Materialized planner workspaces do not contain `/workspace` in the prompt text.
4. Planner submission succeeds from the local workspace helper.
5. Path traversal outside the workspace root is rejected.
6. The CLI-provider launcher uses the native `workspace-write` sandbox with the legacy landlock backend, an isolated provider home seeded with the active auth bundle and a minimal generated `config.toml`, and a `PYTHONPATH` that prefers the materialized workspace while still appending the repo root so shared repo modules import correctly during local execution.
7. CLI-provider judge/reviewer mode can run locally from the same workspace artifacts when requested.
8. The controller backend still executes tasks after its preflight step.

The integration test file that exercises this contract is `tests/integration/architecture_p0/test_codex_runner_mode.py`.

## Non-goals

This mode does not create a new agent graph.
It does not replace the controller-backed production path.
It does not change the controller's orchestration responsibility.
