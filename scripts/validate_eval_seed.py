from __future__ import annotations

import argparse
import asyncio
import atexit
import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.logic.cli_provider import available_cli_providers  # noqa: E402
from evals.logic.dataset_selection import (  # noqa: E402
    parse_level_filters,
    resolve_agents_for,
)
from evals.logic.stack_profiles import apply_stack_profile_env  # noqa: E402
from scripts.internal.eval_run_lock import (  # noqa: E402
    EvalRunSelection,
    acquire_eval_run_lock,
    acquire_eval_run_shared_lock,
    downgrade_eval_run_lock_to_shared,
    release_eval_run_lock,
)
from scripts.internal.eval_seed_selection import (  # noqa: E402
    infer_seed_agent_for_task_id,
    load_seed_dataset,
    seed_dataset_agents,
)
from shared.enums import ResponseStatus  # noqa: E402

_STACK_PROFILE_NAME = (
    "integration"
    if os.getenv("IS_INTEGRATION_TEST", "").strip().lower() == "true"
    else "eval"
)
apply_stack_profile_env(_STACK_PROFILE_NAME, env=os.environ, root=ROOT)

from controller.agent.node_entry_validation import ValidationScope  # noqa: E402
from controller.clients.worker import WorkerClient  # noqa: E402
from evals.logic.curation import load_dataset_curation_manifest  # noqa: E402
from evals.logic.models import EvalDatasetItem  # noqa: E402
from evals.logic.specs import AGENT_SPECS  # noqa: E402
from evals.logic.workspace import (  # noqa: E402
    InMemorySeedWorkspaceClient,
    SeededEntryContractError,
    materialize_seed_workspace_snapshot,
)
from evals.logic.workspace import (
    preflight_seeded_entry_contract as _preflight_seeded_entry_contract,
)
from evals.logic.workspace import (  # noqa: E402
    resolve_seed_artifact_dir as _resolve_seed_artifact_dir,
)
from scripts.internal.eval_seed_renders import (  # noqa: E402
    update_seed_artifact_renders,
)
from shared.enums import AgentName, EvalRunnerBackend  # noqa: E402
from shared.logging import get_logger  # noqa: E402

WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://localhost:18001")
logger = get_logger(__name__)


class _QuietLogger:
    def __getattr__(self, _name: str):
        def _noop(*_args, **_kwargs):
            return None

        return _noop


QUIET_LOGGER = _QuietLogger()


def _format_failure_message(
    agent: str,
    task_id: str,
    detail: str | object,
) -> str:
    header = [f"FAIL {agent} {task_id}:"]
    if isinstance(detail, SeededEntryContractError):
        report = yaml.safe_dump(
            detail.report.model_dump(mode="json"),
            sort_keys=False,
        ).rstrip()
        return "\n".join(
            header + ["  report:"] + ["    " + line for line in report.splitlines()]
        )

    body = yaml.safe_dump(
        {"detail": str(detail)},
        sort_keys=False,
    ).rstrip()
    return "\n".join(
        header + ["  report:"] + ["    " + line for line in body.splitlines()]
    )


def _parse_runner_backend_arg(value: str) -> str:
    try:
        return EvalRunnerBackend(value).value
    except ValueError as exc:
        available = ", ".join(backend.value for backend in EvalRunnerBackend)
        raise argparse.ArgumentTypeError(
            f"Unknown eval runner backend {value!r}. Available: {available}"
        ) from exc


def _parse_validation_scope_arg(value: str) -> ValidationScope:
    try:
        return ValidationScope(value)
    except ValueError as exc:
        available = ", ".join(scope.value for scope in ValidationScope)
        raise argparse.ArgumentTypeError(
            f"Unknown validation scope {value!r}. Available: {available}"
        ) from exc


