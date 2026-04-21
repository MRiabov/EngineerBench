---
name: agent-pipeline-debugging-workflow
description: Debug and fix agent-pipeline failures by reproducing with one agent and one task through `uv run dataset/evals/run_evals.py` or `uv run scripts/validate_eval_seed.py`, inspecting `logs/manual_run/`, `logs/evals/`, and integration backend-error logs, and applying root-cause fixes for deterministic validation, prompts, seed fixtures, or runtime-contract bugs aligned with `specs/desired_architecture.md`, `specs/architecture/evals-architecture.md`, `specs/devtools.md`, `specs/integration-test-rules.md`, `specs/integration-test-list.md`, and `specs/dataset-generation.md`. Invoke this skill when you need to fix eval regressions or seeded-entry contract failures.
---

# Agent Pipeline Debugging Workflow

Use this workflow to make failing agent evals pass with the smallest reproducible run.

Deterministic validation is not optional: if a value can be checked from structured inputs, validate it exactly on node entry and exit and hard-fail on mismatch.

## Contract hierarchy

Use these docs in order when deciding whether the failure is a seed bug, code bug, prompt bug, or architecture gap:

01. `specs/desired_architecture.md`
02. `specs/architecture/evals-architecture.md`
03. `specs/devtools.md`
04. `specs/integration-test-rules.md`
05. `specs/integration-test-list.md`
06. `specs/architecture/agents/agent-harness.md`
07. `specs/architecture/agents/prompt-management.md`
08. `specs/architecture/agents/agent-skill.md`
09. `specs/architecture/observability.md`
10. `specs/dataset-generation.md`
11. `specs/business-usecase.md`

If a row violates the current seeded-entry contract, fix the seed or fixture and validate it before spending more eval quota.

## Non-negotiable rules

01. Never debug with multiple agents (`--agent all` is forbidden for triage).
02. Always reproduce with one agent and one task first (`--task-id`, `--limit 1`, `--concurrency 1`).
    - `run_evals.py` now supports multi-ID `--task-id` input (repeated flags, CSV, bracket list), but use that only after first-seed triage.
    - `--random` with `--limit N` can help widen follow-up runs so they do not keep hitting only the first eval row.
03. Run evals through `uv run dataset/evals/run_evals.py`.
04. Use standard `run_evals.py` startup (it already runs env setup); do not pre-run `./scripts/env_up.sh` for normal eval triage.
05. If you hit devops/startup instability (ports, stale containers, unhealthy services), run `scripts/env_down.sh` first, then rerun `uv run dataset/evals/run_evals.py`; the eval runner will bring the environment back up automatically.
06. Fix root causes in prompts/code/environment; do not add permissive fallbacks that hide failures.
07. Validate fixes against intended architecture/business behavior, not just current implementation behavior.
08. Use subagents to view and triage from logs; else you'll fill up your context too quickly.
09. If you changed a contract surface (prompt/runtime/helper/validator), treat any earlier eval behavior as tainted evidence until you rerun under the corrected contract.
10. Respect the skill split:

- `.agents/skills/` is the single canonical skill tree for all agents.
- Keep all skill content in `.agents/skills/`.
- If any mirrored or duplicate skill content exists outside that tree, consolidate it back into `.agents/skills/` and remove the duplicate.

11. If you are acting as the supervisor agent, never edit files in a worker agent's workspace. Keep your edits limited to backend/runtime/orchestration/code-path fixes and repository-level contracts; let the worker agent own its own workspace files.
12. Distinguish three end states clearly:

- `code bug`: controller/runtime/helper/validator/integration behavior is wrong.
- `prompt bug`: orchestration is healthy but the agent is being taught the wrong operational contract.
- `optimization gap`: prompt and code contracts are now correct, but the model still fails because solution quality/search is weak.

12. If contract-surface code changed, run the relevant integration test before spending more eval quota.
13. Before rerunning a costly eval after an authored-script or helper-contract change, do at least one cheap validity check first when possible (syntax/import/basic command).
14. When debugging prompts, default to judge mode with reviewer execution enabled (`--run-judge --run-reviewers-with-judge`) so reviewer checklists are populated after hard-check success; opt out only when reviewer execution is intentionally not needed.
15. For basic prompt debugging and other work that is not FEM, fluids, part breakage, Genesis-native stress reporting, dynamic wire/softbody behavior, or other backend-specific artifact behavior, use the MuJoCo default with `uv run dataset/evals/run_evals.py`. Switch to Genesis with `--full-sim` only when backend-specific fidelity work requires it.
16. Treat schema, enum, numeric, and derived-field mismatches as source bugs. Validate exact structured values on node entry and exit, and do not explain them away as model flakiness or patch them with fallback handling.

