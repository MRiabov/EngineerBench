from __future__ import annotations

import asyncio
import re
import shlex
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from controller.clients.worker import WorkerClient
from evals.logic.codex_session_trace import (
    capture_latest_codex_session_artifacts as _capture_latest_codex_session_artifacts,
)
from evals.logic.codex_session_trace import (
    snapshot_workspace_state as _snapshot_workspace_state,
)
from evals.logic.codex_workspace import get_cli_provider as _get_cli_provider
from evals.logic.codex_workspace import launch_cli_exec as _launch_cli_exec
from evals.logic.codex_workspace import (
    materialize_seed_workspace as _materialize_workspace,
)
from evals.logic.codex_workspace import open_cli_ui as _open_cli_ui
from evals.logic.codex_workspace import resolve_cli_home_root as _resolve_cli_home_root
from evals.logic.codex_workspace import resume_cli_exec as _resume_cli_exec
from evals.logic.codex_workspace import (
    verify_workspace_for_agent as _verify_workspace_for_agent,
)
from evals.logic.models import (
    EvalDatasetItem,
    GitEvalConfig,
    GitStatusExpectation,
)
from evals.logic.review_checks import (
    requires_expected_review_decision as _requires_expected_review_decision,
)
from evals.logic.review_checks import (
    review_artifact_pending as _review_artifact_pending,
)
from evals.logic.review_checks import (
    review_expectation_error as _review_expectation_error,
)
from evals.logic.runner_judging import (
    _completion_contract_error,
    _fetch_episode,
    _missing_required_traces,
    _planned_counts_as_success,
    _request_episode_interrupt,
    _reviewer_metrics_from_verification,
    _run_reviewer_chain_for_judge,
    _validate_unit_eval_allowlist,
)
from evals.logic.runner_metrics import (
    METRIC_HANDLERS,
    _extract_episode_cost_usd,
    _extract_episode_failure_reason,
    _record_hard_check_outcomes,
    _record_judge_outcomes,
    _workspace_metrics,
)
from evals.logic.runner_reporting import (
    RunnerLogContext,
    _append_readable_log_line,
    _console_message,
    _eval_case_label,
    _format_readable_trace_line,
    _mirror_session_trace_to_readable_logs,
    _resolve_eval_log_key,
    _sanitize_readable_text,
    _truncate_text,
    _write_eval_session_metadata,
)
from evals.logic.runner_skill_loop import (
    CodexSkillLoopSummary,
    _load_workspace_simulation_result,
    _record_skill_loop_event,
    _run_skill_loop,
)
from evals.logic.specs import AGENT_SPECS, JUDGE_REVIEWER_CHAIN
from evals.logic.workspace import (
    preflight_seeded_entry_contract as _preflight_seeded_entry_contract,
)
from evals.logic.workspace import seed_eval_workspace as _seed_eval_workspace
from shared.agents.config import (
    load_agents_config,
)
from shared.enums import (
    AgentName,
    EpisodeStatus,
    EvalMode,
    EvalRunnerBackend,
    GenerationKind,
    ReviewDecision,
    SeedMatchMethod,
)
from shared.logging import get_logger
from shared.models.schemas import EpisodeMetadata

logger = get_logger(__name__)


def _dep(deps: dict[str, Any] | None, name: str, default: Any) -> Any:
    if deps is None:
        return default
    return deps.get(name, default)


def _apply_default_non_frontend_integration_marker(command: str) -> str:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return command

    if not tokens:
        return command

    cmd_index = 0
    while cmd_index < len(tokens) and re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[cmd_index]
    ):
        cmd_index += 1

    if cmd_index >= len(tokens):
        return command

    script_token = tokens[cmd_index]
    if script_token not in {
        "./scripts/run_integration_tests.sh",
        "scripts/run_integration_tests.sh",
    }:
        return command

    args = tokens[cmd_index + 1 :]
    if any(arg == "-m" or arg.startswith("-m=") for arg in args):
        return command
    if any(
        "tests/integration/frontend" in arg
        or "tests/e2e" in arg
        or "integration_frontend" in arg
        for arg in args
    ):
        return command

    return command + ' -m "integration_p0 or integration_p1 or integration_p2"'


def _validate_git_status(
    status: Any, expectation: GitStatusExpectation | None
) -> str | None:
    if getattr(status, "error", None):
        return f"git status returned error: {status.error}"

    if expectation is None:
        return None

    if expectation.branch is not None and status.branch != expectation.branch:
        return f"expected branch {expectation.branch!r}, got {status.branch!r}"

    if expectation.is_dirty is not None and status.is_dirty != expectation.is_dirty:
        return f"expected is_dirty={expectation.is_dirty}, got {status.is_dirty}"

    if (
        expectation.is_merging is not None
        and status.is_merging != expectation.is_merging
    ):
        return f"expected is_merging={expectation.is_merging}, got {status.is_merging}"

    if expectation.conflicts is not None:
        actual_conflicts = sorted(status.conflicts)
        expected_conflicts = sorted(expectation.conflicts)
        if actual_conflicts != expected_conflicts:
            return f"expected conflicts={expected_conflicts}, got {actual_conflicts}"

    return None


def _validate_git_commit_result(
    *,
    commit: Any,
    expect_commit_hash: bool,
    action_label: str,
) -> str | None:
    if not commit.success:
        return f"{action_label} returned success=false: {commit.message}"

    has_hash = commit.commit_hash is not None
    if expect_commit_hash and not has_hash:
        return f"{action_label} completed without a commit hash"
    if not expect_commit_hash and has_hash:
        return f"{action_label} unexpectedly produced commit hash {commit.commit_hash}"
    return None