async def _wait_for_worker_ready(
    timeout_seconds: float = 60.0,
    poll_interval_seconds: float = 1.0,
    *,
    errors_only: bool = False,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    last_error: str | None = None
    temp_client = WorkerClient(base_url=WORKER_LIGHT_URL, session_id="healthcheck")

    while time.monotonic() < deadline:
        attempt += 1
        try:
            health = await temp_client.get_health()
            if health.status == ResponseStatus.HEALTHY:
                if not errors_only:
                    logger.info("worker_health_check_ok", attempts=attempt)
                return
            last_error = f"status={health.status}"
        except Exception as exc:
            last_error = str(exc)

        if not errors_only:
            logger.warning(
                "worker_health_check_retry", attempt=attempt, error=last_error
            )
        await asyncio.sleep(poll_interval_seconds)

    raise RuntimeError(
        "Worker did not become healthy within "
        f"{timeout_seconds}s. last_error={last_error}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate seeded eval entry contracts, including planner inventory "
            "exactness, workspace-contract alignment, and plan grounding "
            "without running full evals."
        )
    )
    parser.add_argument(
        "--agent",
        type=str,
        action="append",
        required=False,
        help=(
            "Agent dataset(s) to validate. Supports a single agent, repeated flags, "
            "comma-separated values, list syntax like [a,b], or 'or' separators. "
            "Use 'all' to run every seed-backed agent. Omit when --task-id is set "
            "to infer the matching agent automatically."
        ),
    )
    parser.add_argument(
        "--task-id",
        type=str,
        default=None,
        help="Validate only one specific task ID.",
    )
    parser.add_argument(
        "--level",
        action="append",
        default=None,
        help=(
            "Validate only evals at the selected complexity levels. Supports a "
            "single level, repeated flags, comma-separated values, or list syntax "
            "like [0,1]."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of rows per agent after task-id filtering.",
    )
    parser.add_argument(
        "--skip-env-up",
        action="store_true",
        help=(
            "Skip running scripts/env_up.sh before validation. Validation "
            "still joins the shared eval lock so the stack stays protected."
        ),
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help=(
            "Wait for the eval lock when this command is bootstrapping the "
            "eval stack or joining the shared validation lock instead of "
            "failing fast when another eval run is active."
        ),
    )
    parser.add_argument(
        "--update-manifests",
        dest="update_manifests",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Repair deterministic seed-manifest drift before validation "
            "(default: enabled). Seed validation still fails closed on "
            "inventory exactness, workspace-contract drift, or plan-grounding "
            "mismatches."
        ),
    )
    parser.add_argument(
        "--update-renders",
        dest="update_renders",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Deprecated compatibility alias. Regenerate deterministic seed "
            "render bundles before validation (default: disabled). Prefer "
            "scripts/update_eval_seed_renders.py for maintenance runs."
        ),
    )
    parser.add_argument(
        "--validation-scope",
        type=_parse_validation_scope_arg,
        default=ValidationScope.CURRENT_AND_PREVIOUS_NODES,
        help=(
            "Depth of seed validation to run. Default: "
            f"{ValidationScope.CURRENT_AND_PREVIOUS_NODES.value}."
        ),
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at the first invalid seed.",
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help=(
            "Suppress PASS/status output and validator success chatter. "
            "Useful for bulk inventory sweeps such as --agent all."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit a machine-readable validation summary as JSON. "
            "Incompatible with --run-judge."
        ),
    )
    parser.add_argument(
        "--run-judge",
        action="store_true",
        help=(
            "After validating the selected seeds, run the eval runner in judge "
            "mode to validate the seed quality itself."
        ),
    )
    parser.add_argument(
        "--judge-provider",
        type=str,
        default="qwen",
        choices=available_cli_providers(),
        help=("CLI provider to use for --run-judge follow-up evals (default: qwen)."),
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=(
            "Assume yes for expensive judge runs. Required when --run-judge is "
            "used with more than 10 selected seeds."
        ),
    )
    parser.add_argument(
        "--runner-backend",
        type=_parse_runner_backend_arg,
        default=EvalRunnerBackend.CLI.value,
        choices=[backend.value for backend in EvalRunnerBackend],
        help=(
            "Backend to use for --run-judge follow-up evals "
            f"(default: {EvalRunnerBackend.CLI.value})."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=16,
        help=(
            "Number of concurrent row validations. Ignored when --fail-fast is enabled."
        ),
    )
    return parser.parse_args()


def _build_session_id(agent: AgentName, task_id: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    return f"seed-check-{agent.value}-{task_id}-{suffix}"[:120]


def _load_json_mapping(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _load_yaml_mapping(path: Path) -> dict[str, object] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _validate_seed_row_metadata(
    agent: AgentName, item: EvalDatasetItem
) -> tuple[bool, str]:
    if agent == AgentName.ENGINEER_PLANNER:
        family_name = item.family_name.strip() if item.family_name else ""
        if not family_name:
            return False, (
                "engineer_planner rows must include a non-empty family_name field"
            )

    return True, "seed metadata valid"


def _resolve_workspace_dir(
    raw_workspace_dir: object, *, session_dir: Path | None = None
) -> Path | None:
    if not isinstance(raw_workspace_dir, str):
        return None
    workspace_dir = Path(raw_workspace_dir).expanduser()
    if workspace_dir.is_absolute():
        return workspace_dir.resolve()

    if session_dir is not None:
        candidate = (session_dir / workspace_dir).expanduser()
        if candidate.exists():
            return candidate.resolve()

    return (ROOT / workspace_dir).resolve()


def _latest_review_comments_path(
    *, workspace_dir: Path, agent: AgentName
) -> Path | None:
    review_prefix = AGENT_SPECS[agent].review_filename_prefix
    if not review_prefix:
        return None

    reviews_dir = workspace_dir / "reviews"
    if not reviews_dir.exists():
        return None

    comments_pattern = re.compile(
        rf"^{re.escape(review_prefix)}-comments-round-(\d+)\.yaml$"
    )
    latest_round = -1
    latest_path: Path | None = None

    for entry in reviews_dir.iterdir():
        if entry.is_dir():
            continue
        match = comments_pattern.fullmatch(entry.name)
        if match is None:
            continue
        round_number = int(match.group(1))
        if round_number > latest_round:
            latest_round = round_number
            latest_path = entry

    return latest_path


def _judge_failure_summary_lines(*, report_path: Path, agent_value: str) -> list[str]:
    report = _load_yaml_mapping(report_path)
    if not report:
        return []

    report_root = report_path.parent
    if agent_value == "all":
        agent_keys = sorted(report)
    else:
        agent_keys = [agent_value] if agent_value in report else []

    summary_lines: list[str] = []
    seen: set[tuple[str, str]] = set()

    for agent_key in agent_keys:
        payload = report.get(agent_key)
        if not isinstance(payload, dict):
            continue

        judge_checks = payload.get("judge_checks")
        if not isinstance(judge_checks, dict):
            continue

        failure_pointers: dict[str, object] = {}
        for check_payload in judge_checks.values():
            if not isinstance(check_payload, dict):
                continue
            raw_failure_pointers = check_payload.get("failure_pointers")
            if not isinstance(raw_failure_pointers, dict):
                continue
            for seed_id, pointer in raw_failure_pointers.items():
                if seed_id not in failure_pointers:
                    failure_pointers[seed_id] = pointer

        if not failure_pointers:
            failed_seeds: list[str] = []
            for check_payload in judge_checks.values():
                if not isinstance(check_payload, dict):
                    continue
                raw_failed_seeds = check_payload.get("failed_seeds")
                if isinstance(raw_failed_seeds, list):
                    for seed_id in raw_failed_seeds:
                        if isinstance(seed_id, str):
                            failed_seeds.append(seed_id)
            failure_pointers = {seed_id: {} for seed_id in sorted(set(failed_seeds))}

        try:
            agent_name = AgentName(agent_key)
        except ValueError:
            continue

        for seed_id in sorted(failure_pointers):
            cache_key = (agent_key, seed_id)
            if cache_key in seen:
                continue
            seen.add(cache_key)

            pointer = failure_pointers.get(seed_id)
            session_dir: Path | None = None
            if isinstance(pointer, dict):
                raw_session_dir = pointer.get("session_log_dir")
                if isinstance(raw_session_dir, str) and raw_session_dir.strip():
                    session_dir = (ROOT / raw_session_dir).resolve()

            workspace_dir: Path | None = None
            if session_dir is not None:
                metadata_path = session_dir / "session_metadata.json"
                metadata = _load_json_mapping(metadata_path)
                if metadata is not None:
                    workspace_dir = _resolve_workspace_dir(
                        metadata.get("workspace_dir"), session_dir=session_dir
                    )

            if workspace_dir is None:
                for metadata_path in report_root.rglob("session_metadata.json"):
                    metadata = _load_json_mapping(metadata_path)
                    if metadata is None:
                        continue
                    if str(metadata.get("task_id")) != seed_id:
                        continue
                    if (
                        agent_value != "all"
                        and str(metadata.get("agent_name")) != agent_key
                    ):
                        continue
                    workspace_dir = _resolve_workspace_dir(
                        metadata.get("workspace_dir"),
                        session_dir=metadata_path.parent,
                    )
                    if workspace_dir is not None:
                        break

            comments_path = (
                _latest_review_comments_path(
                    workspace_dir=workspace_dir, agent=agent_name
                )
                if workspace_dir is not None
                else None
            )

            if comments_path is None:
                fallback_path = (
                    workspace_dir / "reviews"
                    if workspace_dir is not None
                    else (session_dir or report_root)
                )
                comments_text = str(fallback_path.resolve())
            else:
                comments_text = str(comments_path.resolve())

            summary_lines.append(
                f'{seed_id}. Review comments can be found at "{comments_text}".'
            )

    return summary_lines


def _validate_generated_curation_manifests(*, errors_only: bool = False) -> list[Path]:
    manifest_paths = sorted(ROOT.glob("dataset/data/generated/*/v0.0.1/manifest.json"))
    validated: list[Path] = []
    for manifest_path in manifest_paths:
        manifest = load_dataset_curation_manifest(manifest_path)
        if not errors_only:
            logger.info(
                "generated_curation_manifest_validated",
                path=str(manifest_path),
                family=manifest.family,
                agent_target=manifest.agent_target,
                accepted=manifest.counts.accepted_after_pending_filter,
                rejected=manifest.counts.rejected,
            )
        validated.append(manifest_path)
    return validated


def _validation_json_payload(
    *,
    checked: int,
    results: list[dict[str, object]],
) -> dict[str, object]:
    failed = sum(1 for result in results if not bool(result.get("ok")))
    return {
        "checked": checked,
        "passed": checked - failed,
        "failed": failed,
        "results": results,
    }


async def _validate_item(
    agent: AgentName,
    item: EvalDatasetItem,
    *,
    update_manifests: bool,
    update_renders: bool,
    errors_only: bool = False,
    validation_scope: ValidationScope = ValidationScope.CURRENT_AND_PREVIOUS_NODES,
) -> tuple[bool, str | SeededEntryContractError]:
    session_id = _build_session_id(agent, item.id)
    spec = AGENT_SPECS[agent]
    item_logger = QUIET_LOGGER if errors_only else logger
    try:
        if update_renders and item.seed_artifact_dir is not None:
            artifact_dir = _resolve_seed_artifact_dir(item, root=ROOT)
            if artifact_dir is not None:
                update_seed_artifact_renders(artifact_dir)
        snapshot_client = InMemorySeedWorkspaceClient(session_id=session_id)
        await materialize_seed_workspace_snapshot(
            item=item,
            session_id=session_id,
            agent_name=agent,
            root=ROOT,
            workspace_client=snapshot_client,
            update_manifests=update_manifests,
        )
        await _preflight_seeded_entry_contract(
            item=item,
            session_id=session_id,
            agent_name=agent,
            spec=spec,
            root=ROOT,
            worker_light_url=WORKER_LIGHT_URL,
            logger=item_logger,
            workspace_client=snapshot_client,
            validation_scope=validation_scope,
        )
    except SeededEntryContractError as exc:
        return False, exc
    except Exception as exc:
        return False, str(exc)

    if item.seed_artifact_dir is None and not item.seed_files:
        return True, "prompt-only row; no seeded-entry contract required"
    return True, "seeded-entry contract valid"


def _run_env_up() -> None:
    env_up_path = ROOT / "scripts" / "env_up.sh"
    result = subprocess.run(
        [str(env_up_path), "--profile", "eval"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PROBLEMOLOGIST_EVAL_LOCK_HELD": "1"},
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        print(
            f"env_up.sh failed with exit code {result.returncode}.",
            file=sys.stderr,
        )
        raise SystemExit(result.returncode)


async def _async_main(args: argparse.Namespace) -> int:
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    if args.json and args.run_judge:
        raise SystemExit("--json cannot be combined with --run-judge.")
    if args.json:
        logging.disable(logging.CRITICAL)

    if args.agent:
        agents = resolve_agents_for(
            args.agent,
            available_agents=seed_dataset_agents(root=ROOT),
        )
    elif args.task_id:
        agents = [infer_seed_agent_for_task_id(args.task_id, root=ROOT)]
    else:
        raise SystemExit("Provide --agent or --task-id.")
    levels = parse_level_filters(args.level)
    if args.level and not levels:
        raise SystemExit("No valid --level values were parsed.")

    failures: list[tuple[str, str, str]] = []
    checked = 0
    work_items: list[tuple[AgentName, EvalDatasetItem]] = []
    json_results: list[dict[str, object]] = []

    for agent in agents:
        dataset = load_seed_dataset(
            agent,
            task_id=args.task_id,
            limit=args.limit,
            levels=levels if levels else None,
        )
        if args.task_id and not dataset:
            failures.append((agent.value, args.task_id, "task id not found in dataset"))
            if args.fail_fast:
                break
            continue
        for item in dataset:
            metadata_ok, metadata_detail = _validate_seed_row_metadata(agent, item)
            if not metadata_ok:
                checked += 1
                if not args.errors_only:
                    print(
                        _format_failure_message(agent.value, item.id, metadata_detail)
                    )
                failures.append((agent.value, item.id, metadata_detail))
                json_results.append(
                    {
                        "agent": agent.value,
                        "task_id": item.id,
                        "ok": False,
                        "detail": metadata_detail,
                    }
                )
                if args.fail_fast:
                    break
                continue
            work_items.append((agent, item))

        if args.fail_fast and failures:
            break

    if args.run_judge and not failures and len(work_items) > 10 and not args.yes:
        raise SystemExit(
            f"--run-judge selected {len(work_items)} seed rows; rerun with -y to "
            "confirm the extra judge cost."
        )

    lock_lease = None
    if not args.skip_env_up:
        lock_lease = acquire_eval_run_lock(
            queue=args.queue,
            requested_command=[sys.argv[0], *sys.argv[1:]],
            requested_selection=EvalRunSelection(
                agent=agents[0].value if len(agents) == 1 else None,
                task_ids=[args.task_id] if args.task_id else [],
                levels=sorted(levels) if levels else [],
            ),
        )
        if lock_lease is None:
            return 1
        atexit.register(release_eval_run_lock, lock_lease)
        if lock_lease.state is not None:
            lock_lease.update_state(current_phase="manifest_validation")
        try:
            _validate_generated_curation_manifests(errors_only=args.errors_only)
        except Exception as exc:
            print("Generated curation manifest validation failed.", file=sys.stderr)
            print(str(exc), file=sys.stderr)
            return 1

        if lock_lease.state is not None:
            lock_lease.update_state(current_phase="env_up")
        _run_env_up()
        if lock_lease.state is not None:
            lock_lease.update_state(current_phase="validation")
        # Keep the lock exclusive only through bootstrap, then let other
        # validation consumers join the shared lock on the same file.
        downgrade_eval_run_lock_to_shared(lock_lease)
    else:
        lock_lease = acquire_eval_run_shared_lock(
            queue=args.queue,
            requested_command=[sys.argv[0], *sys.argv[1:]],
            requested_selection=EvalRunSelection(
                agent=agents[0].value if len(agents) == 1 else None,
                task_ids=[args.task_id] if args.task_id else [],
                levels=sorted(levels) if levels else [],
            ),
        )
        if lock_lease is None:
            return 1
        atexit.register(release_eval_run_lock, lock_lease)
        try:
            _validate_generated_curation_manifests(errors_only=args.errors_only)
        except Exception as exc:
            print("Generated curation manifest validation failed.", file=sys.stderr)
            print(str(exc), file=sys.stderr)
            return 1

    if not args.skip_env_up:
        try:
            await _wait_for_worker_ready(errors_only=args.errors_only)
        except Exception as exc:
            print(
                "Worker is not healthy. Start the local services first if needed "
                "(for example `uv run dataset/evals/run_evals.py ...` or `./scripts/env_up.sh`).",
                file=sys.stderr,
            )
            print(str(exc), file=sys.stderr)
            return 1

    if not failures or not args.fail_fast:
        if args.fail_fast or args.concurrency == 1:
            for agent, item in work_items:
                checked += 1
                ok, detail = await _validate_item(
                    agent,
                    item,
                    update_manifests=args.update_manifests,
                    update_renders=args.update_renders,
                    errors_only=args.errors_only,
                    validation_scope=args.validation_scope,
                )
                if not ok:
                    print(_format_failure_message(agent.value, item.id, detail))
                    failures.append((agent.value, item.id, detail))
                elif not args.errors_only:
                    print(f"PASS {agent.value} {item.id}: {detail}")
                json_results.append(
                    {
                        "agent": agent.value,
                        "task_id": item.id,
                        "ok": ok,
                        "detail": str(detail),
                    }
                )
                if not ok and args.fail_fast:
                    break
        else:
            semaphore = asyncio.Semaphore(args.concurrency)

            async def _validate_with_semaphore(
                agent: AgentName, item: EvalDatasetItem
            ) -> tuple[AgentName, EvalDatasetItem, bool, str]:
                async with semaphore:
                    ok, detail = await _validate_item(
                        agent,
                        item,
                        update_manifests=args.update_manifests,
                        update_renders=args.update_renders,
                        errors_only=args.errors_only,
                        validation_scope=args.validation_scope,
                    )
                    return agent, item, ok, detail

            tasks = [
                asyncio.create_task(_validate_with_semaphore(agent, item))
                for agent, item in work_items
            ]
            for completed in asyncio.as_completed(tasks):
                agent, item, ok, detail = await completed
                checked += 1
                if not ok:
                    print(_format_failure_message(agent.value, item.id, detail))
                    failures.append((agent.value, item.id, detail))
                elif not args.errors_only:
                    print(f"PASS {agent.value} {item.id}: {detail}")
                json_results.append(
                    {
                        "agent": agent.value,
                        "task_id": item.id,
                        "ok": ok,
                        "detail": str(detail),
                    }
                )

    if checked == 0:
        if args.json:
            payload = _validation_json_payload(checked=0, results=[])
            payload["error"] = "No dataset rows matched the requested filter."
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("No dataset rows matched the requested filter.", file=sys.stderr)
        return 1

    if failures:
        if args.json:
            print(
                json.dumps(
                    _validation_json_payload(checked=checked, results=json_results),
                    indent=2,
                    sort_keys=True,
                )
            )
        elif not args.errors_only:
            print(
                f"Validated {checked} row(s): {checked - len(failures)} passed, {len(failures)} failed.",
                file=sys.stderr,
            )
        return 1

    if args.json:
        print(
            json.dumps(
                _validation_json_payload(checked=checked, results=json_results),
                indent=2,
                sort_keys=True,
            )
        )
    elif not args.errors_only:
        print(f"Validated {checked} row(s): all passed.")

    if args.run_judge:
        release_eval_run_lock(lock_lease)
        lock_lease = None

        judge_backend = EvalRunnerBackend(args.runner_backend)
        selected_agent_values = [agent.value for agent in agents]
        if len(selected_agent_values) == len(AGENT_SPECS):
            judge_agent_values = ["all"]
        else:
            judge_agent_values = selected_agent_values

        for agent_value in judge_agent_values:
            judge_command = [
                sys.executable,
                str(ROOT / "dataset" / "evals" / "run_evals.py"),
                "--skip-env-up",
                "--runner-backend",
                judge_backend.value,
                "--provider",
                args.judge_provider,
                "--run-judge",
                "--agent",
                agent_value,
                "--limit",
                str(args.limit),
            ]
            if args.task_id:
                judge_command.extend(["--task-id", args.task_id])
            for level in sorted(levels):
                judge_command.extend(["--level", str(level)])
            if args.queue:
                judge_command.append("--queue")
            if args.update_manifests:
                judge_command.append("--update-manifests")
            else:
                judge_command.append("--no-update-manifests")

            print(
                "Running judge evals for "
                f"{agent_value} via {judge_backend.value} backend "
                f"with {args.judge_provider} provider..."
            )
            result = subprocess.run(judge_command, check=False, cwd=ROOT)
            if result.returncode != 0:
                report_path = (
                    ROOT / "logs" / "evals" / "current" / "judge_pass_rates.yaml"
                )
                summary_lines = _judge_failure_summary_lines(
                    report_path=report_path,
                    agent_value=agent_value,
                )
                print("REVIEW FAILED!")
                if summary_lines:
                    print("Failed seeds:")
                    for line in summary_lines:
                        print(line)
                else:
                    print("Failed seeds: unavailable.")
                return result.returncode

    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
