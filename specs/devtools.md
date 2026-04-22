# Developer instrumentation

## Scope summary

- This file documents the developer-facing bootstrap, orchestration, validation, and artifact-regeneration surface that supports local development and eval/debug workflows.
- It is adjacent to, not a replacement for, `specs/architecture/**`.
- Use `specs/integration-test-rules.md` for integration-test boundary rules, `specs/architecture/evals-architecture.md` for eval semantics, and `specs/architecture/agents/agent-harness.md` for the workspace contract.
- The contract here is operational: how developers reproduce the stack, inspect seeded workspaces, run integration slices, and regenerate derived artifacts.

## Tooling principles

- Devtools are agent-facing by default. Keep default verbosity low, but when tools emit logs or summaries they should be dense and informative. Avoid chatty traces and large dumps; aim for roughly a few hundred tokens per invocation when practical, and treat a tool that routinely produces hundreds of lines as a smell because it wastes context and token budget.
- Devtools integrate with application logic where possible instead of reimplementing it in wrapper code. The preferred shape is a thin maintainer-facing utility that reuses shared runtime, validation, or seed logic, as in `scripts/validate_eval_seed.py`, `dataset/evals/run_evals.py`, and `scripts/validate_integration_mock_response_preflight.py`; the shared eval core lives in `evals/logic/runner.py` and should be split into smaller reusable modules rather than wrapped again.
- Compatibility shims are migration scaffolding, not a permanent layer. Do not stack a shim over another shim when a direct helper import or a single owning CLI module would do, and remove redundant wrappers once the call sites are updated.
- Before adding a new devtool, check for shared utilities and existing dependencies in the application code. Prefer extending those primitives over creating parallel scaffolding; the repo should maintain the application code, not a second code path around it, and fewer duplicated concepts reduce confusion for both developers and agents.

## Ownership model

The developer instrumentation layer is split into a small set of canonical entrypoints and a larger set of internal helpers.

| Layer | Canonical files | Responsibility | Stability |
| -- | -- | -- | -- |
| Local bootstrap | `scripts/env_up.sh`, `scripts/env_down.sh` | Bring the selected local stack profile up and down, including infra, app processes, and profile-scoped cleanup | Public and stable |
| Integration orchestration | `scripts/run_integration_tests.sh`, `scripts/internal/integration_runner.py` | Run the canonical integration suite through the real stack and the real HTTP/system boundaries | Public wrapper, internal implementation |
| Eval orchestration | `dataset/evals/run_evals.py`, `evals/logic/runner.py` (split into reusable helpers under `evals/logic/`), `dataset/evals/materialize_seed_workspace.py`, `dataset/evals/materialize_seed_authoring_workspace.py` | Run evals, materialize seeded workspaces, bootstrap seed-authoring workspaces, and expose the CLI-provider-backed debug path | Public wrapper plus internal implementation |
| Eval coordination | `scripts/internal/eval_run_lock.py`, `scripts/internal/eval_seed_renders.py` | Serialize eval runs and support deterministic seed render regeneration for maintainer tooling | Internal helper modules |
| Seed and fixture validation | `scripts/validate_eval_seed.py`, `scripts/update_eval_seed_renders.py`, `scripts/validate_integration_mock_response_preflight.py`, `scripts/normalize_integration_mock_responses.py` | Validate seeded eval rows against the current seeded-entry contract, including the seeded-validation scope contract, update deterministic seed render bundles, validate the legacy integration replay corpus, and repair deterministic drift in that corpus | Public maintenance utilities |
| Derived artifact regeneration | `scripts/persist_test_results.py` | Persist test-history outputs | Public utilities |
| Bug-report archival | `scripts/persist_bug_reports.py` | Copy `bug_report.md` into `logs/bug_reports/` with run/session metadata | Public utility |
| Compatibility and environment helpers | `scripts/ensure_docker_vfs.sh`, `scripts/cleanup_local_s3.py` | Make the local stack runnable in constrained environments and clear object-store state before runs | Public support scripts |
| Experimental probes | `scripts/experiments/**` | Measure or compare runtime behavior without defining the stable contract | Non-contractual |

## Local bootstrap

`scripts/env_up.sh` and `scripts/env_down.sh` are the paired local-environment controls.

### `scripts/env_up.sh`