async def _run_git_eval(
    item: EvalDatasetItem,
    stats: dict[AgentName, Any],
    agent_name: AgentName,
    reward_agent_configs,
    *,
    worker_light_url: str,
    root: Path,
    log_context: RunnerLogContext,
    update_manifests: bool = True,
    deps: dict[str, Any] | None = None,
) -> bool:
    deps = deps or {}
    seed_eval_workspace = _dep(deps, "seed_eval_workspace", _seed_eval_workspace)
    record_hard_check_outcomes = _dep(
        deps, "record_hard_check_outcomes", _record_hard_check_outcomes
    )
    write_eval_session_metadata = _dep(
        deps, "write_eval_session_metadata", _write_eval_session_metadata
    )
    apply_marker = _dep(
        deps,
        "apply_default_non_frontend_integration_marker",
        _apply_default_non_frontend_integration_marker,
    )
    task_id = item.id
    log = logger.bind(task_id=task_id, agent_name=agent_name, eval_mode=EvalMode.GIT)
    log.info("eval_start")

    git_eval = item.git_eval or GitEvalConfig()
    session_id = f"eval-git-{task_id}-{uuid.uuid4().hex[:8]}"
    eval_log_key = _resolve_eval_log_key(task_id=task_id, session_id=session_id)
    worker = WorkerClient(base_url=worker_light_url, session_id=session_id)

    success = False
    failure_reason = ""

    try:
        await worker.git_init()
        if item.seed_artifact_dir is not None or item.seed_files:
            await seed_eval_workspace(
                item=item,
                session_id=session_id,
                agent_name=agent_name,
                root=root,
                worker_light_url=worker_light_url,
                logger=logger,
                update_manifests=update_manifests,
            )

        if (
            not git_eval.setup_commands
            and item.seed_artifact_dir is None
            and not item.seed_files
        ):
            await worker.write_file(
                "git_eval_note.md",
                f"# Git Eval {task_id}\n\n{item.task.strip()}\n",
                overwrite=True,
            )

        for command in git_eval.setup_commands:
            command_to_run = apply_marker(command)
            if command_to_run != command:
                log.info(
                    "setup_command_adjusted",
                    original_command=command,
                    adjusted_command=command_to_run,
                )

            result = await worker.execute_command(command_to_run, timeout=60)
            if result.timed_out:
                failure_reason = f"setup command timed out: {command_to_run}"
                break
            if result.exit_code != 0:
                stderr = _truncate_text(result.stderr or result.stdout or "")
                failure_reason = (
                    f"setup command failed with exit_code={result.exit_code}: "
                    f"{command_to_run} ({stderr})"
                )
                break

        requires_merge_flow = bool(
            git_eval.resolve_conflicts
            or git_eval.abort_merge
            or git_eval.merge_complete_message is not None
        )
        if not failure_reason and requires_merge_flow:
            merge_status = await worker.git_status()
            failure_reason = _validate_git_status(merge_status, None)
            if not failure_reason:
                if not merge_status.is_merging:
                    failure_reason = "expected setup to leave repository in merge state"
                elif not merge_status.conflicts:
                    failure_reason = (
                        "expected setup to create conflicted files before merge action"
                    )

        if not failure_reason:
            for step in git_eval.resolve_conflicts:
                resolved = await worker.git_resolve(
                    file_path=step.file_path,
                    strategy=step.strategy,
                )
                if not resolved:
                    failure_reason = (
                        f"git resolve failed for {step.file_path} with strategy "
                        f"{step.strategy}"
                    )
                    break

        if not failure_reason and git_eval.abort_merge:
            aborted = await worker.git_merge_abort()
            if not aborted:
                failure_reason = "git merge abort returned success=false"

        commit = None
        if not failure_reason and not git_eval.abort_merge:
            if git_eval.merge_complete_message is not None:
                commit = await worker.git_merge_complete(
                    message=git_eval.merge_complete_message
                )
                action_label = "git merge complete"
            else:
                commit = await worker.git_commit(
                    message=git_eval.commit_message
                    or f"eval({task_id}): git agent baseline"
                )
                action_label = "git commit"

            expected_hash = git_eval.expect_commit_hash
            if expected_hash is None:
                expected_hash = True
            failure_reason = _validate_git_commit_result(
                commit=commit,
                expect_commit_hash=expected_hash,
                action_label=action_label,
            )

        if not failure_reason:
            status = await worker.git_status()
            failure_reason = _validate_git_status(status, git_eval.expected_status)

        if not failure_reason:
            success = True
            log.info("eval_completed", session_id=session_id)
    except Exception as exc:
        failure_reason = str(exc)
    finally:
        await worker.aclose()

    if not success:
        log.error("eval_failed", reason=failure_reason, session_id=session_id)
    write_eval_session_metadata(
        log_context=log_context,
        eval_log_key=eval_log_key,
        payload={
            "agent_name": agent_name.value,
            "episode_id": None,
            "eval_mode": EvalMode.GIT.value,
            "complexity_level": item.complexity_level,
            "failure_reason": failure_reason,
            "session_id": session_id,
            "success": success,
            "task_id": task_id,
        },
    )

    agent_stats = stats[agent_name]
    agent_stats["total"] += 1
    if success:
        agent_stats["success"] += 1
    await record_hard_check_outcomes(
        stats=stats,
        reward_agent_configs=reward_agent_configs,
        agent_name=agent_name,
        item=item,
        success=success,
        episode_data=None,
        session_id=session_id,
        worker_light_url=worker_light_url,
        log_context=log_context,
        failure_context=(
            {
                "error_code": "git_eval_failed",
                "session_status": "failed",
                "error_message": _truncate_text(failure_reason or "", limit=220),
                "error_source": "evals/logic/runner_execution.py",
            }
            if not success and failure_reason
            else None
        ),
    )
    return success


