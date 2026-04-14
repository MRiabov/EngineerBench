from __future__ import annotations

import argparse
import asyncio
import atexit
import contextlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pyrate_limiter import Duration, Limiter, Rate

from evals.logic.cli_provider import available_cli_providers
from evals.logic.codex_session_trace import (
    CodexSessionTraceArtifact,
)
from evals.logic.codex_session_trace import (
    capture_latest_codex_session_artifacts as _capture_latest_codex_session_artifacts,
)
from evals.logic.codex_session_trace import (
    snapshot_workspace_state as _snapshot_workspace_state,
)
from evals.logic.codex_workspace import (
    WorkspaceVerificationResult,
)
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
from evals.logic.dataset_selection import (
    parse_level_filters as _parse_level_filters,
)
from evals.logic.dataset_selection import (
    parse_task_id_filters as _parse_task_id_filters,
)
from evals.logic.models import (
    EvalDatasetItem,
)
from evals.logic.notifications import start_periodic_audible_reminder
from evals.logic.review_checks import (
    requires_expected_review_decision as _requires_expected_review_decision,
)
from evals.logic.runner_execution import (
    _apply_default_non_frontend_integration_marker,
)
from evals.logic.runner_execution import _run_cli_eval as _run_cli_eval_impl
from evals.logic.runner_execution import (
    _run_git_eval as _run_git_eval_impl,
)
from evals.logic.runner_execution import (
    run_single_eval as _run_single_eval_impl,
)
from evals.logic.runner_judging import (
    _reviewer_metrics_from_verification,
    _run_reviewer_chain_for_judge,
    _validate_unit_eval_allowlist,
    _wait_for_controller_ready,
    _wait_for_worker_ready,
)
from evals.logic.runner_metrics import (
    _load_agent_reward_configs,
    _record_hard_check_outcomes,
    _record_judge_outcomes,
    _workspace_metrics,
)
from evals.logic.runner_reporting import (
    RunnerLogContext,
    _append_readable_log_line,
    _console_message,
    _emit_startup_log_pointers,
    _eval_case_label,
    _path_for_report,
    _resolve_eval_log_key,
    _truncate_text,
    _write_eval_session_metadata,
)
from evals.logic.runner_reporting import (
    _mirror_session_trace_to_readable_logs as _mirror_session_trace_to_readable_logs_impl,
)
from evals.logic.runner_skill_loop import (
    CodexSkillLoopSummary,
    _record_skill_loop_event,
)
from evals.logic.runner_skill_loop import (
    _run_skill_loop as _run_skill_loop_module,
)
from evals.logic.specs import (
    AGENT_SPECS,
)
from evals.logic.stack_profiles import apply_stack_profile_env
from evals.logic.startup_checks import fail_closed_if_integration_test_setup
from evals.logic.workspace import (
    preflight_seeded_entry_contract as _preflight_seeded_entry_contract,
)
from evals.logic.workspace import (
    seed_eval_workspace as _seed_eval_workspace,
)
from scripts.internal.eval_run_lock import (
    EvalRunSelection,
    acquire_eval_run_lock,
    acquire_eval_run_shared_lock,
    downgrade_eval_run_lock_to_shared,
    release_eval_run_lock,
)
from shared.enums import (
    AgentName,
    EvalMode,
    EvalRunnerBackend,
)
from shared.logging import configure_logging, get_logger

ROOT = Path(__file__).resolve().parents[2]

load_dotenv()
logger = get_logger(__name__)

CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://localhost:18000")
WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://localhost:18001")
EVAL_RUNNER_BACKEND_ENV = "EVAL_RUNNER_BACKEND"
READABLE_AGENT_LOG_FILE: Path | None = None
SESSION_LOG_ROOT: Path | None = None
DEFAULT_EVAL_AGENT = AgentName.BENCHMARK_PLANNER.value
DEFAULT_EVAL_LIMIT = 1
DEFAULT_EVAL_CONCURRENCY = 1


def _build_log_context() -> RunnerLogContext:
    return RunnerLogContext(
        root=ROOT,
        readable_agent_log_file=READABLE_AGENT_LOG_FILE,
        session_log_root=SESSION_LOG_ROOT,
    )


def _dep_for_runner(deps: dict[str, Any] | None, name: str, default: Any) -> Any:
    if deps is None:
        return default
    return deps.get(name, default)