- `scripts/env_up.sh` is the canonical local bootstrap command.
- The default profile is `integration`; `--profile eval` switches to the eval stack profile.
- The script loads `.env` when present, exports the selected profile, and reuses the shared stack-profile helper from `evals.logic.stack_profiles`.
- It stops the selected profile first, then starts infra and application services.
- It starts the containerized infra stack from `docker-compose.test.yaml`, ensures migrations are at Alembic head, launches the local controller and workers, and starts the renderer in Docker. The migration step skips the upgrade when the database is already current unless `--force-run-alembic` is passed.
- It performs local compatibility setup before bootstrapping services, including Docker VFS readiness checks.

### `scripts/env_down.sh`

- `scripts/env_down.sh` is the canonical teardown command for the selected profile.
- It reads the same profile selection as `env_up.sh` and stops only the processes and containers associated with that profile.
- It removes the saved PID files for host processes and stops the renderer container explicitly.
- It tears down the infra stack with `docker compose down -v --remove-orphans`.
- It clears root log symlinks when the stack is configured to create them.

### Local bootstrap support scripts

- `scripts/ensure_docker_vfs.sh` exists to keep Docker usable in environments where the default storage driver is not reliable.
- `scripts/cleanup_local_s3.py` clears object-store state before a run so prior artifacts do not leak into the next session.

## Integration orchestration

The integration runner is a real-stack boundary contract, not a synthetic test harness.

### Severity classification

- Devtool integration tests should be classified as `p1` or `p2` priority by default; `p0` priority is reserved for exceptional cases only.

### Public entrypoint

- `scripts/run_integration_tests.sh` is the only supported public entrypoint for integration verification.
- The shell wrapper sets the integration defaults and then hands off to `scripts/internal/integration_runner.py`.
- It keeps browser-fixture disabling, backend-error early stop, ordered marker slicing, and async cleanup as runner-level behavior rather than test-level improvisation.
- It accepts `--force-run-alembic` to force the schema upgrade step when a caller explicitly wants it.
- It should remain the human-facing command that other docs reference.

### Runner implementation

- `scripts/internal/integration_runner.py` owns lock acquisition, run-state persistence, service startup, health checks, log archiving, backend-error early stop, pytest execution, and cleanup.
- It treats the integration stack as a single serialized shared resource guarded by `/tmp/problemologist-integration.lock`.
- It records the requested run in `/tmp/problemologist-integration.run.json` so a blocked caller can decide whether to queue or reuse the active logs.
- It writes run logs under `logs/integration_tests/runs/run_*` and updates `logs/integration_tests/current/` to point at the active run.
- It keeps xdist enabled by default and only opts out when the caller explicitly requests a different pytest distribution mode.
- Its startup and teardown chatter is quiet by default; set `INTEGRATION_RUNNER_VERBOSE=1` when you want detailed orchestration progress in the terminal.
- It can split the default suite into deterministic marker buckets so P0/P1 coverage is reached before the broader slices.
- It performs backend-error early stop when enabled and only falls through to full-duration runs when the errors are allowlisted or the gate is disabled.

### Integration run state

The integration runner owns the following persistent surfaces:

- `/tmp/problemologist-integration.lock`
- `/tmp/problemologist-integration.run.json`
- `logs/integration_tests/current/`
- `logs/integration_tests/current/json/`
- `logs/integration_tests/runs/run_*`
- the compatibility symlinks under `logs/integration_tests/` and `logs/integration_tests/json/`
- `test_output/junit.xml`
- `test_output/junit_slices/`

### Integration rules carried by the scripts

- Integration traffic stays on the real HTTP/system boundary.
- Integration runs do not become unit tests with mocks dressed up as end-to-end coverage.
- The runner should fail closed on startup, lock contention, or backend errors rather than silently degrade to a weaker execution path.
- Simulation-heavy slices follow the backend-matrix rules from `specs/integration-test-rules.md`; the script layer is responsible for honoring the selected backend, not for inventing its own matrix.

## Eval orchestration

The eval tooling mirrors the integration tooling, but it owns a separate lock, a separate log tree, and family-scoped temp roots under `/tmp/problemologist-evals/<family>/` for ad hoc workspaces and run state.

### `dataset/evals/run_evals.py`