async def _run_cli_eval(
    *,
    item: EvalDatasetItem,
    stats: dict[AgentName, Any],
    agent_name: AgentName,
    reward_agent_configs,
    case_label: str,
    worker_light_url: str,
    controller_url: str,
    root: Path,
    log_context: RunnerLogContext,
    run_judge: bool = False,
    run_reviewers_with_judge: bool = False,
    enable_skill_loop: bool = False,
    enable_codex_skill_loop: bool | None = None,
    provider_name: str | None = None,
    open_cli_ui: bool = False,
    open_cli_ui_new_terminal: bool = False,
    deps: dict[str, Any] | None = None,
) -> bool:
    deps = deps or {}
    if enable_codex_skill_loop is not None:
        enable_skill_loop = enable_codex_skill_loop
    provider = (
        _get_cli_provider(provider_name)
        if provider_name is not None
        else _get_cli_provider()
    )
    materialize_workspace = _dep(deps, "materialize_workspace", _materialize_workspace)
    launch_cli_exec = _dep(deps, "launch_cli_exec", _launch_cli_exec)
    open_cli_ui_fn = _dep(deps, "open_cli_ui", _open_cli_ui)
    verify_workspace_for_agent = _dep(
        deps, "verify_workspace_for_agent", _verify_workspace_for_agent
    )
    capture_latest_codex_session_artifacts = _dep(
        deps,
        "capture_latest_codex_session_artifacts",
        _capture_latest_codex_session_artifacts,
    )
    snapshot_workspace_state = _dep(
        deps, "snapshot_workspace_state", _snapshot_workspace_state
    )
    resolve_cli_home_root = _dep(deps, "resolve_cli_home_root", _resolve_cli_home_root)
    append_readable_log_line = _dep(
        deps, "append_readable_log_line", _append_readable_log_line
    )
    write_eval_session_metadata = _dep(
        deps, "write_eval_session_metadata", _write_eval_session_metadata
    )
    record_hard_check_outcomes = _dep(
        deps, "record_hard_check_outcomes", _record_hard_check_outcomes
    )
    record_judge_outcomes = _dep(deps, "record_judge_outcomes", _record_judge_outcomes)
    run_skill_loop = _dep(deps, "run_skill_loop", _run_skill_loop)
    run_reviewer_chain_for_judge = _dep(
        deps, "run_reviewer_chain_for_judge", _run_reviewer_chain_for_judge
    )
    workspace_metrics = _dep(deps, "workspace_metrics", _workspace_metrics)
    reviewer_metrics_from_verification = _dep(
        deps,
        "reviewer_metrics_from_verification",
        _reviewer_metrics_from_verification,
    )
    provider = (
        _get_cli_provider(provider_name)
        if provider_name is not None
        else _get_cli_provider()
    )

    task_id = item.id
    spec = AGENT_SPECS[agent_name]
    session_id = f"{provider.session_prefix}-{task_id}-{uuid.uuid4().hex[:8]}"
    eval_log_key = _resolve_eval_log_key(task_id=task_id, session_id=session_id)
    cli_workspace_root = (
        log_context.session_log_root.parent
        if log_context.session_log_root is not None
        else root
    ) / f"{provider.provider_name}-workspaces"
    cli_runtime_root = cli_workspace_root.parent
    cli_workspace_root.mkdir(parents=True, exist_ok=True)
    workspace_dir = cli_workspace_root / (
        f"{agent_name.value}-{task_id}-{uuid.uuid4().hex[:8]}"
    )

    log = logger.bind(
        task_id=task_id,
        agent_name=agent_name,
        eval_mode=spec.mode,
        runner_backend=EvalRunnerBackend.CLI.value,
        provider_name=provider.provider_name,
    )
    log.info("eval_start", backend=EvalRunnerBackend.CLI.value)

    success = False
    failure_reason = ""
    launch_return_code: int | None = None
    verification_result = None
    codex_trace_artifacts = None
    skill_loop_summary = CodexSkillLoopSummary(enabled=enable_skill_loop)
    hard_checks_passed: bool | None = None
    codex_reviewer_results: list[dict[str, Any]] = []

    try:
        materialized = materialize_workspace(
            item=item,
            agent_name=agent_name,
            workspace_dir=workspace_dir,
        )
        log.info(
            "codex_workspace_materialized",
            workspace_dir=str(materialized.workspace_dir),
            prompt_path=str(materialized.prompt_path),
            copied_paths=materialized.copied_paths,
        )
        append_readable_log_line(
            "CODEX_WORKSPACE_MATERIALIZED "
            f"task_id={task_id} "
            f"session_id={session_id} "
            f"workspace_dir={_sanitize_readable_text(str(materialized.workspace_dir))}",
            log_context=log_context,
            eval_log_key=eval_log_key,
        )
        baseline_snapshot = snapshot_workspace_state(
            workspace_dir=materialized.workspace_dir,
        )
        write_eval_session_metadata(
            log_context=log_context,
            eval_log_key=eval_log_key,
            payload={
                "agent_name": agent_name.value,
                "episode_id": None,
                "eval_mode": spec.mode.value,
                "complexity_level": item.complexity_level,
                "provider_name": provider.provider_name,
                "runner_backend": EvalRunnerBackend.CLI.value,
                "session_id": session_id,
                "status": "materialized",
                "success": False,
                "task_id": task_id,
                "workspace_dir": str(materialized.workspace_dir),
                "prompt_path": str(materialized.prompt_path),
            },
        )

        append_readable_log_line(
            f"CODEX_EXEC_LAUNCHED task_id={task_id} session_id={session_id}",
            log_context=log_context,
            eval_log_key=eval_log_key,
        )
        launch_started_at_ns = time.time_ns()
        primary_timeout_seconds = int(
            load_agents_config().execution.agents[agent_name].timeout_seconds
        )
        if open_cli_ui:
            launch_return_code = await asyncio.to_thread(
                open_cli_ui_fn,
                materialized.workspace_dir,
                materialized.prompt_text,
                task_id=task_id,
                agent_name=agent_name,
                session_id=session_id,
                runtime_root=cli_runtime_root,
                yolo=False,
                timeout_seconds=primary_timeout_seconds,
                provider_name=provider.provider_name,
                new_terminal=open_cli_ui_new_terminal,
            )
        else:
            launch_return_code = await asyncio.to_thread(
                launch_cli_exec,
                materialized.workspace_dir,
                materialized.prompt_text,
                task_id=task_id,
                agent_name=agent_name,
                session_id=session_id,
                runtime_root=cli_runtime_root,
                yolo=False,
                timeout_seconds=primary_timeout_seconds,
            )
        if launch_return_code != 0:
            failure_reason = f"CLI-provider exited with code {launch_return_code}"

        if log_context.session_log_root is not None:
            try:
                codex_trace_artifacts = await asyncio.to_thread(
                    capture_latest_codex_session_artifacts,
                    workspace_dir=materialized.workspace_dir,
                    artifact_root=(
                        log_context.session_log_root
                        / eval_log_key
                        / provider.provider_name
                    ),
                    baseline_snapshot=baseline_snapshot,
                    launched_after_ns=launch_started_at_ns,
                    sessions_root=resolve_cli_home_root(
                        task_id=task_id,
                        session_id=session_id,
                        runtime_root=cli_runtime_root,
                    )
                    / provider.home_dir_name
                    / "sessions",
                )
            except Exception as exc:
                codex_trace_artifacts = None
                log.warning(
                    "codex_session_trace_import_failed",
                    session_id=session_id,
                    error=str(exc),
                )

        if codex_trace_artifacts is None:
            log.warning(
                "codex_session_trace_missing",
                session_id=session_id,
                workspace_dir=str(materialized.workspace_dir),
            )
        else:
            _mirror_session_trace_to_readable_logs(
                codex_trace_artifacts,
                log_context=log_context,
                eval_log_key=eval_log_key,
            )
            log.info(
                "codex_session_trace_imported",
                session_id=session_id,
                source_session_id=codex_trace_artifacts.session_id,
                transcript_path=str(codex_trace_artifacts.transcript_path),
                workspace_diff_path=str(codex_trace_artifacts.workspace_diff_path),
                reasoning_count=codex_trace_artifacts.transcript_stats.reasoning_count,
                tool_call_count=codex_trace_artifacts.transcript_stats.tool_call_count,
            )

        verification_result = await verify_workspace_for_agent(
            workspace_dir=materialized.workspace_dir,
            agent_name=agent_name,
            session_id=session_id,
            expected_decision=item.expected_decision,
        )
        simulation_result = _load_workspace_simulation_result(
            materialized.workspace_dir
        )
        simulation_success = (
            bool(simulation_result.success) if simulation_result is not None else False
        )
        if verification_result.success and not simulation_success:
            if failure_reason:
                failure_reason = (
                    f"{failure_reason}; simulation_result.json did not report success"
                )
            else:
                failure_reason = (
                    "simulation_result.json missing"
                    if simulation_result is None
                    else simulation_result.summary
                )

        if verification_result.success and simulation_success and not failure_reason:
            success = True
            log.info(
                "eval_completed",
                session_id=session_id,
                verification=verification_result.verification_name,
            )
        elif not verification_result.success:
            verification_failure = "; ".join(verification_result.errors) or (
                f"{verification_result.verification_name} failed"
            )
            if failure_reason:
                failure_reason = f"{failure_reason}; {verification_failure}"
            else:
                failure_reason = verification_failure

        if enable_skill_loop:
            (
                skill_loop_summary,
                codex_trace_artifacts,
            ) = await run_skill_loop(
                item=item,
                agent_name=agent_name,
                workspace_dir=materialized.workspace_dir,
                codex_runtime_root=cli_runtime_root,
                log_context=log_context,
                baseline_snapshot=baseline_snapshot,
                codex_trace_artifacts=codex_trace_artifacts,
                primary_session_id=session_id,
                launch_return_code=launch_return_code,
                verification_result=verification_result,
                log=log,
                provider_name=provider.provider_name,
                deps={
                    "append_readable_log_line": append_readable_log_line,
                    "capture_latest_codex_session_artifacts": capture_latest_codex_session_artifacts,
                    "resume_cli_exec": _resume_cli_exec,
                    "resolve_cli_home_root": resolve_cli_home_root,
                    "record_skill_loop_event": _record_skill_loop_event,
                    "eval_log_key": eval_log_key,
                },
            )

        codex_metrics = workspace_metrics(
            workspace_dir=materialized.workspace_dir,
            success=success,
            verification_result=verification_result,
        )
        hard_checks_passed = await record_hard_check_outcomes(
            stats=stats,
            reward_agent_configs=reward_agent_configs,
            agent_name=agent_name,
            item=item,
            success=success,
            episode_data=None,
            session_id=session_id,
            worker_light_url=worker_light_url,
            log_context=log_context,
            workspace_dir=materialized.workspace_dir,
            failure_context=(
                {
                    "error_code": "codex_eval_failed",
                    "session_status": "failed",
                    "error_message": _truncate_text(failure_reason or "", limit=220),
                    "error_source": "evals/logic/runner_execution.py",
                }
                if not success and failure_reason
                else None
            ),
            metrics_override=codex_metrics,
        )
        if (
            run_judge
            and run_reviewers_with_judge
            and success
            and hard_checks_passed is True
            and JUDGE_REVIEWER_CHAIN.get(agent_name)
        ):
            codex_reviewer_results = await run_reviewer_chain_for_judge(
                item=item,
                agent_name=agent_name,
                source_workspace_dir=materialized.workspace_dir,
                task_description=item.task,
                session_id=session_id,
                codex_workspace_root=cli_workspace_root,
                codex_runtime_root=cli_runtime_root,
                provider_name=provider.provider_name,
                log=log,
            )

        if run_judge:
            judge_metrics = dict(codex_metrics)
            if codex_reviewer_results:
                judge_metrics.update(
                    reviewer_metrics_from_verification(
                        verification_result=codex_reviewer_results[0],
                        expected_decision=item.expected_decision,
                    )
                )
            await record_judge_outcomes(
                stats=stats,
                reward_agent_configs=reward_agent_configs,
                agent_name=agent_name,
                item=item,
                success=success,
                session_id=session_id,
                worker_light_url=worker_light_url,
                log_context=log_context,
                workspace_dir=materialized.workspace_dir,
                episode_data=None,
                extra_episodes=None,
                metrics_override=judge_metrics,
            )
    except FileNotFoundError as exc:
        failure_reason = str(exc)
        log.error("codex_cli_missing", session_id=session_id, error=failure_reason)
    except Exception as exc:
        failure_reason = str(exc)
        log.exception("codex_eval_failed", session_id=session_id)

    agent_stats = stats[agent_name]
    agent_stats["total"] += 1
    if success:
        agent_stats["success"] += 1

    write_eval_session_metadata(
        log_context=log_context,
        eval_log_key=eval_log_key,
        payload={
            "agent_name": agent_name.value,
            "episode_id": None,
            "eval_mode": spec.mode.value,
            "provider_name": provider.provider_name,
            "runner_backend": EvalRunnerBackend.CLI.value,
            "session_id": session_id,
            "status": "completed" if success else "failed",
            "success": success,
            "task_id": task_id,
            "workspace_dir": str(workspace_dir),
            "launch_return_code": launch_return_code,
            "verification_name": (
                verification_result.verification_name
                if verification_result is not None
                else None
            ),
            "verification_errors": (
                verification_result.errors if verification_result is not None else []
            ),
            "verification_details": (
                verification_result.details if verification_result is not None else {}
            ),
            "codex_skill_loop": skill_loop_summary.model_dump(mode="json"),
            "skill_loop_journal_path": (
                skill_loop_summary.skill_update_turn.journal_path
                if skill_loop_summary.skill_update_turn is not None
                and skill_loop_summary.skill_update_turn.journal_path is not None
                else (
                    skill_loop_summary.self_analysis_turn.journal_path
                    if skill_loop_summary.self_analysis_turn is not None
                    else None
                )
            ),
            "skill_loop_context_snapshot_path": (
                skill_loop_summary.skill_update_turn.context_snapshot_path
                if skill_loop_summary.skill_update_turn is not None
                and skill_loop_summary.skill_update_turn.context_snapshot_path
                is not None
                else (
                    skill_loop_summary.self_analysis_turn.context_snapshot_path
                    if skill_loop_summary.self_analysis_turn is not None
                    else None
                )
            ),
            "hard_checks_passed": hard_checks_passed,
            "judge_reviewer_results": codex_reviewer_results,
            "codex_session_trace": (
                {
                    "session_id": codex_trace_artifacts.session_id,
                    "session_file": str(codex_trace_artifacts.session_file)
                    if codex_trace_artifacts.session_file is not None
                    else None,
                    "artifact_dir": str(codex_trace_artifacts.artifact_dir)
                    if codex_trace_artifacts.artifact_dir is not None
                    else None,
                    "raw_trace_path": str(codex_trace_artifacts.raw_trace_path)
                    if codex_trace_artifacts.raw_trace_path is not None
                    else None,
                    "transcript_path": str(codex_trace_artifacts.transcript_path)
                    if codex_trace_artifacts.transcript_path is not None
                    else None,
                    "summary_path": str(codex_trace_artifacts.summary_path)
                    if codex_trace_artifacts.summary_path is not None
                    else None,
                    "workspace_diff_path": str(
                        codex_trace_artifacts.workspace_diff_path
                    )
                    if codex_trace_artifacts.workspace_diff_path is not None
                    else None,
                    "transcript_stats": (
                        codex_trace_artifacts.transcript_stats.model_dump(mode="json")
                    ),
                    "workspace_changed_paths": (
                        codex_trace_artifacts.workspace_diff.changed_paths
                        if codex_trace_artifacts.workspace_diff is not None
                        else []
                    ),
                }
                if codex_trace_artifacts is not None
                else None
            ),
            "failure_reason": failure_reason or None,
        },
    )

    if not success:
        log.error("eval_failed", reason=failure_reason, session_id=session_id)

    _console_message(
        f"eval case finished: {case_label} - {'success' if success else 'failed'}"
        + f" session_id={session_id}"
    )
    return success