## Minimal run setup

1. Select one agent and one seed task (normally supplied by user/failure context):

```bash
AGENT=engineer_planner
TASK_ID=$(jq -r '.[0].id' "dataset/data/seed/role_based/${AGENT}.json")
echo "$AGENT $TASK_ID"
```

2. Run exactly that case:

```bash
uv run dataset/evals/run_evals.py \
  --agent "$AGENT" \
  --task-id "$TASK_ID" \
  --limit 1 \
  --concurrency 1 \
  --run-judge \
  --run-reviewers-with-judge \
  --log-level INFO
```

Use `--run-judge` without `--run-reviewers-with-judge` only when reviewer execution is intentionally out of scope for the triage step.

3. For richer trace output during triage, add:

```bash
--verbose --log-level DEBUG
```

4. When the failure involves authored scripts or helper/runtime code, do a cheap pre-eval validity check before the full rerun when possible:

```bash
uv run python -m py_compile path/to/file.py
```

or an import/basic execution probe inside the seeded workspace, depending on the contract.

## Seed validation first

Use seed validation before burning more eval quota when the failure might be the row itself, a fixture, or a stale generated artifact.

```bash
uv run scripts/validate_eval_seed.py --agent <agent> --task-id <task-id>
```

- Add `--skip-env-up` only when the stack is already up and you are doing validation-only triage.
- Add `--queue` when the eval lock is busy and you want to wait instead of failing fast.
- Use `-y` when `--run-judge` would cover more than 10 selected rows.
- Use `--runner-backend` to choose the follow-up judge backend when needed.
- If you need the exact prompt/workspace for one row, inspect it with `uv run dataset/evals/materialize_seed_workspace.py --agent <agent> --task-id <task-id> --provider qwen --no-yolo`.
- Use `scripts/update_eval_seed_renders.py` only when you are intentionally refreshing deterministic render bundles.

## Canonical debug commands

- Preferred log-reading method:
  Use a subagent to inspect logs and return concise evidence (`cause`, `proof lines`, `next fix`), instead of raw full-log reads in the main agent context.

- Primary agent log location:
  Agent pipeline logs/traces are in `logs/manual_run/` (`controller.log`, `worker_light.log`, `worker_heavy.log`, `temporal_worker.log`). Agent-level orchestration traces are in `logs/manual_run/controller.log`.

- Distilled eval trace log:
  `uv run dataset/evals/run_evals.py` also writes `logs/evals/readable_agent_logs.log` and updates `logs/readable_agent_logs.log` symlink.
  Use this first when the goal is to quickly read agent reasoning/tool flow without structlog wrappers.
  Format is intentionally simple:

  - `agent_name | short_run_id | text`
  - `agent_name | short_run_id | TOOL tool_name key=value`
  - `agent_name | short_run_id | RESULT tool_name ...`
  - `agent_name | short_run_id | TOOL tool_name ERROR ...`
    The file is derived from persisted episode traces, not from raw structlog output, so it should not contain ANSI color codes, JSON escaping noise, or structlog brackets/symbols.
    If another eval run is active at the same time, treat the readable log as contested evidence until you rerun in isolated single-agent mode.

- Machine-readable backend error logs:
  When the regression looks like startup, orchestration, or trace drift, inspect `logs/integration_tests/current/json/*_errors.json` alongside `logs/manual_run/` so you can separate product failures from infra noise.

- Hard-check pass-rate helper output:
  `uv run dataset/evals/run_evals.py` now prints `Hard check pass rates:` at the end and writes `logs/evals/hard_check_pass_rates.yaml`.
  Use this to quickly verify which seeded eval IDs were run per agent and which configured reward `hard_checks` failed.
  YAML shape:

  - `<agent_name>.ran_cases: [seed-id, ...]`
  - `<agent_name>.hard_checks.<check_name>.pass_rate`
  - `<agent_name>.hard_checks.<check_name>.failed_seeds`

- List available task IDs for one agent:

```bash
jq -r '.[].id' dataset/data/seed/role_based/engineer_planner.json
```

- Multi-ID task filter syntax (post-triage widening):