def _resolve_runner_backend(
    *,
    runner_backend_arg: str | None,
    call_paid_api: bool | None,
    env_runner_backend: str | None,
) -> EvalRunnerBackend:
    if runner_backend_arg is not None:
        return EvalRunnerBackend(runner_backend_arg)

    if call_paid_api is True:
        return EvalRunnerBackend.CONTROLLER

    if call_paid_api is False:
        return EvalRunnerBackend.CODEX

    if env_runner_backend:
        return EvalRunnerBackend(env_runner_backend)

    return EvalRunnerBackend.CODEX


def _mirror_session_trace_to_readable_logs(
    trace_artifacts: CodexSessionTraceArtifact,
    *,
    eval_log_key: str | None,
) -> None:
    return _mirror_session_trace_to_readable_logs_impl(
        trace_artifacts,
        log_context=_build_log_context(),
        eval_log_key=eval_log_key,
    )


async def _run_skill_loop(
    *,
    item: EvalDatasetItem,
    agent_name: AgentName,
    workspace_dir: Path,
    cli_runtime_root: Path,
    eval_log_key: str | None,
    baseline_snapshot,
    codex_trace_artifacts: CodexSessionTraceArtifact | None,
    primary_session_id: str | None = None,
    launch_return_code: int | None,
    verification_result: WorkspaceVerificationResult | None,
    log,
    provider_name: str | None = None,
) -> tuple[CodexSkillLoopSummary, CodexSessionTraceArtifact | None]:
    return await _run_skill_loop_module(
        item=item,
        agent_name=agent_name,
        workspace_dir=workspace_dir,
        codex_runtime_root=cli_runtime_root,
        log_context=_build_log_context(),
        baseline_snapshot=baseline_snapshot,
        codex_trace_artifacts=codex_trace_artifacts,
        primary_session_id=primary_session_id,
        launch_return_code=launch_return_code,
        verification_result=verification_result,
        log=log,
        provider_name=provider_name,
        deps={
            "append_readable_log_line": _append_readable_log_line,
            "capture_latest_codex_session_artifacts": _capture_latest_codex_session_artifacts,
            "resume_cli_exec": _resume_cli_exec,
            "resolve_cli_home_root": _resolve_cli_home_root,
            "record_skill_loop_event": _record_skill_loop_event,
            "eval_log_key": eval_log_key,
        },
    )


async def _run_git_eval(
    item: EvalDatasetItem,
    stats: dict[AgentName, Any],
    agent_name: AgentName,
    reward_agent_configs,
    update_manifests: bool = True,
) -> bool:
    return await _run_git_eval_impl(
        item,
        stats,
        agent_name,
        reward_agent_configs,
        worker_light_url=WORKER_LIGHT_URL,
        root=ROOT,
        log_context=_build_log_context(),
        update_manifests=update_manifests,
        deps={
            "seed_eval_workspace": _seed_eval_workspace,
            "record_hard_check_outcomes": _record_hard_check_outcomes,
            "write_eval_session_metadata": _write_eval_session_metadata,
            "apply_default_non_frontend_integration_marker": _apply_default_non_frontend_integration_marker,
        },
    )


async def _run_cli_eval(
    *,
    item: EvalDatasetItem,
    stats: dict[AgentName, Any],
    agent_name: AgentName,
    reward_agent_configs,
    case_label: str,
    run_judge: bool = False,
    run_reviewers_with_judge: bool = False,
    enable_skill_loop: bool = False,
    enable_codex_skill_loop: bool | None = None,
    provider_name: str | None = None,
    open_cli_ui: bool = False,
    open_cli_ui_new_terminal: bool = False,
) -> bool:
    if enable_codex_skill_loop is not None:
        enable_skill_loop = enable_codex_skill_loop
    provider_label = (provider_name or "codex").strip() or "codex"
    return await _run_cli_eval_impl(
        item=item,
        stats=stats,
        agent_name=agent_name,
        reward_agent_configs=reward_agent_configs,
        case_label=case_label,
        worker_light_url=WORKER_LIGHT_URL,
        controller_url=CONTROLLER_URL,
        root=ROOT,
        log_context=_build_log_context(),
        run_judge=run_judge,
        run_reviewers_with_judge=run_reviewers_with_judge,
        enable_skill_loop=enable_skill_loop,
        provider_name=provider_name,
        open_cli_ui=open_cli_ui,
        open_cli_ui_new_terminal=open_cli_ui_new_terminal,
        deps={
            "materialize_workspace": _materialize_workspace,
            "launch_cli_exec": _launch_cli_exec,
            "open_cli_ui": _open_cli_ui,
            "verify_workspace_for_agent": _verify_workspace_for_agent,
            "capture_latest_codex_session_artifacts": _capture_latest_codex_session_artifacts,
            "snapshot_workspace_state": _snapshot_workspace_state,
            "resolve_cli_home_root": _resolve_cli_home_root,
            "append_readable_log_line": _append_readable_log_line,
            "write_eval_session_metadata": _write_eval_session_metadata,
            "record_hard_check_outcomes": _record_hard_check_outcomes,
            "record_judge_outcomes": _record_judge_outcomes,
            "run_skill_loop": _run_skill_loop,
            "run_reviewer_chain_for_judge": _run_reviewer_chain_for_judge,
            "workspace_metrics": _workspace_metrics,
            "reviewer_metrics_from_verification": _reviewer_metrics_from_verification,
            "eval_log_key": _resolve_eval_log_key(
                task_id=item.id, session_id=f"{provider_label}-{item.id}"
            ),
        },
    )