- `dataset/evals/run_evals.py` is a compatibility shim.
- Its only job is to add the repo root to `sys.path` and call `evals.logic.runner.run_cli()`.
- The file should stay thin so historical invocations remain valid without turning the shim into orchestration logic.

### `evals/logic/runner.py`

- `evals/logic/runner.py` is the real eval runner.
- It is the orchestration core that should be decomposed into smaller reusable modules under `evals/logic/` rather than expanding further as a single file.
- It owns backend selection, task filtering, complexity-level filtering, concurrency, rate limiting, and run logging.
- Its local CLI-provider backend must expose an explicit provider selector so Codex remains the default while other concrete providers such as `QwenCliProvider` can be selected without inferring the backend from the binary name.
- When `--open-cli-ui` is combined with concurrency greater than 1, each interactive launch opens in its own terminal window instead of reusing the current shell.
- It uses the eval run lock to protect the stack while bootstrapping and then runs as a shared consumer of the eval lock during execution.
- Controller-backed runs bootstrap exclusively only while `scripts/env_up.sh` is running, then downgrade to the shared lock for the actual eval loop.
- CLI-provider-backed runs and `--skip-env-up` runs join the shared eval lock directly.
- It records the active bootstrap owner in `/tmp/problemologist-evals/eval/problemologist-eval.run.json` and updates that state only while the lease is writable.
- It writes logs under `logs/evals/runs/run_*` and maintains `logs/evals/current/` plus `logs/evals/latest.log`.
- It can run against the controller-backed path or the local CLI-provider path.
- Devtools that can target more than one CLI backend must expose the choice explicitly, for example `--provider qwen` or an equivalent provider selector, rather than inferring the backend from the binary name. This is orthogonal to `--runner-backend`, which remains the controller-vs-local execution-mode switch.
- Controller-backed eval runs bootstrap the `eval` profile through `scripts/env_up.sh` unless the caller explicitly skips that step.
- `--skip-env-up` joins the shared eval lock directly so multiple eval consumers can coexist when the stack is already up.
- CLI-provider-backed eval runs remain local to the materialized workspace and do not require the controller/worker stack to be booted for the agent loop itself.

### `dataset/evals/materialize_seed_workspace.py`

- `dataset/evals/materialize_seed_workspace.py` is an inspection helper for a single seeded eval row.
- It materializes the row into a temp workspace under `/tmp/problemologist-evals/<agent>/`, writes the provider prompt to `prompt.md`, writes `.manifests/current_role.json` with the active role, and prints the copied file list for inspection.
- It is not the eval runner and should not be treated as the owner of the eval loop.
- It can optionally bootstrap the `eval` profile, launch the configured CLI provider, or open the interactive UI through that provider backend. The current supported concrete providers are Codex and `QwenCliProvider`.
- When `--provider` is omitted, the helper defaults to `qwen`; pass `--provider codex` to use the Codex backend explicitly.
- `--new-terminal` is a standalone-helper option that opens `--open-cli-ui` sessions in a separate terminal window when you run the materializer directly.
- It uses the exclusive eval lock while bootstrapping and then downgrades to the shared validation lock so multiple validation-only consumers can coexist while the stack remains protected.
- After bootstrap it stops mutating the lock state and keeps only the shared lock file handle open.
- It exposes explicit sandbox selection through `--yolo` and `--no-yolo`; the script should never invent a hidden bypass mode.
- The blank-slate seed-authoring helper lives in `dataset/evals/materialize_seed_authoring_workspace.py` and is tracked in [Seed Authoring Workspace Bootstrapper](./migrations/minor/seed-authoring-workspace-bootstrapper.md); it bootstraps a fresh authoring workspace instead of rehydrating an existing seed row and synchronizes the repository-local `.venv` into that workspace so the authoring agent can run workspace-local commands immediately.

### `dataset/evals/run_e2e_seed.py`

- `dataset/evals/run_e2e_seed.py` runs the benchmark-to-engineer smoke chain from a seeded prompt.
- When `--workspace-root` is omitted, it creates its workspace tree and resume checkpoint under `/tmp/problemologist-evals/e2e_seed/` so repeated runs stay grouped instead of scattering `mkdtemp()` outputs across `/tmp`.
- Resume checkpoints remain local to that workspace root, and explicit `--workspace-root` / `--resume-from-dir` arguments still take precedence when provided.