```bash
# repeated flag form
uv run dataset/evals/run_evals.py --agent engineer_planner --task-id id-1 --task-id id-2

# comma-separated form
uv run dataset/evals/run_evals.py --agent engineer_planner --task-id id-1,id-2,id-3

# bracket-list form
uv run dataset/evals/run_evals.py --agent engineer_planner --task-id '[id-1,id-2,id-3]'
```

- Fast sidecar sanity check (single use case):

```bash
uv run dataset/evals/run_evals.py \
  --agent <agent_name> \
  --task-id sk-001-sidecar-skill \
  --limit 1 \
  --concurrency 1
```

- Extract key failure lines from eval runner logs:

```bash
rg "eval_trigger_failed|controller_request_failed|eval_failed|eval_timeout|eval_failed_missing_traces|overall_summary" logs/evals/run_evals.log
```

- Read the distilled agent log first:

```bash
sed -n '1,200p' logs/evals/readable_agent_logs.log
```

- Check eval runner status quickly:

```bash
sed -n '1,200p' logs/evals/latest.log
```

- Inspect service logs for the same timestamp window:

```bash
tail -n 200 logs/manual_run/controller.log
tail -n 200 logs/manual_run/worker_light.log
tail -n 200 logs/manual_run/worker_heavy.log
tail -n 200 logs/manual_run/temporal_worker.log
```

- Inspect the run workspace `events.jsonl` sidecar when flow integrity matters:

```bash
sed -n '1,200p' events.jsonl
```

## Contract-surface checklist

When an eval regression looks like contract drift, inspect all relevant surfaces before concluding it is "just a prompt issue":

01. prompt text and examples
02. runtime helper modules exposed to agents
03. loader/import behavior for authored scripts
04. controller validators and script-contract guards
05. schema/request descriptions shown to tools or APIs
06. template repos and sample agent files
07. mock transcripts / integration fixtures that may keep teaching the old contract
08. architecture specs and skills that should own the long-form instructions
09. deterministic validators, normalization helpers, and generated schemas/code that compute or check derived fields
10. observability outputs and terminal metadata (`events.jsonl`, `terminal_reason`, `failure_class`, and backend error JSON logs) when the failure is about trace integrity or status transitions

## Iterative debug directive

When asked to debug pipeline failures, keep iterating this loop until pass (or a real blocker is found):

1. Reproduce on one agent + one task.
2. Classify the failure from logs.
3. Map observed behavior to expected behavior in specs.
4. Implement the smallest source-level fix.
5. Re-run the same single case.
6. After pass, widen one notch (`--limit 2` for the same agent).
7. If the widened run or adjacent seed is still failing, continue debugging there instead of stopping at the first green seed.
8. If the first seed passes cleanly, proactively run at least one adjacent eval for the same agent to check whether the fix generalizes or whether another prompt/code bug remains.
9. Keep expanding after each green eval until you either hit a failing adjacent eval, exhaust the meaningful nearby seed set for that agent, or run into quota/time constraints. A single green seed is evidence, not completion.

Quota guard:

- After the first clear behavior improvement on the target eval, stop and inspect before spending more reruns.
- If the run starts showing unusual infra behavior, controller health churn, or repeated non-informative retries, abort and keep the evidence instead of burning quota.
- If integration is green and the remaining failures are solution-quality failures under a correct contract, stop calling it a pipeline bug and record the remainder as optimization work.

## Triage classification

- Environment/bootstrap failure:
  `controller_unreachable`, `worker_unreachable`, dependency/import/startup errors.
- Seed/fixture contract failure:
  `validate_eval_seed.py` rejects missing artifacts, malformed manifests, stale renders, or workspace-shape drift before full evals can be trusted.
- API/orchestration contract failure:
  `eval_trigger_failed`, wrong status transitions, bad request/response shape.
- Trace/flow integrity failure:
  `eval_failed_missing_traces`, missing required agent trace despite completion-like state.
- Timeout/stall failure:
  `eval_timeout`, repeated `RUNNING` without meaningful progress.
- Prompt/behavior failure:
  pipeline executes but artifacts are invalid/incomplete relative to requirements.
- Optimization gap:
  contracts are now correct and the pipeline is healthy, but the generated solution is still weak, unstable, or under-optimized.
- Architecture gap:
  current code path is over-complex, contradictory, or missing logic needed by intended behavior.

## Architecture and business alignment checks

Use these files as the contract hierarchy for decisions:

1. `specs/desired_architecture.md` (source-of-truth behavior)
2. `specs/architecture/evals-architecture.md` (evaluation tiers, pass criteria, and fail-closed gates)
3. `specs/devtools.md` (runner and maintenance commands, lock behavior, and artifact roots)
4. `specs/integration-test-rules.md` and `specs/integration-test-list.md` (hard behavioral gates and INT mapping)
5. `specs/dataset-generation.md` (seed lineage, batch/eval intent)
6. `specs/architecture/observability.md` (trace, event, and terminal metadata contracts)
7. `specs/business-usecase.md` (business-level success criteria)

If integration expectations and architecture text conflict, document the inconsistency and fix toward the intended product behavior, not accidental implementation quirks.

## Prompt vs code vs environment decision rule

- Fix environment when services or dependencies fail before agent logic runs.
- Fix code/orchestration when state transitions, contracts, or trace semantics are wrong.
- Fix prompts when orchestration is healthy but outputs are consistently low-quality or malformed.
- Classify as optimization work when prompt/code contracts are already correct and the remaining failure is poor search, geometry choice, parameter tuning, or weak iterative improvement.
- If success requires fallback-heavy behavior, the source bug is still unresolved.
- If a structured value is deterministically wrong, fix the producer or validator; do not treat it as prompt quality or accept fallback parsing.
- If a seed validation run fails, do not rerun the same eval case until the seed or fixture is corrected.

Prompt vs skill guidance:

- Stable operational instructions belong in runtime-loaded skills whenever possible.
- Prompts should point to the relevant skill and keep only task-local constraints, role intent, and the minimum contract reminders needed for correctness.
- If you find yourself repeatedly stuffing execution workflow details into prompts, that is usually a signal to move them into a skill.
- Keep the skill boundary clean:
  - runtime-agent skills belong in `.agents/skills/`
  - keep all skill content in `.agents/skills/`
  - if a skill is needed by multiple agents, share it once in `.agents/skills/` rather than duplicating it

Import-side-effect hazard:

- If the new intended contract moves helper calls into module body, verify the heavy/light runtime can import authored scripts without recursively triggering validation, simulation, or submission during control-plane load.
- Check loader behavior and helper import guards before declaring the contract change complete.

Cheap validity checks:

- Prefer a fast syntax/import/basic-execution check before a full eval rerun when the changed surface makes that possible.
- Examples:
  - `uv run python -m py_compile ...` for Python control-plane/runtime files
  - importing the authored script in the seeded workspace
  - one direct validate/simulate probe if the contract allows it
- If the failure might be an invalid seeded eval rather than a pipeline bug, run:
  `uv run scripts/validate_eval_seed.py --agent <agent> --task-id <task-id>`
- If you need the exact prompt/workspace for the suspected bad row, materialize it with:
  `uv run dataset/evals/materialize_seed_workspace.py --agent <agent> --task-id <task-id> --provider qwen --no-yolo`
- This applies to any coder/debug flow, not only benchmark CAD tasks.

## References

- [runner-and-artifacts.md](references/runner-and-artifacts.md): command shapes, artifact roots, and log-reading shortcuts.
- [mock-response-corpus.md](references/mock-response-corpus.md): deterministic scenario corpus shape and preflight helpers.

## Validation checklist before finishing

- Target run passes with one agent, one task, `--limit 1`, `--concurrency 1`.
- Relevant logs in `logs/manual_run/` and `logs/evals/run_evals.log` are consistent with a clean pass.
- If the failure might have been a bad row, `scripts/validate_eval_seed.py` passes for that row or the seed defect is fixed.
- Fix aligns with `desired_architecture` and business use case.
- No permissive fallback introduced to mask failures.
- If contract-surface code changed, the relevant integration test passes before you conclude the pipeline fix is complete.
- At least one adjacent case for the same agent passes (`--limit 2` or another explicit `--task-id`).
- If the target seed passes but an adjacent seed fails, continue triage on that adjacent failure instead of concluding the workflow is complete.
- Derived values, enums, and numeric constraints in logs and artifacts match the deterministic source of truth.

## Reference files

- `dataset/evals/run_evals.py`
- `scripts/env_up.sh` (called by `run_evals.py` unless `--skip-env-up` is explicitly used)
- `logs/manual_run/`
- `logs/evals/run_evals.log`
- `specs/desired_architecture.md`
- `specs/business-usecase.md`
- `specs/integration-tests.md`
- `specs/dataset-generation.md`