async def run_single_eval(
    item: EvalDatasetItem,
    agent_name: AgentName,
    stats: dict[AgentName, Any],
    reward_agent_configs,
    verbose: bool = False,
    run_judge: bool = False,
    run_reviewers_with_judge: bool = False,
    runner_backend: EvalRunnerBackend = EvalRunnerBackend.CONTROLLER,
    update_manifests: bool = True,
    enable_skill_loop: bool = False,
    enable_codex_skill_loop: bool | None = None,
    provider_name: str | None = None,
    open_cli_ui: bool = False,
    open_cli_ui_new_terminal: bool = False,
):
    if enable_codex_skill_loop is not None:
        enable_skill_loop = enable_codex_skill_loop
    spec = AGENT_SPECS[agent_name]
    _validate_unit_eval_allowlist(agent_name, spec)
    case_label = _eval_case_label(item, agent_name, spec.mode)
    _console_message(f"eval case started: {case_label}")

    if spec.mode == EvalMode.GIT:
        success = await _run_git_eval(
            item,
            stats,
            agent_name,
            reward_agent_configs,
            update_manifests=update_manifests,
        )
        _console_message(
            f"eval case finished: {case_label} - {'success' if success else 'failed'}"
        )
        return

    if runner_backend == EvalRunnerBackend.CODEX:
        await _run_cli_eval(
            item=item,
            stats=stats,
            agent_name=agent_name,
            reward_agent_configs=reward_agent_configs,
            case_label=case_label,
            run_judge=run_judge,
            run_reviewers_with_judge=run_reviewers_with_judge,
            enable_skill_loop=enable_skill_loop,
            provider_name=provider_name,
            open_cli_ui=open_cli_ui,
            open_cli_ui_new_terminal=open_cli_ui_new_terminal,
        )
        return

    await _run_single_eval_impl(
        item,
        agent_name,
        stats,
        reward_agent_configs,
        verbose=verbose,
        run_judge=run_judge,
        run_reviewers_with_judge=run_reviewers_with_judge,
        runner_backend=runner_backend,
        update_manifests=update_manifests,
        enable_skill_loop=enable_skill_loop,
        worker_light_url=WORKER_LIGHT_URL,
        controller_url=CONTROLLER_URL,
        root=ROOT,
        log_context=_build_log_context(),
        deps={
            "_run_git_eval": _run_git_eval,
            "_run_cli_eval": _run_cli_eval,
        },
    )


_mirror_codex_session_trace_to_readable_logs = _mirror_session_trace_to_readable_logs
_run_codex_skill_loop = _run_skill_loop
_run_codex_eval = _run_cli_eval