async def run_single_eval(
    item: EvalDatasetItem,
    agent_name: AgentName,
    stats: dict[AgentName, Any],
    reward_agent_configs,
    *,
    worker_light_url: str,
    controller_url: str,
    root: Path,
    log_context: RunnerLogContext,
    verbose: bool = False,
    run_judge: bool = False,
    run_reviewers_with_judge: bool = False,
    runner_backend: EvalRunnerBackend = EvalRunnerBackend.CONTROLLER,
    update_manifests: bool = True,
    enable_skill_loop: bool = False,
    enable_codex_skill_loop: bool | None = None,
    provider_name: str | None = None,
    deps: dict[str, Any] | None = None,
):
    spec = AGENT_SPECS[agent_name]
    _validate_unit_eval_allowlist(agent_name, spec)
    case_label = _eval_case_label(item.id, agent_name.value, spec.mode.value)
    _console_message(f"eval case started: {case_label}")

    deps = deps or {}
    if enable_codex_skill_loop is not None:
        enable_skill_loop = enable_codex_skill_loop

    if spec.mode == EvalMode.GIT:
        success = await _run_git_eval(
            item,
            stats,
            agent_name,
            reward_agent_configs,
            worker_light_url=worker_light_url,
            root=root,
            log_context=log_context,
            update_manifests=update_manifests,
            deps=deps,
        )
        _console_message(
            f"eval case finished: {case_label} - {'success' if success else 'failed'}"
        )
        return

    if runner_backend == EvalRunnerBackend.CLI:
        await _run_cli_eval(
            item=item,
            stats=stats,
            agent_name=agent_name,
            reward_agent_configs=reward_agent_configs,
            case_label=case_label,
            worker_light_url=worker_light_url,
            controller_url=controller_url,
            root=root,
            log_context=log_context,
            run_judge=run_judge,
            run_reviewers_with_judge=run_reviewers_with_judge,
            enable_skill_loop=enable_skill_loop,
            provider_name=provider_name,
            deps=deps,
        )
        return

    task_id = item.id
    task_description = item.task
    lineage = EpisodeMetadata(
        seed_id=task_id,
        seed_dataset=str(item.seed_dataset) if item.seed_dataset else None,
        seed_match_method=SeedMatchMethod.RUNTIME_EXPLICIT,
        generation_kind=GenerationKind.SEEDED_EVAL,
        parent_seed_id=task_id,
        disable_sidecars=True,
    )

    log = logger.bind(
        task_id=task_id,
        agent_name=agent_name,
        eval_mode=spec.mode,
    )
    log.info("eval_start")
    readable_agent = spec.start_node or spec.request_agent_name or agent_name
    readable_agent_name = (
        readable_agent.value
        if isinstance(readable_agent, AgentName)
        else str(readable_agent).strip()
    )

    success = False
    session_id = ""
    episode_id = ""
    last_episode_data: dict[str, Any] | None = None
    eval_log_key = _resolve_eval_log_key(task_id=task_id)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                if spec.mode == EvalMode.BENCHMARK:
                    benchmark_session_id = uuid.uuid4()
                    session_id = str(benchmark_session_id)
                    eval_log_key = _resolve_eval_log_key(
                        task_id=task_id, session_id=session_id
                    )
                    await _seed_eval_workspace(
                        item=item,
                        session_id=session_id,
                        agent_name=agent_name,
                        root=root,
                        worker_light_url=worker_light_url,
                        logger=logger,
                        update_manifests=update_manifests,
                    )
                    await _preflight_seeded_entry_contract(
                        item=item,
                        session_id=session_id,
                        agent_name=agent_name,
                        spec=spec,
                        root=root,
                        worker_light_url=worker_light_url,
                        logger=logger,
                    )
                    url = f"{controller_url}/api/benchmark/generate"
                    payload = {
                        "prompt": task_description,
                        "session_id": session_id,
                        "start_node": spec.start_node,
                        "seed_id": lineage.seed_id,
                        "seed_dataset": lineage.seed_dataset,
                        "generation_kind": lineage.generation_kind,
                    }
                    status_url_template = (
                        f"{controller_url}/api/benchmark/{{session_id}}"
                    )
                    episode_id_key = "episode_id"
                    session_id_key = "session_id"
                else:
                    session_id = f"eval-{task_id}-{uuid.uuid4().hex[:8]}"

                    await _seed_eval_workspace(
                        item=item,
                        session_id=session_id,
                        agent_name=agent_name,
                        root=root,
                        worker_light_url=worker_light_url,
                        logger=logger,
                        update_manifests=update_manifests,
                    )
                    await _preflight_seeded_entry_contract(
                        item=item,
                        session_id=session_id,
                        agent_name=agent_name,
                        spec=spec,
                        root=root,
                        worker_light_url=worker_light_url,
                        logger=logger,
                    )

                    url = f"{controller_url}/agent/run"
                    payload = {
                        "task": task_description,
                        "agent_name": spec.request_agent_name or agent_name,
                        "start_node": spec.start_node or agent_name,
                        "session_id": session_id,
                        "metadata_vars": lineage.model_dump(exclude_none=True),
                    }
                    status_url_template = f"{controller_url}/episodes/{{episode_id}}"
                    episode_id_key = "episode_id"
                    session_id_key = "session_id"

                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    log.error(
                        "eval_trigger_failed",
                        status_code=resp.status_code,
                        response_text=resp.text,
                        session_id=session_id,
                    )
                    stats[agent_name]["total"] += 1
                    await _record_hard_check_outcomes(
                        stats=stats,
                        reward_agent_configs=reward_agent_configs,
                        agent_name=agent_name,
                        item=item,
                        success=False,
                        episode_data=last_episode_data,
                        session_id=session_id,
                        worker_light_url=worker_light_url,
                        log_context=log_context,
                        failure_context={
                            "error_code": "eval_trigger_failed",
                            "session_status": "trigger_failed",
                            "error_message": _truncate_text(
                                f"HTTP {resp.status_code}: {resp.text}", limit=220
                            ),
                            "error_source": "evals/logic/runner_execution.py",
                        },
                    )
                    if run_judge:
                        await _record_judge_outcomes(
                            stats=stats,
                            reward_agent_configs=reward_agent_configs,
                            agent_name=agent_name,
                            item=item,
                            success=False,
                            session_id=session_id,
                            worker_light_url=worker_light_url,
                            log_context=log_context,
                            episode_data=last_episode_data,
                        )
                    _write_eval_session_metadata(
                        log_context=log_context,
                        eval_log_key=eval_log_key,
                        payload={
                            "agent_name": agent_name.value,
                            "episode_id": episode_id or None,
                            "eval_mode": spec.mode.value,
                            "complexity_level": item.complexity_level,
                            "session_id": session_id or None,
                            "status": "trigger_failed",
                            "success": False,
                            "task_id": task_id,
                        },
                    )
                    return

                data = resp.json()
                episode_id = str(
                    data.get(episode_id_key) or data.get("episode_id") or ""
                )
                response_session_id = data.get(session_id_key) or data.get("session_id")
                if response_session_id:
                    session_id = str(response_session_id)
                    eval_log_key = _resolve_eval_log_key(
                        task_id=task_id, session_id=session_id
                    )

                status_url = status_url_template.format(
                    session_id=session_id, episode_id=episode_id
                )
                poll_interval_seconds = 5
                agent_timeout_seconds = int(
                    load_agents_config().execution.agents[agent_name].timeout_seconds
                )
                max_attempts = max(
                    1,
                    (agent_timeout_seconds + poll_interval_seconds - 1)
                    // poll_interval_seconds,
                )
                attempt = 0
                seen_trace_ids = set()
                seen_trace_errors: dict[int, str] = {}
                seen_trace_results: dict[int, str] = {}

                while attempt < max_attempts:
                    await asyncio.sleep(poll_interval_seconds)
                    attempt += 1

                    try:
                        status_resp = await client.get(status_url)
                        if status_resp.status_code == 200:
                            status_data = status_resp.json()
                            last_episode_data = status_data
                            status = status_data.get("status")

                            traces = status_data.get("traces", [])
                            for trace in sorted(traces, key=lambda t: t.get("id", 0)):
                                trace_id = trace.get("id")
                                readable_line = _format_readable_trace_line(
                                    episode=status_data,
                                    trace=trace,
                                    default_agent_name=readable_agent_name,
                                )
                                if trace_id not in seen_trace_ids:
                                    log.debug(
                                        "trace_log",
                                        trace_id=trace_id,
                                        content=trace.get("content"),
                                    )
                                    if verbose:
                                        log.info(
                                            "trace_log",
                                            trace_id=trace_id,
                                            content=trace.get("content"),
                                        )
                                    if readable_line:
                                        _append_readable_log_line(
                                            readable_line,
                                            log_context=log_context,
                                            eval_log_key=eval_log_key,
                                        )
                                    seen_trace_ids.add(trace_id)

                                error_line = _format_readable_trace_line(
                                    episode=status_data,
                                    trace=trace,
                                    default_agent_name=readable_agent_name,
                                    detail_mode="error",
                                )
                                error_text = error_line or ""
                                prior_error_text = seen_trace_errors.get(trace_id, "")
                                if error_text and error_text != prior_error_text:
                                    _append_readable_log_line(
                                        error_text,
                                        log_context=log_context,
                                        eval_log_key=eval_log_key,
                                    )
                                    seen_trace_errors[trace_id] = error_text

                                result_line = _format_readable_trace_line(
                                    episode=status_data,
                                    trace=trace,
                                    default_agent_name=readable_agent_name,
                                    detail_mode="result",
                                )
                                result_text = result_line or ""
                                prior_result_text = seen_trace_results.get(trace_id, "")
                                if result_text and result_text != prior_result_text:
                                    _append_readable_log_line(
                                        result_text,
                                        log_context=log_context,
                                        eval_log_key=eval_log_key,
                                    )
                                    seen_trace_results[trace_id] = result_text

                            if _requires_expected_review_decision(spec):
                                episode = await _fetch_episode(
                                    controller_url, client, episode_id
                                )
                                last_episode_data = episode
                                missing_traces = _missing_required_traces(
                                    spec.required_trace_names, episode
                                )
                                if not missing_traces:
                                    review_error = await _review_expectation_error(
                                        item=item,
                                        spec=spec,
                                        session_id=session_id,
                                        worker_light_url=worker_light_url,
                                    )
                                    if review_error is None:
                                        log.info(
                                            "eval_review_decision_matched",
                                            status=status,
                                        )
                                        success = True
                                        break
                                    if not _review_artifact_pending(review_error):
                                        log.error(
                                            "eval_failed_expected_decision_mismatch",
                                            session_id=session_id,
                                            error=review_error,
                                        )
                                        break

                            if (
                                status == EpisodeStatus.PLANNED
                                and _planned_counts_as_success(agent_name, spec)
                            ):
                                if agent_name == AgentName.BENCHMARK_PLANNER:
                                    episode = await _fetch_episode(
                                        controller_url, client, episode_id
                                    )
                                    last_episode_data = episode
                                    missing_traces = _missing_required_traces(
                                        spec.required_trace_names, episode
                                    )
                                    if missing_traces:
                                        log.error(
                                            "eval_failed_missing_traces",
                                            missing_traces=missing_traces,
                                            session_id=session_id,
                                        )
                                    else:
                                        log.info("eval_planned")
                                        success = True
                                    break

                                if (
                                    spec.mode == EvalMode.BENCHMARK
                                    and not _requires_expected_review_decision(spec)
                                ):
                                    log.info("eval_planned_confirming")
                                    confirm_url = f"{controller_url}/api/benchmark/{session_id}/confirm"
                                    confirm_resp = await client.post(
                                        confirm_url, json={}
                                    )
                                    if confirm_resp.status_code >= 400:
                                        log.error(
                                            "benchmark_confirm_failed",
                                            status_code=confirm_resp.status_code,
                                            response_text=confirm_resp.text,
                                            session_id=session_id,
                                        )
                                        break
                                else:
                                    episode = await _fetch_episode(
                                        controller_url, client, episode_id
                                    )
                                    last_episode_data = episode
                                    missing_traces = _missing_required_traces(
                                        spec.required_trace_names, episode
                                    )
                                    if missing_traces:
                                        log.error(
                                            "eval_failed_missing_traces",
                                            missing_traces=missing_traces,
                                            session_id=session_id,
                                        )
                                    else:
                                        completion_error = (
                                            await _completion_contract_error(
                                                worker_light_url=worker_light_url,
                                                spec=spec,
                                                session_id=session_id,
                                            )
                                        )
                                        if completion_error:
                                            log.error(
                                                "eval_failed_completion_contract",
                                                session_id=session_id,
                                                error=completion_error,
                                            )
                                        else:
                                            review_error = (
                                                await _review_expectation_error(
                                                    item=item,
                                                    spec=spec,
                                                    session_id=session_id,
                                                    worker_light_url=worker_light_url,
                                                )
                                            )
                                            if review_error:
                                                log.error(
                                                    "eval_failed_expected_decision_mismatch",
                                                    session_id=session_id,
                                                    error=review_error,
                                                )
                                            else:
                                                log.info("eval_planned")
                                                success = True
                                    break

                            if status == EpisodeStatus.COMPLETED:
                                episode = await _fetch_episode(
                                    controller_url, client, episode_id
                                )
                                last_episode_data = episode
                                missing_traces = _missing_required_traces(
                                    spec.required_trace_names, episode
                                )
                                if missing_traces:
                                    log.error(
                                        "eval_failed_missing_traces",
                                        missing_traces=missing_traces,
                                        session_id=session_id,
                                    )
                                else:
                                    completion_error = await _completion_contract_error(
                                        worker_light_url=worker_light_url,
                                        spec=spec,
                                        session_id=session_id,
                                    )
                                    if completion_error:
                                        log.error(
                                            "eval_failed_completion_contract",
                                            session_id=session_id,
                                            error=completion_error,
                                        )
                                    else:
                                        review_error = await _review_expectation_error(
                                            item=item,
                                            spec=spec,
                                            session_id=session_id,
                                            worker_light_url=worker_light_url,
                                        )
                                        if review_error:
                                            log.error(
                                                "eval_failed_expected_decision_mismatch",
                                                session_id=session_id,
                                                error=review_error,
                                            )
                                        else:
                                            log.info("eval_completed")
                                            success = True
                                break

                            if status == EpisodeStatus.FAILED:
                                episode = await _fetch_episode(
                                    controller_url, client, episode_id
                                )
                                last_episode_data = episode
                                missing_traces = _missing_required_traces(
                                    spec.required_trace_names, episode
                                )
                                if missing_traces:
                                    log.error(
                                        "eval_failed_missing_traces",
                                        missing_traces=missing_traces,
                                        session_id=session_id,
                                    )
                                else:
                                    review_error = await _review_expectation_error(
                                        item=item,
                                        spec=spec,
                                        session_id=session_id,
                                        worker_light_url=worker_light_url,
                                    )
                                    if review_error:
                                        log.error(
                                            "eval_failed",
                                            session_id=session_id,
                                            reason=review_error,
                                            error=review_error,
                                        )
                                    elif (
                                        item.expected_decision is not None
                                        and item.expected_decision
                                        != ReviewDecision.APPROVED
                                    ):
                                        log.info("eval_failed_as_expected")
                                        success = True
                                    else:
                                        log.error(
                                            "eval_failed",
                                            session_id=session_id,
                                            reason=(
                                                _extract_episode_failure_reason(
                                                    last_episode_data
                                                )
                                                or "episode reported FAILED"
                                            ),
                                        )
                                break

                            if status == EpisodeStatus.CANCELLED:
                                log.warning("eval_cancelled")
                                break

                            if attempt % 6 == 0:
                                log.info(
                                    "eval_still_running", status=status, attempt=attempt
                                )
                        else:
                            log.warning(
                                "eval_status_check_failed",
                                status_code=status_resp.status_code,
                            )
                    except Exception:
                        log.exception("eval_status_check_exception")

                if attempt >= max_attempts:
                    log.warning("eval_timeout", max_attempts=max_attempts)

                agent_stats = stats[agent_name]
                eval_cost_usd = _extract_episode_cost_usd(last_episode_data)
                agent_stats["total"] += 1
                if eval_cost_usd is not None:
                    agent_stats["total_cost_usd"] += eval_cost_usd
                    agent_stats["costed_cases"] += 1
                if success:
                    agent_stats["success"] += 1

                    worker = WorkerClient(
                        base_url=worker_light_url, session_id=session_id
                    )
                    handler = METRIC_HANDLERS.get(agent_name)
                    try:
                        if handler:
                            await handler(worker, session_id, agent_stats)
                    finally:
                        await worker.aclose()

                hard_checks_passed = await _record_hard_check_outcomes(
                    stats=stats,
                    reward_agent_configs=reward_agent_configs,
                    agent_name=agent_name,
                    item=item,
                    success=success,
                    episode_data=last_episode_data,
                    session_id=session_id,
                    worker_light_url=worker_light_url,
                    log_context=log_context,
                )
                reviewer_episodes: list[dict[str, Any]] = []
                if (
                    run_judge
                    and run_reviewers_with_judge
                    and success
                    and hard_checks_passed is True
                ):
                    reviewer_episodes = await _run_reviewer_chain_for_judge(
                        controller_url=controller_url,
                        client=client,
                        agent_name=agent_name,
                        session_id=session_id,
                        task_description=task_description,
                        lineage=lineage,
                        log=log,
                    )

                if run_judge:
                    await _record_judge_outcomes(
                        stats=stats,
                        reward_agent_configs=reward_agent_configs,
                        agent_name=agent_name,
                        item=item,
                        success=success,
                        session_id=session_id,
                        worker_light_url=worker_light_url,
                        log_context=log_context,
                        episode_data=last_episode_data,
                        extra_episodes=reviewer_episodes,
                    )
            except asyncio.CancelledError:
                log.warning(
                    "eval_run_interrupted",
                    session_id=session_id or None,
                    episode_id=episode_id or None,
                )
                if episode_id:
                    await asyncio.shield(
                        _request_episode_interrupt(
                            controller_url,
                            episode_id,
                            log=log,
                        )
                    )
                raise
            except Exception as exc:
                log.exception(
                    "controller_request_failed", session_id=session_id or None
                )
                stats[agent_name]["total"] += 1
                await _record_hard_check_outcomes(
                    stats=stats,
                    reward_agent_configs=reward_agent_configs,
                    agent_name=agent_name,
                    item=item,
                    success=False,
                    episode_data=last_episode_data,
                    session_id=session_id,
                    worker_light_url=worker_light_url,
                    log_context=log_context,
                    failure_context={
                        "error_code": "controller_request_failed",
                        "session_status": "controller_request_failed",
                        "error_message": _truncate_text(str(exc), limit=220),
                        "error_source": "evals/logic/runner_execution.py",
                    },
                )
                if run_judge:
                    await _record_judge_outcomes(
                        stats=stats,
                        reward_agent_configs=reward_agent_configs,
                        agent_name=agent_name,
                        item=item,
                        success=False,
                        session_id=session_id,
                        worker_light_url=worker_light_url,
                        log_context=log_context,
                        episode_data=last_episode_data,
                    )
                _write_eval_session_metadata(
                    log_context=log_context,
                    eval_log_key=eval_log_key,
                    payload={
                        "agent_name": agent_name.value,
                        "episode_id": episode_id or None,
                        "eval_mode": spec.mode.value,
                        "complexity_level": item.complexity_level,
                        "session_id": session_id or None,
                        "status": "controller_request_failed",
                        "success": False,
                        "task_id": task_id,
                    },
                )
                return
        _write_eval_session_metadata(
            log_context=log_context,
            eval_log_key=eval_log_key,
            payload={
                "agent_name": agent_name.value,
                "episode_id": episode_id or None,
                "eval_mode": spec.mode.value,
                "complexity_level": item.complexity_level,
                "session_id": session_id or None,
                "status": "completed",
                "success": success,
                "task_id": task_id,
            },
        )
    finally:
        _console_message(
            f"eval case finished: {case_label} - {'success' if success else 'failed'}"
            + (f" session_id={session_id}" if session_id else "")
        )


_run_codex_eval = _run_cli_eval