### `dataset/evals/eval_seed_update_autopilot.py`

- `dataset/evals/eval_seed_update_autopilot.py` is the reusable seed-update autopilot for eval rows.
- It runs engineer_planner seed jobs one row at a time with process-level concurrency: each worker owns one seed worktree, launches the authoring Codex CLI, refreshes the seed artifacts, runs `scripts/validate_eval_seed.py`, and then runs a read-only review prompt before the relevant workspace files are copied back.
- For new rows, the worker bootstraps the worktree through `dataset/evals/materialize_seed_authoring_workspace.py` before authoring starts, so the blank workspace and `.venv` are already in place when the model receives the prompt.
- The autopilot creates new rows and repairs broken existing rows: if a canonical `task_id` already exists in `dataset/data/seed/role_based/engineer_planner.json`, it is skipped when the persisted task-state record shows the current bundle fingerprint was already validated and reviewed cleanly, and it is requeued when the current `scripts/validate_eval_seed.py` check fails or the persisted task state is missing/stale.
- The persisted task-state file lives at `logs/evals/seed_update_autopilot/task_state.json`; successful copy-back runs refresh it with the task id, bundle fingerprint, and the last validation/review outcome, so later runs do not need to re-review unchanged clean rows.
- Its authoring and review prompts inline the row's task and expected criteria when available so the model can self-check exact role and label grounding before editing the workspace.
- It keeps its per-seed logs, prompts, and per-seed run summaries under `logs/evals/seed_update_autopilot/`, and the worker count is configurable so 2-4 Codex CLIs can be active at once on different seeds.
- The canonical entrypoint lives in `dataset/evals/eval_seed_update_autopilot.py`; the old family-batch idea is no longer the maintained contract.

### Eval coordination helpers

- `scripts/internal/eval_run_lock.py` is the shared lock/state helper for eval runs, and its default files live under `/tmp/problemologist-evals/eval/`.
- `scripts/internal/eval_seed_renders.py` supports deterministic regeneration of seed render bundles.
- These modules are implementation details and should stay under `scripts/internal/`.

### Eval run state

The eval runner owns the following persistent surfaces:

- `/tmp/problemologist-evals/eval/problemologist-eval.lock`
- `/tmp/problemologist-evals/eval/problemologist-eval.run.json`
- `logs/evals/current/`
- `logs/evals/runs/run_*`
- `logs/evals/latest.log`
- `logs/evals/current/sessions/`

The seeded-workspace helpers use the same `/tmp/problemologist-evals/` base but keep their workspace trees separated by family name so the top-level `/tmp` namespace stays uncluttered.

## Seed and fixture validation

The validation helpers are developer tooling, not product behavior.

### `scripts/validate_eval_seed.py`

- This script validates seeded eval entry contracts without running the full eval loop.
- It seeds the local workspace through the real helper path and validates the row against the current contract set.
- The seeded-validation depth contract is documented in [Seeded Eval Validation Scope Contract](./migrations/minor/seeded-eval-validation-scope-contract.md); `--validation-scope` selects `current-node`, `current-and-previous-nodes`, or `current-and-previous-nodes-with-heavy-simulation`, `current-and-previous-nodes` is the default, and unknown values fail closed.
- For role-based rows, that contract includes the current-role manifest as the authoritative role marker for the seeded workspace.
- For planner rows, that contract includes exact inventory preservation, exact identifier mention coverage in `benchmark_plan.md` or `engineering_plan.md`, and the latest handoff cross-contract checks from the controller validation path.
- `scripts/update_eval_seed_renders.py` continues to own deterministic render regeneration.
- It can refresh deterministic seed manifests when asked; render bundles are handled by `scripts/update_eval_seed_renders.py`.
- It can optionally run the eval runner in judge mode after validation.
- `--judge-provider` selects the CLI provider for that judge follow-up; the default is `qwen`, and the choice is orthogonal to `--runner-backend`.
- `--json` emits a trailing machine-readable summary payload so maintainer tooling can parse validation results without scraping the human-oriented logs.
- Validation-only `--skip-env-up` runs join the shared validation lock so multiple seed checks can proceed in parallel while still preventing eval teardown during an active validation consumer.
- The script keeps the lock exclusive only while bootstrapping the eval stack, then downgrades to the shared validation lock before health checks and validation work continue.
- If `--run-judge` is requested for more than 10 selected seed rows, the script requires `-y` before it will launch the expensive judge pass.
- Seeded eval corpora are template-free. The validator only inspects the stored seed corpus, while runtime workspace bootstrap materializes the engineer-planner starter scaffold before planner entry and the controller node-entry gate validates that scaffold there.
- It must fail closed when required seed-corpus artifacts are missing, malformed, or no longer match the expected stored-corpus contract.