async def _preflight_selected_seeded_tasks(
    *,
    tasks: list[tuple[EvalDatasetItem, AgentName]],
    update_manifests: bool = True,
) -> None:
    failures: list[str] = []

    for item, agent_name in tasks:
        spec = AGENT_SPECS[agent_name]
        if spec.mode == EvalMode.GIT:
            continue
        if item.seed_artifact_dir is None and not item.seed_files:
            continue

        session_id = f"eval-preflight-{item.id}-{uuid.uuid4().hex[:8]}"
        try:
            await _seed_eval_workspace(
                item=item,
                session_id=session_id,
                agent_name=agent_name,
                root=ROOT,
                worker_light_url=WORKER_LIGHT_URL,
                logger=logger,
                update_manifests=update_manifests,
            )
            await _preflight_seeded_entry_contract(
                item=item,
                session_id=session_id,
                agent_name=agent_name,
                spec=spec,
                root=ROOT,
                worker_light_url=WORKER_LIGHT_URL,
                logger=logger,
            )
            logger.info(
                "eval_seed_entry_preflight_ready",
                task_id=item.id,
                agent_name=agent_name,
                session_id=session_id,
            )
        except Exception as exc:
            message = _truncate_text(str(exc), limit=400)
            logger.error(
                "eval_seed_entry_preflight_failed",
                task_id=item.id,
                agent_name=agent_name,
                session_id=session_id,
                error=message,
            )
            failures.append(f"- {agent_name.value}:{item.id}: {message}")

    if failures:
        raise ValueError(
            "seeded preflight failed before run start:\n" + "\n".join(failures)
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Agent Evals")

    parser.add_argument(
        "--agent",
        type=str,
        default=DEFAULT_EVAL_AGENT,
        help=(f"Agent to evaluate (default: {DEFAULT_EVAL_AGENT} smoke-test run)"),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_EVAL_LIMIT,
        help=(
            "Limit number of eval items per agent "
            f"(default: {DEFAULT_EVAL_LIMIT} smoke-test item)"
        ),
    )
    parser.add_argument(
        "--random",
        action="store_true",
        help="Randomize dataset selection before applying --limit",
    )
    parser.add_argument(
        "--task-id",
        action="append",
        default=None,
        help=(
            "Run only specific task IDs. Supports a single ID, repeated flags, "
            "comma-separated values, or list syntax like [id-1,id-2]."
        ),
    )
    parser.add_argument(
        "--level",
        action="append",
        default=None,
        help=(
            "Run only evals at the selected complexity levels. Supports a single "
            "level, repeated flags, comma-separated values, or list syntax like [0,1]."
        ),
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print backend traces during polling"
    )
    parser.add_argument(
        "--full-sim",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Use the full-fidelity Genesis simulation backend for this eval run "
            "(default: disabled; MuJoCo is the default backend unless a seed "
            "or benchmark explicitly requires Genesis)."
        ),
    )
    parser.add_argument(
        "--run-judge",
        action="store_true",
        help="Record judge/checklist pass rates from reward_config judge_evaluation",
    )
    parser.add_argument(
        "--run-reviewers-with-judge",
        action="store_true",
        help=(
            "When --run-judge is enabled, run reviewer stages after hard checks "
            "pass to populate reviewer checklist metrics."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_EVAL_CONCURRENCY,
        help=(
            "Max number of eval tasks to run concurrently "
            f"(default: {DEFAULT_EVAL_CONCURRENCY} for smoke-test runs)"
        ),
    )
    parser.add_argument(
        "--no-rate-limit", action="store_true", help="Disable the 50 RPM rate limit"
    )
    parser.add_argument(
        "--skip-env-up",
        action="store_true",
        help=("Skip running scripts/env_up.sh and join the shared eval lock directly."),
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="Wait for the shared eval lock instead of failing fast when another eval run is active.",
    )
    parser.add_argument(
        "--update-manifests",
        dest="update_manifests",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Repair deterministic seed-manifest drift before seeding workspaces "
            "(default: enabled)."
        ),
    )
    parser.add_argument(
        "--call-paid-api",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Use the controller/API LLM path instead of local Codex CLI "
            "execution. The controller still orchestrates the run; this flag "
            "only switches how model calls/tool use happen under the hood."
        ),
    )
    parser.add_argument(
        "--codex-skill-loop",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Enable the Codex self-improving skill loop for Codex backend runs "
            "(default: disabled)."
        ),
    )
    parser.add_argument(
        "--open-cli-ui",
        action="store_true",
        help=(
            "Open local CLI-provider eval launches in an interactive UI instead "
            "of the plain exec path. When concurrency is greater than 1, each "
            "launch uses a separate terminal window."
        ),
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="qwen",
        choices=available_cli_providers(),
        help=(
            "CLI provider to use for local backend runs (default: qwen). "
            "The provider choice is orthogonal to --runner-backend."
        ),
    )
    parser.add_argument(
        "--runner-backend",
        type=str,
        default=None,
        choices=[backend.value for backend in EvalRunnerBackend],
        help=(
            "Explicit execution backend override: 'controller' for the API LLM "
            "path, 'codex' for the local CLI LLM path. Codex is the default "
            "when neither --call-paid-api nor EVAL_RUNNER_BACKEND is set."
        ),
    )
    parser.add_argument(
        "--log-level",
        "--log_level",
        type=str,
        default="ERROR",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Console log level; detailed logs are written to files (default: ERROR)",
    )
    return parser


async def main():
    parser = _build_parser()
    args = parser.parse_args()
    selected_task_ids = _parse_task_id_filters(args.task_id)
    try:
        selected_levels = _parse_level_filters(args.level)
    except SystemExit as exc:
        parser.error(str(exc))

    if args.task_id and not selected_task_ids:
        parser.error("--task-id provided but no valid task IDs were parsed")
    if args.level and not selected_levels:
        parser.error("--level provided but no valid complexity levels were parsed")

    os.environ["SIMULATION_DEFAULT_BACKEND"] = "GENESIS" if args.full_sim else "MUJOCO"

    try:
        runner_backend = _resolve_runner_backend(
            runner_backend_arg=args.runner_backend,
            call_paid_api=args.call_paid_api,
            env_runner_backend=os.getenv(EVAL_RUNNER_BACKEND_ENV),
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.open_cli_ui and runner_backend != EvalRunnerBackend.CODEX:
        parser.error("--open-cli-ui requires the local Codex CLI backend")

    requested_command = [sys.argv[0], *sys.argv[1:]]
    requested_selection = EvalRunSelection(
        agent=None if args.agent == "all" else args.agent,
        task_ids=selected_task_ids,
        levels=sorted(selected_levels),
    )
    if runner_backend == EvalRunnerBackend.CONTROLLER and not args.skip_env_up:
        lock_lease = acquire_eval_run_lock(
            queue=args.queue,
            requested_command=requested_command,
            requested_selection=requested_selection,
        )
    else:
        lock_lease = acquire_eval_run_shared_lock(
            queue=args.queue,
            requested_command=requested_command,
            requested_selection=requested_selection,
        )
    if lock_lease is None:
        sys.exit(1)
    atexit.register(release_eval_run_lock, lock_lease)

    stack_profile = apply_stack_profile_env("eval", env=os.environ, root=ROOT)
    global CONTROLLER_URL
    global WORKER_LIGHT_URL
    CONTROLLER_URL = os.environ["CONTROLLER_URL"]
    WORKER_LIGHT_URL = os.environ["WORKER_LIGHT_URL"]
    os.environ["PROBLEMOLOGIST_CLI_ALLOW_HOST_LOOPBACK"] = "1"

    eval_reminder = None
    if runner_backend == EvalRunnerBackend.CONTROLLER:
        eval_reminder = start_periodic_audible_reminder("eval setup running")
        atexit.register(eval_reminder.stop)

    if args.run_reviewers_with_judge and not args.run_judge:
        parser.error("--run-reviewers-with-judge requires --run-judge")

    try:
        await asyncio.to_thread(
            fail_closed_if_integration_test_setup,
            CONTROLLER_URL,
            context="eval runner startup",
        )
    except SystemExit as exc:
        _console_message(str(exc))
        sys.exit(1)

    evals_root = ROOT / "logs" / "evals"
    runs_root = evals_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    run_name = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    log_dir = runs_root / run_name
    suffix = 1
    while log_dir.exists():
        log_dir = runs_root / f"{run_name}_{suffix}"
        suffix += 1
    log_dir.mkdir(parents=True, exist_ok=True)
    if lock_lease.state is not None:
        lock_lease.update_state(current_log_dir=str(log_dir), current_phase="startup")

    now = time.time()
    cutoff_seconds = 24 * 60 * 60
    for old_run in runs_root.glob("run_*"):
        try:
            if now - old_run.stat().st_mtime > cutoff_seconds:
                if old_run.is_dir():
                    shutil.rmtree(old_run, ignore_errors=True)
                else:
                    old_run.unlink(missing_ok=True)
        except OSError:
            continue

    log_file = log_dir / "run_evals.log"
    readable_log_file = log_dir / "readable_agent_logs.log"
    session_log_root = log_dir / "sessions"
    session_log_root.mkdir(parents=True, exist_ok=True)

    current_link = evals_root / "current"
    if current_link.exists() or current_link.is_symlink():
        with contextlib.suppress(Exception):
            current_link.unlink()
    with contextlib.suppress(Exception):
        current_link.symlink_to(log_dir.relative_to(evals_root))

    latest_log = evals_root / "latest.log"
    if latest_log.exists() or latest_log.is_symlink():
        with contextlib.suppress(Exception):
            latest_log.unlink()
    with contextlib.suppress(Exception):
        latest_log.symlink_to(Path("current") / "run_evals.log")

    if readable_log_file.exists():
        with contextlib.suppress(Exception):
            readable_log_file.unlink()
    readable_log_file.touch()

    os.environ["LOG_DIR"] = str(log_dir)
    os.environ["SESSION_LOG_ROOT"] = str(session_log_root)
    os.environ["EXTRA_DEBUG_LOG"] = str(log_file)
    os.environ["LOG_LEVEL"] = args.log_level
    configure_logging("evals")

    global logger
    global READABLE_AGENT_LOG_FILE
    global SESSION_LOG_ROOT
    logger = get_logger(__name__)
    READABLE_AGENT_LOG_FILE = readable_log_file
    SESSION_LOG_ROOT = session_log_root
    _build_log_context()
    logger.info(
        "eval_stack_profile_selected",
        profile=stack_profile.name,
        compose_project=stack_profile.compose_project_name,
        controller_url=CONTROLLER_URL,
        worker_light_url=WORKER_LIGHT_URL,
        frontend_enabled=stack_profile.start_frontend,
    )
    logger.info(
        "eval_simulation_backend_selected",
        backend=os.environ.get("SIMULATION_DEFAULT_BACKEND", "MUJOCO"),
        full_sim=args.full_sim,
    )
    logger.info(
        "eval_runner_backend_selected",
        backend=runner_backend.value,
        call_paid_api=args.call_paid_api,
        explicit_runner_backend=args.runner_backend,
        env_runner_backend=os.getenv(EVAL_RUNNER_BACKEND_ENV),
    )

    _emit_startup_log_pointers(current_link=current_link, root=ROOT)
    logger.info("eval_run_start", log_dir=str(log_dir))

    start_time = time.time()
    _console_message(f"Agent evals started: {time.ctime(start_time)}")

    if lock_lease.state is not None:
        lock_lease.update_state(current_phase="startup_checks")

    if runner_backend == EvalRunnerBackend.CONTROLLER and not args.skip_env_up:
        if lock_lease.state is not None:
            lock_lease.update_state(current_phase="env_up")
        logger.info("env_up_start")
        try:
            env_up_path = ROOT / "scripts" / "env_up.sh"
            env_up_log_dir = log_dir.relative_to(ROOT)
            result = subprocess.run(
                [str(env_up_path), "--profile", "eval"],
                check=True,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "LOG_DIR": str(env_up_log_dir),
                    "SKIP_LOG_ARCHIVE": "1",
                    "PROBLEMOLOGIST_EVAL_LOCK_HELD": "1",
                },
            )
            for line in result.stdout.splitlines():
                if line.strip():
                    logger.debug("env_up_output", line=line)
            logger.info("env_up_completed")
        except subprocess.CalledProcessError as e:
            logger.warning("env_up_failed", stdout=e.stdout, stderr=e.stderr)
            _console_message(f"ERROR: env_up.sh failed with exit code {e.returncode}")
            _console_message(
                f"Check logs for details: {_path_for_report(log_file, root=ROOT)}"
            )
            sys.exit(1)
        except Exception:
            logger.exception("env_up_exception")
            sys.exit(1)

    try:
        await asyncio.to_thread(
            fail_closed_if_integration_test_setup,
            CONTROLLER_URL,
            context="eval runner startup",
        )
    except SystemExit as exc:
        _console_message(str(exc))
        sys.exit(1)

    rate = Rate(50, Duration.MINUTE)
    limiter = Limiter(rate)
    available_agents = list(AGENT_SPECS.keys())

    requested_agent = args.agent
    if requested_agent != "all":
        try:
            requested_agent = AgentName(requested_agent)
        except ValueError:
            logger.error("unknown_agent", agent=requested_agent, session_id="eval")
            logger.info("available_agents")
            for name in available_agents:
                logger.info("agent", name=name)
            sys.exit(1)

    if requested_agent != "all" and requested_agent not in AGENT_SPECS:
        logger.error("agent_not_in_specs", agent=requested_agent, session_id="eval")
        sys.exit(1)

    if runner_backend == EvalRunnerBackend.CONTROLLER:
        logger.info("controller_health_check_start", url=CONTROLLER_URL)
        try:
            await _wait_for_controller_ready(CONTROLLER_URL)
        except Exception:
            logger.exception("controller_unreachable", url=CONTROLLER_URL)
            sys.exit(1)

        logger.info("worker_health_check_start", url=WORKER_LIGHT_URL)
        try:
            await _wait_for_worker_ready(WORKER_LIGHT_URL)
        except Exception:
            logger.exception("worker_unreachable", url=WORKER_LIGHT_URL)
            sys.exit(1)

    dataset_roots = [
        Path(__file__).parent / "datasets",
        ROOT / "dataset" / "data" / "seed" / "role_based",
    ]
    datasets = {}
    agents_to_run = available_agents if requested_agent == "all" else [requested_agent]
    reward_agent_configs = _load_agent_reward_configs()

    stats = {
        agent: {
            "total": 0,
            "success": 0,
            "total_cost_usd": 0.0,
            "costed_cases": 0,
            "electrical_validity_rate": 0.0,
            "wire_integrity_rate": 0.0,
            "power_efficiency_score": 0.0,
            "hard_checks": {},
            "judge_checks": {},
        }
        for agent in agents_to_run
    }

    for agent in agents_to_run:
        agent_val = agent.value if isinstance(agent, AgentName) else agent
        json_path = next(
            (
                root / f"{agent_val}.json"
                for root in dataset_roots
                if (root / f"{agent_val}.json").exists()
            ),
            None,
        )
        if json_path is not None:
            with json_path.open() as f:
                try:
                    data = json.load(f)
                    if selected_task_ids:
                        data = [
                            item for item in data if item["id"] in selected_task_ids
                        ]
                    if selected_levels:
                        data = [
                            item
                            for item in data
                            if item.get("complexity_level") in selected_levels
                        ]
                    if args.limit > 0:
                        if args.random:
                            data = random.sample(data, k=min(args.limit, len(data)))
                            logger.info(
                                "random_eval_selection",
                                agent=agent,
                                limit=args.limit,
                                selected_task_ids=[item["id"] for item in data],
                            )
                        else:
                            data = data[: args.limit]
                    seed_dataset = json_path.relative_to(ROOT)
                    datasets[agent] = [
                        EvalDatasetItem.model_validate(
                            {**item_raw, "seed_dataset": seed_dataset}
                        )
                        for item_raw in data
                    ]
                    if _requires_expected_review_decision(AGENT_SPECS[agent]):
                        missing_expectations = [
                            item.id
                            for item in datasets[agent]
                            if item.expected_decision is None
                        ]
                        if missing_expectations:
                            raise ValueError(
                                f"{agent.value} eval rows missing expected_decision: "
                                + ", ".join(missing_expectations)
                            )
                except json.JSONDecodeError:
                    logger.warning("dataset_json_decode_failed", path=str(json_path))
        else:
            logger.warning(
                "dataset_missing",
                agent=agent,
                searched_roots=[str(p) for p in dataset_roots],
            )

    tasks = []
    for agent, dataset in datasets.items():
        logger.info("agent_evals_start", agent=agent, count=len(dataset))
        for item in dataset:
            tasks.append((item, agent))

    if lock_lease.state is not None:
        lock_lease.update_state(current_phase="running")
        downgrade_eval_run_lock_to_shared(lock_lease)

    if tasks and runner_backend == EvalRunnerBackend.CONTROLLER:
        logger.info("eval_seed_preflight_start", total_tasks=len(tasks))
        try:
            await _preflight_selected_seeded_tasks(
                tasks=tasks,
                update_manifests=args.update_manifests,
            )
        except Exception as exc:
            logger.error("eval_seed_preflight_abort", error=str(exc))
            _console_message("ERROR: eval seeded preflight failed before execution.")
            _console_message(str(exc))
            sys.exit(1)
        logger.info("eval_seed_preflight_completed", total_tasks=len(tasks))
    elif tasks:
        logger.info(
            "eval_seed_preflight_skipped",
            total_tasks=len(tasks),
            runner_backend=runner_backend.value,
        )
    else:
        logger.warning("no_tasks_to_run")

    if tasks:
        semaphore = asyncio.Semaphore(max(1, args.concurrency))
        open_cli_ui_new_terminal = args.open_cli_ui and args.concurrency > 1

        async def _guarded(item: EvalDatasetItem, agent: AgentName):
            async with semaphore:
                if not args.no_rate_limit:
                    await asyncio.to_thread(limiter.try_acquire, "eval")
                await run_single_eval(
                    item,
                    agent,
                    stats,
                    reward_agent_configs,
                    verbose=args.verbose,
                    run_judge=args.run_judge,
                    run_reviewers_with_judge=args.run_reviewers_with_judge,
                    runner_backend=runner_backend,
                    update_manifests=args.update_manifests,
                    enable_skill_loop=args.codex_skill_loop,
                    provider_name=args.provider,
                    open_cli_ui=args.open_cli_ui,
                    open_cli_ui_new_terminal=open_cli_ui_new_terminal,
                )

        await asyncio.gather(*(_guarded(item, agent) for item, agent in tasks))

    logger.info("evaluation_report_start")

    total_pass = 0
    total_count = 0
    for agent, s in stats.items():
        if s["total"] == 0:
            continue

        success_rate = (s["success"] / s["total"]) * 100
        total_pass += s["success"]
        total_count += s["total"]

        log_report = logger.bind(agent=agent)
        log_report.info(
            "agent_summary",
            task_success_rate_pct=round(success_rate, 1),
            successful_tasks=s["success"],
            total_tasks=s["total"],
        )
        if s["costed_cases"] > 0:
            log_report.info(
                "agent_cost_summary",
                total_cost_usd=round(s["total_cost_usd"], 6),
                costed_cases=s["costed_cases"],
                avg_cost_per_case_usd=round(
                    s["total_cost_usd"] / s["costed_cases"],
                    6,
                ),
            )

    overall = (total_pass / total_count * 100) if total_count else 0.0
    logger.info(
        "overall_summary",
        overall_pass_rate_pct=round(overall, 1),
        passed_tasks=total_pass,
        total_tasks=total_count,
    )
    total_cost_usd = sum(float(s["total_cost_usd"]) for s in stats.values())
    total_costed_cases = sum(int(s["costed_cases"]) for s in stats.values())
    if total_costed_cases > 0:
        logger.info(
            "overall_cost_summary",
            total_cost_usd=round(total_cost_usd, 6),
            costed_cases=total_costed_cases,
            avg_cost_per_case_usd=round(total_cost_usd / total_costed_cases, 6),
        )

    agent_ran_cases: dict[AgentName, list[str]] = {
        agent: [item.id for item in datasets.get(agent, [])] for agent in agents_to_run
    }

    def _build_check_report(check_key: str, payload_key: str) -> dict[str, Any]:
        report: dict[str, Any] = {}
        for agent, agent_stats in stats.items():
            check_stats = agent_stats.get(check_key) or {}
            agent_key = agent.value if isinstance(agent, AgentName) else str(agent)
            ran_cases = agent_ran_cases.get(agent, [])
            checks_payload: dict[str, Any] = {}
            for check_name, raw in check_stats.items():
                total = int(raw.get("total", 0))
                passed = int(raw.get("passed", 0))
                failed_seeds = sorted(set(raw.get("failed_seeds", [])))
                pass_rate = round((passed / total) * 100) if total else 0
                check_payload: dict[str, Any] = {
                    "pass_rate": f"{pass_rate}%",
                    "passed": passed,
                    "total": total,
                    "failed_seeds": failed_seeds,
                }
                raw_failure_pointers = raw.get("failure_pointers")
                if isinstance(raw_failure_pointers, dict) and raw_failure_pointers:
                    ordered_pointers: dict[str, Any] = {}
                    for seed in failed_seeds:
                        if seed in raw_failure_pointers:
                            ordered_pointers[seed] = raw_failure_pointers[seed]
                    for seed in sorted(raw_failure_pointers):
                        if seed not in ordered_pointers:
                            ordered_pointers[seed] = raw_failure_pointers[seed]
                    check_payload["failure_pointers"] = ordered_pointers
                checks_payload[check_name] = check_payload
            report[agent_key] = {
                "ran_cases": ran_cases,
                payload_key: checks_payload,
            }
        return report

    hard_check_report = _build_check_report("hard_checks", "hard_checks")
    hard_check_report_path = log_dir / "hard_check_pass_rates.yaml"
    with hard_check_report_path.open("w", encoding="utf-8") as handle:
        import yaml

        yaml.safe_dump(
            hard_check_report,
            handle,
            sort_keys=True,
            allow_unicode=False,
            default_flow_style=False,
        )

    logger.info(
        "hard_check_report_written",
        path=str(hard_check_report_path),
        agents=list(hard_check_report.keys()),
    )

    if args.run_judge:
        judge_report = _build_check_report("judge_checks", "judge_checks")
        judge_report_path = log_dir / "judge_pass_rates.yaml"
        with judge_report_path.open("w", encoding="utf-8") as handle:
            import yaml

            yaml.safe_dump(
                judge_report,
                handle,
                sort_keys=True,
                allow_unicode=False,
                default_flow_style=False,
            )

        logger.info(
            "judge_report_written",
            path=str(judge_report_path),
            agents=list(judge_report.keys()),
            reviewers_enabled=args.run_reviewers_with_judge,
        )

    finish_time = time.time()
    duration = finish_time - start_time
    _console_message(f"Agent evals finished: {time.ctime(finish_time)}")
    _console_message(f"Total duration: {duration:.2f}s")
    logger.info("eval_run_finished", duration_s=round(duration, 2))


def run_cli() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _console_message("Agent evals interrupted.")


if __name__ == "__main__":
    run_cli()