### `scripts/update_eval_seed_renders.py`

- This script regenerates deterministic seed render bundles without running seed validation.
- It uses the same seeded-dataset selection filters as `scripts/validate_eval_seed.py` and the same deterministic render regeneration helper.
- It is the preferred maintainer-facing command for occasional render refreshes.
- It accepts `--skip-env-up` as a compatibility alias for eval-maintenance workflows, but it never bootstraps `env_up` and always joins the shared eval lock directly.

### `scripts/validate_integration_mock_response_preflight.py`

- This script validates `tests/integration/mock_responses/*.yaml` and the referenced payload files against real node-entry and handoff contracts.
- It replays scenario entries cumulatively rather than trusting a single fixture file in isolation.
- It is stricter than the fixture normalizer and should be treated as a contract gate, not a convenience parser.
- It validates the legacy replay corpus, not the canonical fixture-authoring surface.
- It is intentionally happy-path oriented for the current `INT-###` corpus and should not guess at future negative-test semantics.

### `scripts/normalize_integration_mock_responses.py`

- This utility rewrites deterministic derived fields in the legacy integration replay corpus.
- It is allowed to repair drift, but it should not alter scenario intent or narrative text.
- It is a consistency tool for checked-in compatibility material, not a benchmark for agent behavior.

### `scripts/pick_preview_pixel.py`

- This script resolves a screen-space pixel against a local render bundle and prints the ray-pick result as JSON.
- It is the maintainer-facing local equivalent of the worker render-query helper and is intended for eval creation, render inspection, and bundle-debug work against the checked-out workspace.
- It accepts an explicit workspace root so it can query bundles under the repo checkout or another materialized workspace without requiring a worker process.
- It should fail closed when the bundle path, manifest path, or bundle id do not match the resolved bundle snapshot.

## Derived outputs

These scripts own a few generated or persisted artifacts that should be treated as outputs, not hand-edited source.

### Test history persistence

- `scripts/persist_test_results.py` reads `test_output/junit.xml` and appends the parsed results to test history.
- It maintains the rolling history in `test_output/integration_test_history.json`.
- It archives older runs in `test_output/integration_test_archive.json`.
- It is post-run bookkeeping, not a substitute for the integration runner.

### Bug-report archival

- `scripts/persist_bug_reports.py` is the maintainer-facing helper for runtime blocker reports.
- It copies `bug_report.md` into a run-scoped archive tree under `logs/bug_reports/`.
- The archive manifest records the active role, session or episode identifiers when available, the workspace path, the archive path, and a content hash for the copied report.
- The helper is separate from `journal.md`, review YAML, and test-history persistence.

## Legacy and experimental helpers

- `scripts/run_agent.sh` is a legacy container wrapper and is not the canonical agent runtime path.
- `scripts/experiments/**` contains measurement and probe scripts for renderer behavior, simulation reuse, and related investigations.
- These files are useful when they are referenced by a contract or experiment, but they do not define stable production behavior by themselves.

## Edit rules

- Add new developer-facing entrypoints here when they become stable enough that other docs should route to them.
- Keep compatibility shims thin; move orchestration into the underlying Python module instead of growing the shell wrapper indefinitely.
- Keep internal helper modules under `scripts/internal/` unless they become public, documented entrypoints.
- Prefer fail-closed behavior over silent fallback for missing dependencies, missing artifacts, or missing locks.
- If a script starts owning a new persistent output path, document that path here in the same change.

## Non-goals

- This file does not replace the architecture docs.
- This file does not restate the product acceptance rules already covered by `specs/integration-test-rules.md` and `specs/architecture/**`.
- This file does not turn every ad hoc maintenance script into a stable contract; only the tooling that others are expected to use repeatedly belongs here.
