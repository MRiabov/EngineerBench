#!/usr/bin/env python3
"""Create, review, and validate engineer_planner seed rows one row at a time.

This is the maintainer-side autopilot for the narrow task of building
`engineer_planner` corpus rows with process-level concurrency. Each worker
owns a single seed row, runs a seed-local authoring prompt in an isolated
worktree, refreshes the deterministic seed artifacts, runs the real seed
validator, and then runs a read-only review prompt before the relevant files
are copied back. Existing rows are skipped when the latest tracked run passed
review and validation; broken rows are repaired in place.

The outer orchestration is intentionally seed-granular. Multiple workers can
run at the same time, but each Codex CLI invocation handles only one seed at a
time so seed creation can stay complex without batching families together.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset.evals.materialize_seed_authoring_workspace import (  # noqa: E402
    materialize_seed_authoring_workspace as bootstrap_seed_authoring_workspace,
)
from evals.logic.cli_provider import (  # noqa: E402
    available_cli_providers,
    get_cli_provider,
)
from evals.logic.codex_workspace import (  # noqa: E402
    resolve_cli_home_root,
    sync_repo_venv,
)
from evals.logic.dataset_selection import (  # noqa: E402
    parse_level_filters,
    parse_task_id_filters,
)
from evals.logic.seed_maintenance import (  # noqa: E402
    refresh_seed_artifact_manifests,
)
from shared.enums import AgentName  # noqa: E402

DEFAULT_AGENT = AgentName.ENGINEER_PLANNER
DEFAULT_PROVIDER = "codex"
DEFAULT_SEED_WORKERS = 4
DEFAULT_AUTHOR_RETRIES = 1
DEFAULT_FAMILIES = [
    "gap_bridge",
    "central_bypass",
    "narrow_funnel",
    "lower_bin",
    "spiky_descent",
    "clearance_gate",
    "s_corridor",
    "terrain_ridge",
    "post_capture",
    "motion_aware",
]
DEFAULT_COMPLEXITY_BY_FAMILY = {
    "gap_bridge": 1,
    "central_bypass": 1,
    "narrow_funnel": 2,
    "lower_bin": 2,
    "spiky_descent": 2,
    "clearance_gate": 2,
    "s_corridor": 2,
    "terrain_ridge": 3,
    "post_capture": 3,
    "motion_aware": 4,
}
FAMILY_PLAN_REL = Path(
    "dataset/data/seed/artifacts/engineer_planner/engineer_planner_seed_family_plan.md"
)
DATASET_REL = Path("dataset/data/seed/role_based/engineer_planner.json")
ARTIFACT_ROOT_REL = Path("dataset/data/seed/artifacts/engineer_planner")
TASK_STATE_REL = Path("logs/evals/seed_update_autopilot/task_state.json")
CANONICAL_TASK_ID_RE = re.compile(r"^ep-(?P<family>[a-z-]+)-(?P<variant>\d{2})$")
SKIP_UNTRACKED_PREFIXES = (
    "logs/",
    ".tmp/",
    ".codex-runtime/",
    ".qwen-runtime/",
    "codex-runtime/",
    "qwen-runtime/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
)
_WORKTREE_LOCK = threading.Lock()
_APPLY_LOCK = threading.Lock()


@dataclass(slots=True)
class SeedSpec:
    task_id: str
    family: str
    variant: int
    complexity_level: int
    existing_row: bool


@dataclass(slots=True)
class AuthoringRun:
    task_id: str
    family: str
    variant: int
    command: list[str]
    prompt_path: str
    log_path: str
    returncode: int
    changed_task_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ValidationRun:
    task_id: str
    command: list[str]
    log_path: str
    returncode: int


@dataclass(slots=True)
class ReviewRun:
    task_id: str
    family: str
    variant: int
    command: list[str]
    prompt_path: str
    log_path: str
    returncode: int
    passed: bool
    notes: str = ""


@dataclass(slots=True)
class SeedRoundRun:
    round_index: int
    authoring_run: AuthoringRun | None = None
    validation_run: ValidationRun | None = None
    review_run: ReviewRun | None = None
    repair_note: str | None = None


@dataclass(slots=True)
class SeedJobRun:
    task_id: str
    family: str
    variant: int
    complexity_level: int
    existing_row: bool
    worktree_dir: str
    rounds: list[SeedRoundRun] = field(default_factory=list)
    changed_task_ids: list[str] = field(default_factory=list)
    introduced_paths: list[str] = field(default_factory=list)
    unexpected_paths: list[str] = field(default_factory=list)
    copied_back: bool = False
    success: bool = False
    failure_reason: str | None = None
    last_validation_passed: bool | None = None
    last_review_passed: bool | None = None
    bundle_fingerprint: str | None = None


@dataclass(slots=True)
class SeedTaskState:
    task_id: str
    bundle_fingerprint: str
    last_validation_passed: bool
    last_review_passed: bool
    source_run_started_at: str
    source_run_finished_at: str | None
    recorded_at: str


@dataclass(slots=True)
class AutopilotSummary:
    started_at: str
    finished_at: str | None
    provider: str
    seed_workers: int
    author_retries: int
    families: list[str]
    requested_task_ids: list[str]
    selected_task_ids: list[str]
    skipped_existing_task_ids: list[str]
    completed_task_ids: list[str]
    failed_task_ids: list[str]
    dry_run: bool
    validate_only: bool
    authoring_enabled: bool
    seed_jobs: list[SeedJobRun] = field(default_factory=list)
    success: bool = False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create or repair engineer_planner seed rows with one Codex CLI "
            "per seed and process-level concurrency."
        )
    )
    parser.add_argument(
        "--author",
        action="store_true",
        help=(
            "Run the seed-authoring loop. The worker creates or repairs one "
            "seed row at a time, then validates and reviews that seed in the "
            "same isolated worktree."
        ),
    )
    parser.add_argument(
        "--family",
        action="append",
        choices=DEFAULT_FAMILIES,
        default=None,
        help="Restrict the run to one or more seed families.",
    )
    parser.add_argument(
        "--task-id",
        action="append",
        default=None,
        help=(
            "Restrict the run to one or more canonical task ids. Supports "
            "repeated flags, comma-separated values, or list syntax."
        ),
    )
    parser.add_argument(
        "--level",
        action="append",
        default=None,
        help=(
            "Restrict the run to selected complexity levels. Supports "
            "repeated flags, comma-separated values, or list syntax."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit the number of selected seeds after filtering.",
    )
    parser.add_argument(
        "--provider",
        choices=available_cli_providers(),
        default=DEFAULT_PROVIDER,
        help="CLI provider used for both authoring and review prompts.",
    )
    parser.add_argument(
        "--seed-workers",
        type=int,
        default=DEFAULT_SEED_WORKERS,
        help=(
            "Number of concurrent per-seed workers. Each worker owns one "
            "seed job and may launch multiple Codex CLI prompts sequentially."
        ),
    )
    parser.add_argument(
        "--author-retries",
        type=int,
        default=DEFAULT_AUTHOR_RETRIES,
        help=(
            "Maximum extra repair rounds per seed after the initial "
            "author -> refresh -> validate -> review pass."
        ),
    )
    parser.add_argument(
        "--skip-env-up",
        action="store_true",
        help=(
            "Assume the eval stack is already running. When omitted, the "
            "script bootstraps the eval stack once before workers start."
        ),
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="Wait for shared eval locks instead of failing fast.",
    )
    parser.add_argument(
        "--validation-scope",
        type=str,
        default="current-and-previous-nodes",
        help="Validation scope forwarded to scripts/validate_eval_seed.py.",
    )
    parser.add_argument(
        "--update-manifests",
        dest="update_manifests",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refresh deterministic seed manifests during maintenance.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help=(
            "Skip the review prompt after deterministic validation. This is "
            "useful when you only want to refresh and validate the seeds."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned commands without executing them.",
    )
    parser.add_argument(
        "--persist-results",
        dest="persist_results",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Copy successful outputs back into the seed corpus after the "
            "normal validation and review gates. Use --no-persist-results "
            "to keep the run artifacts only."
        ),
    )
    return parser.parse_args()


def _sanitize_slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-") or "item"


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _tail_lines(path: Path, *, limit: int = 80) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    if len(lines) <= limit:
        return "\n".join(lines).strip()
    return "\n".join(lines[-limit:]).strip()


def _dataset_roots(root: Path) -> tuple[Path, ...]:
    configured_roots = os.getenv("PROBLEMOLOGIST_SEED_DATASET_ROOTS", "").strip()
    if configured_roots:
        roots: list[Path] = []
        seen: set[Path] = set()
        for raw_root in configured_roots.split(os.pathsep):
            raw_root = raw_root.strip()
            if not raw_root:
                continue
            dataset_root = Path(raw_root).expanduser()
            if not dataset_root.is_absolute():
                dataset_root = root / dataset_root
            if dataset_root in seen:
                continue
            seen.add(dataset_root)
            roots.append(dataset_root)
        return tuple(roots)
    return (
        root / "dataset" / "evals" / "datasets",
        root / "dataset" / "data" / "seed" / "role_based",
    )


def _seed_dataset_path_for_agent(root: Path, agent: AgentName) -> Path | None:
    for dataset_root in _dataset_roots(root):
        candidate = dataset_root / f"{agent.value}.json"
        if candidate.exists():
            return candidate
    return None


def _load_raw_seed_rows(
    root: Path, agent: AgentName
) -> tuple[Path, list[dict[str, object]]]:
    json_path = _seed_dataset_path_for_agent(root, agent)
    if json_path is None:
        searched = ", ".join(str(path) for path in _dataset_roots(root))
        raise FileNotFoundError(
            f"Dataset for agent '{agent.value}' not found. Searched: {searched}"
        )
    with json_path.open(encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise ValueError(f"Dataset file is not a JSON list: {json_path}")
    return json_path, rows


def _task_state_path(root: Path) -> Path:
    return root / TASK_STATE_REL


def _load_seed_row_context(task_id: str) -> tuple[str | None, str | None]:
    _, rows = _load_raw_seed_rows(ROOT, DEFAULT_AGENT)
    row = next((entry for entry in rows if entry.get("id") == task_id), None)
    if not isinstance(row, dict):
        return None, None

    task_text = row.get("task")
    if not isinstance(task_text, str) or not task_text.strip():
        return None, None

    criteria_text = row.get("expected_criteria")
    if not isinstance(criteria_text, str) or not criteria_text.strip():
        return None, None

    return task_text.strip(), criteria_text.strip()


def _row_id_map(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    mapped: dict[str, dict[str, object]] = {}
    for row in rows:
        task_id = row.get("id")
        if isinstance(task_id, str) and task_id:
            mapped[task_id] = row
    return mapped


def _seed_bundle_fingerprint(root: Path, task_id: str) -> str:
    digest = hashlib.sha256()

    _, rows = _load_raw_seed_rows(root, DEFAULT_AGENT)
    row = next((entry for entry in rows if entry.get("id") == task_id), None)
    if isinstance(row, dict):
        digest.update(
            json.dumps(
                row, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        )
        digest.update(b"\0")

    artifact_dir = root / ARTIFACT_ROOT_REL / task_id
    if artifact_dir.exists():
        for path in sorted(
            (candidate for candidate in artifact_dir.rglob("*") if candidate.is_file()),
            key=lambda candidate: candidate.relative_to(artifact_dir).as_posix(),
        ):
            rel_path = path.relative_to(artifact_dir).as_posix()
            digest.update(rel_path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")

    return digest.hexdigest()


def _diff_changed_task_ids(
    before_rows: list[dict[str, object]],
    after_rows: list[dict[str, object]],
) -> list[str]:
    before = _row_id_map(before_rows)
    after = _row_id_map(after_rows)
    changed = set(after.keys()) ^ set(before.keys())
    for task_id, after_row in after.items():
        if before.get(task_id) != after_row:
            changed.add(task_id)
    return sorted(changed)


def _level_for_family(family: str) -> int:
    return DEFAULT_COMPLEXITY_BY_FAMILY[family]


def _validate_existing_seed_row(
    *,
    task_id: str,
    queue: bool,
    validation_scope: str,
) -> bool:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "validate_eval_seed.py"),
        "--skip-env-up",
        "--agent",
        DEFAULT_AGENT.value,
        "--task-id",
        task_id,
        "--fail-fast",
        "--concurrency",
        "1",
        "--errors-only",
        "--json",
        "--validation-scope",
        validation_scope,
    ]
    if queue:
        command.append("--queue")

    env = dict(os.environ)
    env["LOG_LEVEL"] = "ERROR"

    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in (0, 1):
        return False

    try:
        payload = _parse_trailing_json_payload(completed.stdout)
    except ValueError:
        return False

    results = payload.get("results")
    if not isinstance(results, list):
        return False

    for result in results:
        if not isinstance(result, dict):
            continue
        if result.get("task_id") == task_id:
            return bool(result.get("ok"))
    return False


def _parse_trailing_json_payload(stdout: str) -> dict[str, object]:
    lines = stdout.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip() != "{":
            continue
        payload_text = "\n".join(lines[index:])
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("No trailing JSON payload found in validator output")


def _seed_task_state_from_json(
    task_id: str, payload: dict[str, object]
) -> SeedTaskState:
    return SeedTaskState(
        task_id=task_id,
        bundle_fingerprint=str(payload["bundle_fingerprint"]),
        last_validation_passed=bool(payload["last_validation_passed"]),
        last_review_passed=bool(payload["last_review_passed"]),
        source_run_started_at=str(payload["source_run_started_at"]),
        source_run_finished_at=(
            None
            if payload.get("source_run_finished_at") in {None, ""}
            else str(payload["source_run_finished_at"])
        ),
        recorded_at=str(payload["recorded_at"]),
    )


def _seed_task_state_to_json(state: SeedTaskState) -> dict[str, object]:
    return {
        "task_id": state.task_id,
        "bundle_fingerprint": state.bundle_fingerprint,
        "last_validation_passed": state.last_validation_passed,
        "last_review_passed": state.last_review_passed,
        "source_run_started_at": state.source_run_started_at,
        "source_run_finished_at": state.source_run_finished_at,
        "recorded_at": state.recorded_at,
    }


def _load_seed_task_state(root: Path) -> dict[str, SeedTaskState]:
    state_path = _task_state_path(root)
    if state_path.exists():
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            states: dict[str, SeedTaskState] = {}
            for task_id, raw_state in payload.items():
                if not isinstance(task_id, str) or not isinstance(raw_state, dict):
                    continue
                try:
                    states[task_id] = _seed_task_state_from_json(task_id, raw_state)
                except Exception:
                    continue
            return states

    migrated = _migrate_seed_task_state_from_summaries(root)
    if migrated:
        _write_seed_task_state(root, migrated)
    return migrated


def _migrate_seed_task_state_from_summaries(root: Path) -> dict[str, SeedTaskState]:
    runs_root = root / "logs" / "evals" / "seed_update_autopilot" / "runs"
    if not runs_root.exists():
        return {}

    migrated: dict[str, SeedTaskState] = {}
    for summary_path in runs_root.glob("*/seed_update_autopilot_summary.json"):
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        started_at = str(payload.get("started_at") or "")
        finished_at = payload.get("finished_at")
        finished_at_text = None if finished_at in {None, ""} else str(finished_at)
        seed_jobs = payload.get("seed_jobs")
        if not isinstance(seed_jobs, list):
            continue

        for job in seed_jobs:
            if not isinstance(job, dict):
                continue
            task_id = job.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                continue
            if not bool(job.get("success")):
                continue
            try:
                fingerprint = _seed_bundle_fingerprint(root, task_id)
            except Exception:
                continue
            migrated[task_id] = SeedTaskState(
                task_id=task_id,
                bundle_fingerprint=fingerprint,
                last_validation_passed=bool(job.get("last_validation_passed", True)),
                last_review_passed=bool(job.get("last_review_passed", True)),
                source_run_started_at=started_at,
                source_run_finished_at=finished_at_text,
                recorded_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            )
    return migrated


def _write_seed_task_state(root: Path, states: dict[str, SeedTaskState]) -> None:
    state_path = _task_state_path(root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        task_id: _seed_task_state_to_json(state)
        for task_id, state in sorted(states.items())
    }
    state_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _latest_seed_job_success(task_id: str) -> bool | None:
    runs_root = ROOT / "logs" / "evals" / "seed_update_autopilot" / "runs"
    if not runs_root.exists():
        return None

    latest_started_at = ""
    latest_mtime = -1.0
    latest_success: bool | None = None

    for summary_path in runs_root.glob("*/seed_update_autopilot_summary.json"):
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        started_at = str(payload.get("started_at") or "")
        try:
            mtime = summary_path.stat().st_mtime
        except OSError:
            mtime = -1.0

        seed_jobs = payload.get("seed_jobs")
        if not isinstance(seed_jobs, list):
            continue

        for job in seed_jobs:
            if not isinstance(job, dict):
                continue
            if job.get("task_id") != task_id:
                continue
            if started_at > latest_started_at or (
                started_at == latest_started_at and mtime > latest_mtime
            ):
                latest_started_at = started_at
                latest_mtime = mtime
                latest_success = bool(job.get("success"))

    return latest_success


def _existing_seed_needs_repair(
    *,
    task_id: str,
    queue: bool,
    validation_scope: str,
) -> bool:
    if not _validate_existing_seed_row(
        task_id=task_id,
        queue=queue,
        validation_scope=validation_scope,
    ):
        return True

    latest_success = _latest_seed_job_success(task_id)
    return latest_success is not True


def _canonical_seed_specs(
    *,
    root: Path,
    families: list[str],
    task_ids: set[str] | None,
    levels: set[int] | None,
    limit: int,
    queue: bool,
    validation_scope: str,
    task_state: dict[str, SeedTaskState],
) -> tuple[list[SeedSpec], list[str]]:
    _, rows = _load_raw_seed_rows(root, DEFAULT_AGENT)
    existing_ids = set(_row_id_map(rows))

    candidate_specs: list[SeedSpec] = []
    skipped_existing: list[str] = []
    requested_ids = set(task_ids or set())
    explicit_ids = bool(requested_ids)
    requested_seen: set[str] = set()

    for family in families:
        for variant in range(1, 11):
            task_id = f"ep-{family.replace('_', '-')}-{variant:02d}"
            if requested_ids and task_id not in requested_ids:
                continue
            complexity_level = _level_for_family(family)
            if levels and complexity_level not in levels:
                continue
            existing_row = task_id in existing_ids
            if explicit_ids:
                requested_seen.add(task_id)
            if existing_row:
                current_fingerprint = _seed_bundle_fingerprint(root, task_id)
                state = task_state.get(task_id)
                if (
                    state is not None
                    and state.bundle_fingerprint == current_fingerprint
                    and state.last_validation_passed
                    and state.last_review_passed
                ):
                    skipped_existing.append(task_id)
                    continue
                if _existing_seed_needs_repair(
                    task_id=task_id,
                    queue=queue,
                    validation_scope=validation_scope,
                ):
                    candidate_specs.append(
                        SeedSpec(
                            task_id=task_id,
                            family=family,
                            variant=variant,
                            complexity_level=complexity_level,
                            existing_row=True,
                        )
                    )
                else:
                    skipped_existing.append(task_id)
                continue
            candidate_specs.append(
                SeedSpec(
                    task_id=task_id,
                    family=family,
                    variant=variant,
                    complexity_level=complexity_level,
                    existing_row=False,
                )
            )
    if not candidate_specs:
        if requested_ids and not requested_seen:
            missing = sorted(requested_ids)
            raise SystemExit(
                "Unknown canonical engineer_planner task id(s): " + ", ".join(missing)
            )
        return [], skipped_existing

    selected: list[SeedSpec] = []
    for spec in candidate_specs:
        selected.append(spec)
        if limit > 0 and len(selected) >= limit:
            break

    if requested_ids:
        missing = sorted(requested_ids - requested_seen)
        if missing:
            raise SystemExit(
                "Unknown canonical engineer_planner task id(s): " + ", ".join(missing)
            )

    return selected, skipped_existing


def _prepare_run_dir() -> Path:
    root = ROOT / "logs" / "evals" / "seed_update_autopilot"
    runs_root = root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    base_name = f"run_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = runs_root / base_name
    suffix = 1
    while run_dir.exists():
        run_dir = runs_root / f"{base_name}_{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True, exist_ok=True)

    current_link = root / "current"
    if current_link.exists() or current_link.is_symlink():
        current_link.unlink()
    current_link.symlink_to(run_dir.relative_to(root))
    return run_dir


def _run_git(
    root: Path, args: list[str], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def _upsert_seed_row(rows: list[dict[str, object]], row: dict[str, object]) -> None:
    row_id = row.get("id")
    if not isinstance(row_id, str) or not row_id.strip():
        raise RuntimeError("Seed row is missing an id")
    for index, existing in enumerate(rows):
        if existing.get("id") == row_id:
            rows[index] = row
            return
    rows.append(row)


def _materialize_seed_worktree(
    *,
    root: Path,
    worktree_dir: Path,
    spec: SeedSpec,
    root_rows: list[dict[str, object]],
) -> None:
    with _WORKTREE_LOCK:
        if worktree_dir.exists():
            shutil.rmtree(worktree_dir)
        worktree_dir.parent.mkdir(parents=True, exist_ok=True)
        create_proc = _run_git(
            root, ["worktree", "add", "--detach", str(worktree_dir), "HEAD"]
        )
        if create_proc.returncode != 0:
            raise RuntimeError(
                create_proc.stderr or create_proc.stdout or "git worktree add failed"
            )

    if spec.existing_row:
        root_row = next(
            (row for row in root_rows if row.get("id") == spec.task_id), None
        )
        if isinstance(root_row, dict):
            # Only carry the target row across. The worktree stays clean for every
            # unrelated file so repairs are local to this seed.
            dataset_path = worktree_dir / DATASET_REL
            with dataset_path.open(encoding="utf-8") as handle:
                worktree_rows = json.load(handle)
            if not isinstance(worktree_rows, list):
                raise RuntimeError(f"Seed dataset is not a list: {dataset_path}")
            _upsert_seed_row(worktree_rows, root_row)
            dataset_path.write_text(
                json.dumps(worktree_rows, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        source_artifact_dir = root / ARTIFACT_ROOT_REL / spec.task_id
        destination_artifact_dir = worktree_dir / ARTIFACT_ROOT_REL / spec.task_id
        if source_artifact_dir.exists():
            if destination_artifact_dir.exists():
                shutil.rmtree(destination_artifact_dir)
            destination_artifact_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_artifact_dir, destination_artifact_dir)
        sync_repo_venv(worktree_dir)
    else:
        bootstrap_seed_authoring_workspace(
            agent=DEFAULT_AGENT,
            task_id=spec.task_id,
            output_dir=str(worktree_dir),
        )


def _cleanup_worktree(root: Path, worktree_dir: Path) -> None:
    if not worktree_dir.exists():
        return
    with _WORKTREE_LOCK:
        remove_proc = _run_git(
            root, ["worktree", "remove", "--force", str(worktree_dir)]
        )
        if remove_proc.returncode == 0:
            return
        shutil.rmtree(worktree_dir, ignore_errors=True)
        _run_git(root, ["worktree", "prune"])


def _git_status_paths(root: Path) -> set[str]:
    proc = _run_git(root, ["status", "--porcelain=v1", "--untracked-files=all"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "git status failed")
    paths: set[str] = set()
    for raw_line in proc.stdout.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if len(line) < 4:
            continue
        path = line[3:]
        if "->" in path:
            path = path.split("->", 1)[1].strip()
        paths.add(path)
    return paths


def _build_authoring_prompt(
    spec: SeedSpec,
    *,
    repair_note: str | None = None,
) -> str:
    task_text, criteria_text = _load_seed_row_context(spec.task_id)
    mode = "repair" if spec.existing_row else "create"
    parts = [
        "$eval-creation-workflow",
        "",
        f"{mode.title()} exactly one engineer_planner seed row.",
        "",
        "Target:",
        f"- task_id: {spec.task_id}",
        f"- family: {spec.family}",
        f"- variant: {spec.variant:02d}",
        f"- complexity_level: {spec.complexity_level}",
        f"- dataset row: {DATASET_REL.as_posix()}",
        f"- artifact dir: {(ARTIFACT_ROOT_REL / spec.task_id).as_posix()}",
        "",
        "Use .agents/skills/engineer-planner and .agents/skills/engineer-coder "
        "as the primary manuals for the engineer_planner workspace.",
        "Use .agents/skills/benchmark-planner, .agents/skills/benchmark-coder, "
        "and .agents/skills/benchmark-reviewer to ground and audit the "
        "benchmark-side context embedded in the seed artifact dir.",
        "",
        f"Family plan source of truth: {FAMILY_PLAN_REL.as_posix()}",
        "",
    ]
    if not spec.existing_row:
        parts.extend(
            [
                "Bootstrap state:",
                "- This workspace was initialized by "
                "`dataset/evals/materialize_seed_authoring_workspace.py`.",
                "- The workspace skeleton, current-role manifest, and "
                "workspace-local `.venv` link are already present.",
                "",
            ]
        )
    parts.extend(
        [
            "Rules:",
            "- Modify only dataset/data/seed/role_based/engineer_planner.json and "
            "the target artifact directory.",
            "- Repair the existing seed in place when a previous round failed; do "
            "not restart from scratch or switch to a different task id.",
            "- If seeds from the same family prefix already exist, you may reuse their broad family pattern and variation knobs, but do not clone the layout or make cosmetic changes; the new benchmark must be materially distorted and clearly distinct so the corpus stays high quality.",
            "- Keep `seed_artifact_dir` stable and pointing at the canonical "
            "artifact directory for this task id.",
            "- Keep benchmark-owned context read-only and exact-grounded.",
            "- Do not run validation, render, or judge helpers. The maintainer "
            "driver handles those steps.",
            "- Do not touch unrelated files.",
        ]
    )
    if task_text and criteria_text:
        parts.extend(
            [
                "Row contract snapshot:",
                f"- task: {task_text}",
                f"- expected_criteria: {criteria_text}",
                "",
            ]
        )
    parts.extend(
        [
            "Self-check before editing:",
            "- `.manifests/current_role.json` must name `engineer_planner`.",
            "- `seed_artifact_dir` must stay stable for this task id.",
            "- benchmark-owned files stay read-only and exact-grounded.",
            "- every role, object, and payload label in the task or criteria must "
            "remain exact-grounded; do not substitute generic names.",
            "",
        ]
    )
    if repair_note:
        parts.extend(
            [
                "",
                "Repair note from the previous round:",
                repair_note.strip(),
            ]
        )
    return "\n".join(parts).strip() + "\n"


def _build_review_prompt(
    spec: SeedSpec,
    *,
    validation_tail: str,
    repair_note: str | None = None,
) -> str:
    task_text, criteria_text = _load_seed_row_context(spec.task_id)
    parts = [
        "$engineer-plan-reviewer",
        "",
        f"Review the engineer_planner seed row {spec.task_id} and its artifact "
        f"dir {(ARTIFACT_ROOT_REL / spec.task_id).as_posix()}.",
        "",
        "Use .agents/skills/engineer-plan-reviewer as the primary checklist lens.",
        "Treat the family plan at "
        f"{FAMILY_PLAN_REL.as_posix()} as the source of truth for family "
        "shape, variant progression, and row naming.",
        "Inspect dataset/data/seed/role_based/engineer_planner.json, the "
        "target artifact dir, and the validation evidence in this workspace.",
        "Judge the seed against the row contract and stored corpus only.",
        "If seeds from the same family prefix already exist, you may reuse their broad family pattern and variation knobs, but do not clone the layout or make cosmetic changes; the new benchmark must be materially distorted and clearly distinct so the corpus stays high quality.",
        "",
        "Validation tail:",
        validation_tail or "(no validation output)",
        "",
        "Do not edit files.",
        "Return exactly this format:",
        "REVIEW_RESULT: PASS",
        "REVIEW_NOTES: ...",
        "",
        "or",
        "",
        "REVIEW_RESULT: FAIL",
        "REVIEW_NOTES:",
        "- ...",
    ]
    if task_text and criteria_text:
        parts.extend(
            [
                "",
                "Row contract snapshot:",
                f"- task: {task_text}",
                f"- expected_criteria: {criteria_text}",
            ]
        )
    parts.extend(
        [
            "",
            "Review checklist:",
            "- `.manifests/current_role.json` names `engineer_planner`.",
            "- the seeded workspace matches the row's artifact directory exactly.",
            "- benchmark-owned files remain read-only and exact-grounded.",
            "- role/object/payload labels match the row contract without generic "
            "substitutions.",
        ]
    )
    if repair_note:
        parts.extend(
            [
                "",
                "Repair note from the previous round:",
                repair_note.strip(),
            ]
        )
    return "\n".join(parts).strip() + "\n"


def _run_cli_prompt(
    *,
    provider_name: str,
    agent_name: AgentName,
    task_id: str,
    workspace_dir: Path,
    prompt_text: str,
    prompt_path: Path,
    log_path: Path,
    run_dir: Path,
    session_prefix: str,
    dry_run: bool,
) -> tuple[int, list[str]]:
    provider = get_cli_provider(provider_name)
    session_id = (
        f"{session_prefix}-{_sanitize_slug(task_id)}-{time.strftime('%Y%m%d_%H%M%S')}"
    )
    codex_home_root = resolve_cli_home_root(
        task_id=task_id,
        session_id=session_id,
        runtime_root=run_dir / "codex-runtime",
        provider_name=provider_name,
    )
    provider.prepare_home(
        codex_home_root=codex_home_root,
        workspace_dir=workspace_dir,
        agent_name=agent_name,
    )
    invocation = provider.build_exec_invocation(
        workspace_dir=workspace_dir,
        prompt_text=prompt_text,
        yolo=True,
    )
    merged_env = provider.build_env(
        task_id=task_id,
        workspace_dir=workspace_dir,
        codex_home_root=codex_home_root,
        session_id=session_id,
        agent_name=agent_name,
    )
    merged_env.update(invocation.env_overrides)

    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt_text, encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        log_path.write_text(
            "DRY RUN: " + _format_command(invocation.argv) + "\n\n" + prompt_text,
            encoding="utf-8",
        )
        return 0, invocation.argv

    stdin_text = (
        invocation.prompt_text if invocation.prompt_transport == "stdin" else None
    )
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(f"$ {_format_command(invocation.argv)}\n")
        handle.write("\n")
        handle.flush()
        completed = subprocess.run(
            invocation.argv,
            input=stdin_text,
            text=True,
            cwd=str(invocation.cwd)
            if invocation.cwd is not None
            else str(workspace_dir),
            env=merged_env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
        handle.write(f"\n[exit {completed.returncode}]\n")
        handle.flush()
    return completed.returncode, invocation.argv


def _run_authoring_prompt(
    *,
    spec: SeedSpec,
    provider_name: str,
    workspace_dir: Path,
    run_dir: Path,
    round_dir: Path,
    dry_run: bool,
    repair_note: str | None = None,
) -> AuthoringRun:
    prompt_text = _build_authoring_prompt(spec, repair_note=repair_note)
    prompt_path = round_dir / "authoring.prompt.md"
    log_path = round_dir / "authoring.log"
    rc, command = _run_cli_prompt(
        provider_name=provider_name,
        agent_name=AgentName.ENGINEER_PLANNER,
        task_id=spec.task_id,
        workspace_dir=workspace_dir,
        prompt_text=prompt_text,
        prompt_path=prompt_path,
        log_path=log_path,
        run_dir=run_dir,
        session_prefix="seed-authoring",
        dry_run=dry_run,
    )
    return AuthoringRun(
        task_id=spec.task_id,
        family=spec.family,
        variant=spec.variant,
        command=command,
        prompt_path=str(prompt_path),
        log_path=str(log_path),
        returncode=rc,
    )


def _run_review_prompt(
    *,
    spec: SeedSpec,
    provider_name: str,
    workspace_dir: Path,
    run_dir: Path,
    round_dir: Path,
    validation_tail: str,
    dry_run: bool,
    repair_note: str | None = None,
) -> ReviewRun:
    prompt_text = _build_review_prompt(
        spec,
        validation_tail=validation_tail,
        repair_note=repair_note,
    )
    prompt_path = round_dir / "review.prompt.md"
    log_path = round_dir / "review.log"
    rc, command = _run_cli_prompt(
        provider_name=provider_name,
        agent_name=AgentName.ENGINEER_PLAN_REVIEWER,
        task_id=f"review-{spec.task_id}",
        workspace_dir=workspace_dir,
        prompt_text=prompt_text,
        prompt_path=prompt_path,
        log_path=log_path,
        run_dir=run_dir,
        session_prefix="seed-review",
        dry_run=dry_run,
    )
    review_output = ""
    if log_path.exists():
        review_output = log_path.read_text(encoding="utf-8")
    if dry_run:
        passed = True
        notes = "dry run"
    else:
        passed = False
        notes = ""
        result_matches = list(
            re.finditer(
                r"^REVIEW_RESULT:\s*(PASS|FAIL)\s*$", review_output, re.MULTILINE
            )
        )
        if result_matches:
            passed = result_matches[-1].group(1).upper() == "PASS"
        notes_matches = list(
            re.finditer(r"^REVIEW_NOTES:\s*", review_output, re.MULTILINE)
        )
        if notes_matches:
            notes = review_output[notes_matches[-1].end() :].strip()
        elif review_output.strip():
            notes = review_output.strip()
    return ReviewRun(
        task_id=spec.task_id,
        family=spec.family,
        variant=spec.variant,
        command=command,
        prompt_path=str(prompt_path),
        log_path=str(log_path),
        returncode=rc,
        passed=passed and rc == 0,
        notes=notes,
    )


def _run_validation(
    *,
    spec: SeedSpec,
    workspace_dir: Path,
    run_dir: Path,
    queue: bool,
    update_manifests: bool,
    validation_scope: str,
    dry_run: bool,
) -> ValidationRun:
    command = [
        sys.executable,
        str(workspace_dir / "scripts" / "validate_eval_seed.py"),
        "--agent",
        DEFAULT_AGENT.value,
        "--task-id",
        spec.task_id,
        "--concurrency",
        "1",
        "--skip-env-up",
        "--errors-only",
        "--validation-scope",
        validation_scope,
    ]
    if queue:
        command.append("--queue")
    if update_manifests:
        command.append("--update-manifests")
    else:
        command.append("--no-update-manifests")

    log_path = run_dir / "validation" / f"{_sanitize_slug(spec.task_id)}.log"
    rc = _run_command(command, log_path=log_path, dry_run=dry_run, cwd=workspace_dir)
    return ValidationRun(
        task_id=spec.task_id,
        command=command,
        log_path=str(log_path),
        returncode=rc,
    )


def _refresh_seed_artifacts(
    *,
    spec: SeedSpec,
    workspace_dir: Path,
    run_dir: Path,
    queue: bool,
    update_manifests: bool,
    dry_run: bool,
) -> int:
    renders_cmd = [
        sys.executable,
        str(workspace_dir / "scripts" / "update_eval_seed_renders.py"),
        "--agent",
        DEFAULT_AGENT.value,
        "--task-id",
        spec.task_id,
        "--skip-env-up",
    ]
    if queue:
        renders_cmd.append("--queue")
    renders_log = (
        run_dir / "maintenance" / f"renders-{_sanitize_slug(spec.task_id)}.log"
    )
    return _run_command(
        renders_cmd, log_path=renders_log, dry_run=dry_run, cwd=workspace_dir
    )


def _run_command(
    command: list[str],
    *,
    log_path: Path,
    dry_run: bool,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        print(f"DRY RUN: {_format_command(command)}")
        log_path.write_text(
            f"DRY RUN: {_format_command(command)}\n",
            encoding="utf-8",
        )
        return 0

    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(f"$ {_format_command(command)}\n")
        handle.write("\n")
        handle.flush()
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )
        handle.write(f"\n[exit {completed.returncode}]\n")
        handle.flush()
        return completed.returncode


def _validate_seed_row_contract(
    *,
    spec: SeedSpec,
    workspace_dir: Path,
) -> dict[str, object]:
    dataset_path = workspace_dir / DATASET_REL
    with dataset_path.open(encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise RuntimeError(f"Seed dataset is not a list: {dataset_path}")
    row = next((entry for entry in rows if entry.get("id") == spec.task_id), None)
    if not isinstance(row, dict):
        raise RuntimeError(f"Seed row {spec.task_id} was not found after authoring")

    required_string_fields = {
        "id": spec.task_id,
        "seed_artifact_dir": (ARTIFACT_ROOT_REL / spec.task_id).as_posix(),
    }
    for field_name, expected_value in required_string_fields.items():
        raw_value = row.get(field_name)
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise RuntimeError(
                f"Seed row {spec.task_id} is missing required field {field_name!r}"
            )
        if Path(raw_value).as_posix() != expected_value:
            raise RuntimeError(
                f"Seed row {spec.task_id} has wrong {field_name!r}: "
                f"{raw_value!r} != {expected_value!r}"
            )

    task_text = row.get("task")
    if not isinstance(task_text, str) or not task_text.strip():
        raise RuntimeError(f"Seed row {spec.task_id} is missing a task string")

    criteria_text = row.get("expected_criteria")
    if not isinstance(criteria_text, str) or not criteria_text.strip():
        raise RuntimeError(
            f"Seed row {spec.task_id} is missing a non-empty expected_criteria"
        )

    complexity_level = row.get("complexity_level")
    if not isinstance(complexity_level, int) or not (0 <= complexity_level <= 5):
        raise RuntimeError(
            f"Seed row {spec.task_id} has invalid complexity_level: "
            f"{complexity_level!r}"
        )

    artifact_dir = workspace_dir / ARTIFACT_ROOT_REL / spec.task_id
    if not artifact_dir.exists():
        raise RuntimeError(f"Missing seed artifact dir: {artifact_dir}")

    role_manifest_path = artifact_dir / ".manifests" / "current_role.json"
    if not role_manifest_path.exists():
        raise RuntimeError(f"Missing current-role manifest: {role_manifest_path}")
    try:
        manifest = json.loads(role_manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"Invalid current-role manifest: {role_manifest_path}"
        ) from exc
    if str(manifest.get("agent_name")) != DEFAULT_AGENT.value:
        raise RuntimeError(
            f"current-role manifest does not name {DEFAULT_AGENT.value}: "
            f"{role_manifest_path}"
        )

    return row


def _copy_seed_dataset_file(
    *,
    root: Path,
    workspace_dir: Path,
) -> None:
    with _APPLY_LOCK:
        source_path = workspace_dir / DATASET_REL
        if not source_path.exists():
            raise RuntimeError(f"Source dataset file missing: {source_path}")
        destination_path = root / DATASET_REL
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)


def _copy_seed_artifact_dir(*, root: Path, spec: SeedSpec, workspace_dir: Path) -> None:
    with _APPLY_LOCK:
        source_dir = workspace_dir / ARTIFACT_ROOT_REL / spec.task_id
        if not source_dir.exists():
            raise RuntimeError(f"Source artifact dir missing: {source_dir}")
        destination_dir = root / ARTIFACT_ROOT_REL / spec.task_id
        if destination_dir.exists():
            shutil.rmtree(destination_dir)
        destination_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, destination_dir)


def _seed_job_allowed_prefixes(spec: SeedSpec) -> tuple[str, ...]:
    artifact_prefix = (ARTIFACT_ROOT_REL / spec.task_id).as_posix().rstrip("/") + "/"
    return (
        "logs/",
        artifact_prefix,
    )


def _run_seed_job(
    *,
    spec: SeedSpec,
    provider_name: str,
    run_dir: Path,
    root_rows: list[dict[str, object]],
    author_retries: int,
    queue: bool,
    update_manifests: bool,
    validation_scope: str,
    dry_run: bool,
    validate_only: bool,
    persist_results: bool,
) -> SeedJobRun:
    job_dir = run_dir / "jobs" / _sanitize_slug(spec.task_id)
    worktree_dir = run_dir / "worktrees" / _sanitize_slug(spec.task_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    _materialize_seed_worktree(
        root=ROOT,
        worktree_dir=worktree_dir,
        spec=spec,
        root_rows=root_rows,
    )
    baseline_paths = _git_status_paths(worktree_dir)
    baseline_rows = _load_raw_seed_rows(worktree_dir, DEFAULT_AGENT)[1]

    job = SeedJobRun(
        task_id=spec.task_id,
        family=spec.family,
        variant=spec.variant,
        complexity_level=spec.complexity_level,
        existing_row=spec.existing_row,
        worktree_dir=str(worktree_dir),
    )

    repair_note: str | None = None
    validation_passed = False
    review_passed = False
    for round_index in range(1, max(0, author_retries) + 2):
        round_dir = job_dir / f"round-{round_index:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        round_run = SeedRoundRun(round_index=round_index, repair_note=repair_note)

        author_run = _run_authoring_prompt(
            spec=spec,
            provider_name=provider_name,
            workspace_dir=worktree_dir,
            run_dir=run_dir,
            round_dir=round_dir,
            dry_run=dry_run,
            repair_note=repair_note,
        )
        round_run.authoring_run = author_run
        if author_run.returncode != 0:
            repair_note = _tail_lines(Path(author_run.log_path))
            round_run.repair_note = repair_note
            job.rounds.append(round_run)
            continue

        if (
            _refresh_seed_artifacts(
                spec=spec,
                workspace_dir=worktree_dir,
                run_dir=run_dir,
                queue=queue,
                update_manifests=update_manifests,
                dry_run=dry_run,
            )
            != 0
        ):
            repair_note = _tail_lines(
                run_dir / "maintenance" / f"renders-{_sanitize_slug(spec.task_id)}.log"
            )
            round_run.repair_note = repair_note
            job.rounds.append(round_run)
            continue

        validation_run = _run_validation(
            spec=spec,
            workspace_dir=worktree_dir,
            run_dir=run_dir,
            queue=queue,
            update_manifests=update_manifests,
            validation_scope=validation_scope,
            dry_run=dry_run,
        )
        round_run.validation_run = validation_run
        if validation_run.returncode != 0:
            repair_note = _tail_lines(Path(validation_run.log_path))
            round_run.repair_note = repair_note
            job.rounds.append(round_run)
            continue
        validation_passed = True

        validation_tail = _tail_lines(Path(validation_run.log_path))
        if not validate_only:
            review_run = _run_review_prompt(
                spec=spec,
                provider_name=provider_name,
                workspace_dir=worktree_dir,
                run_dir=run_dir,
                round_dir=round_dir,
                validation_tail=validation_tail,
                dry_run=dry_run,
                repair_note=repair_note,
            )
            round_run.review_run = review_run
            if not review_run.passed:
                repair_note = review_run.notes or _tail_lines(Path(review_run.log_path))
                round_run.repair_note = repair_note
                job.rounds.append(round_run)
                continue
            review_passed = True

        try:
            _validate_seed_row_contract(spec=spec, workspace_dir=worktree_dir)
        except Exception as exc:
            repair_note = str(exc)
            round_run.repair_note = repair_note
            job.rounds.append(round_run)
            continue

        job.rounds.append(round_run)
        changed_ids = _diff_changed_task_ids(
            before_rows=baseline_rows,
            after_rows=_load_raw_seed_rows(worktree_dir, DEFAULT_AGENT)[1],
        )
        round_run.authoring_run.changed_task_ids = changed_ids
        if spec.existing_row:
            if changed_ids and changed_ids != [spec.task_id]:
                repair_note = (
                    f"Repair touched unexpected task ids: {', '.join(changed_ids)}"
                )
                round_run.repair_note = repair_note
                continue
        else:
            if changed_ids != [spec.task_id]:
                repair_note = (
                    f"Authoring did not produce exactly one target row: "
                    f"{', '.join(changed_ids) or '(no row changes)'}"
                )
                round_run.repair_note = repair_note
                continue

        final_paths = _git_status_paths(worktree_dir)
        introduced_paths = sorted(final_paths - baseline_paths)
        allowed_prefixes = _seed_job_allowed_prefixes(spec)
        unexpected_paths = [
            path
            for path in introduced_paths
            if path != DATASET_REL.as_posix()
            and not any(path.startswith(prefix) for prefix in allowed_prefixes)
        ]
        if unexpected_paths:
            repair_note = (
                "Unexpected file changes outside the seed contract: "
                + ", ".join(unexpected_paths)
            )
            round_run.repair_note = repair_note
            continue

        if dry_run:
            job.success = True
            job.changed_task_ids = changed_ids
            job.introduced_paths = introduced_paths
            job.copied_back = False
            try:
                job.bundle_fingerprint = _seed_bundle_fingerprint(
                    worktree_dir, spec.task_id
                )
            except Exception:
                job.bundle_fingerprint = None
            return job

        if persist_results:
            _copy_seed_dataset_file(root=ROOT, workspace_dir=worktree_dir)
            _copy_seed_artifact_dir(root=ROOT, spec=spec, workspace_dir=worktree_dir)
            refresh_seed_artifact_manifests(
                ROOT / ARTIFACT_ROOT_REL / spec.task_id,
                fix=update_manifests,
            )
        job.changed_task_ids = changed_ids
        job.introduced_paths = introduced_paths
        job.copied_back = persist_results
        job.success = True
        job.last_validation_passed = validation_passed
        job.last_review_passed = review_passed if not validate_only else False
        try:
            fingerprint_root = (
                ROOT / ARTIFACT_ROOT_REL / spec.task_id
                if persist_results
                else worktree_dir
            )
            job.bundle_fingerprint = _seed_bundle_fingerprint(
                fingerprint_root, spec.task_id
            )
        except Exception:
            job.bundle_fingerprint = None
        return job

    job.failure_reason = repair_note or "seed job exhausted its repair rounds"
    final_paths = _git_status_paths(worktree_dir)
    introduced_paths = sorted(final_paths - baseline_paths)
    allowed_prefixes = _seed_job_allowed_prefixes(spec)
    job.introduced_paths = introduced_paths
    job.unexpected_paths = [
        path
        for path in introduced_paths
        if path != DATASET_REL.as_posix()
        and not any(path.startswith(prefix) for prefix in allowed_prefixes)
    ]
    job.last_validation_passed = validation_passed
    job.last_review_passed = review_passed if not validate_only else False
    try:
        job.bundle_fingerprint = _seed_bundle_fingerprint(ROOT, spec.task_id)
    except Exception:
        job.bundle_fingerprint = None
    return job


def _run_command(
    command: list[str],
    *,
    log_path: Path,
    dry_run: bool,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        print(f"DRY RUN: {_format_command(command)}")
        log_path.write_text(
            f"DRY RUN: {_format_command(command)}\n",
            encoding="utf-8",
        )
        return 0

    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(f"$ {_format_command(command)}\n")
        handle.write("\n")
        handle.flush()
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )
        handle.write(f"\n[exit {completed.returncode}]\n")
        handle.flush()
        return completed.returncode


def _write_summary(run_dir: Path, summary: AutopilotSummary) -> Path:
    summary_path = run_dir / "seed_update_autopilot_summary.json"
    summary_path.write_text(
        json.dumps(asdict(summary), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary_path


def main() -> int:
    args = _parse_args()
    if not args.author:
        raise SystemExit("--author is required for this autopilot")
    if args.seed_workers < 1:
        raise SystemExit("--seed-workers must be >= 1")
    if args.author_retries < 0:
        raise SystemExit("--author-retries must be >= 0")

    selected_families = list(args.family or DEFAULT_FAMILIES)
    requested_task_ids = parse_task_id_filters(args.task_id)
    selected_levels = parse_level_filters(args.level)
    if args.level and not selected_levels:
        raise SystemExit("No valid --level values were parsed.")

    run_dir = _prepare_run_dir()
    baseline_rows = _load_raw_seed_rows(ROOT, DEFAULT_AGENT)[1]
    summary = AutopilotSummary(
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        finished_at=None,
        provider=args.provider,
        seed_workers=args.seed_workers,
        author_retries=args.author_retries,
        families=selected_families,
        requested_task_ids=sorted(requested_task_ids),
        selected_task_ids=[],
        skipped_existing_task_ids=[],
        completed_task_ids=[],
        failed_task_ids=[],
        dry_run=args.dry_run,
        validate_only=args.validate_only,
        authoring_enabled=args.author,
    )
    task_state = _load_seed_task_state(ROOT)

    if not args.skip_env_up and not args.dry_run:
        env_up_path = ROOT / "scripts" / "env_up.sh"
        if not env_up_path.exists():
            raise FileNotFoundError(f"Missing env bootstrap script: {env_up_path}")
        env = dict(os.environ)
        if args.queue:
            env["PROBLEMOLOGIST_EVAL_LOCK_QUEUE"] = "1"
        print(f"bootstrapping eval environment with: {env_up_path}")
        completed = subprocess.run(
            [str(env_up_path), "--profile", "eval"],
            check=False,
            env=env,
        )
        if completed.returncode != 0:
            summary.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            summary.success = False
            summary_path = _write_summary(run_dir, summary)
            print(f"Summary written to {summary_path}")
            return completed.returncode

    selected_specs, skipped_existing = _canonical_seed_specs(
        root=ROOT,
        families=selected_families,
        task_ids=set(requested_task_ids) if requested_task_ids else None,
        levels=selected_levels,
        limit=args.limit,
        queue=args.queue,
        validation_scope=args.validation_scope,
        task_state=task_state,
    )
    summary.selected_task_ids = [spec.task_id for spec in selected_specs]
    summary.skipped_existing_task_ids = skipped_existing

    if not selected_specs:
        if skipped_existing:
            summary.completed_task_ids = []
            summary.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            summary.success = True
            summary_path = _write_summary(run_dir, summary)
            print(f"Summary written to {summary_path}")
            print(f"Run directory: {run_dir}")
            print(
                "No seeds queued: all matching existing rows are already "
                "clean, and no new canonical task ids matched the selection."
            )
            return 0
        summary.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        summary.success = False
        summary_path = _write_summary(run_dir, summary)
        print(f"Summary written to {summary_path}")
        raise SystemExit("No canonical engineer_planner seeds matched the selection.")

    if args.dry_run:
        for spec in selected_specs:
            mode = "repair" if spec.existing_row else "create"
            print(
                f"DRY RUN {mode} {spec.task_id}: family={spec.family} "
                f"variant={spec.variant:02d} level={spec.complexity_level}"
            )
        summary.completed_task_ids = [spec.task_id for spec in selected_specs]
        summary.success = True
        summary.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        summary_path = _write_summary(run_dir, summary)
        print(f"Summary written to {summary_path}")
        print(f"Run directory: {run_dir}")
        return 0

    jobs: list[SeedJobRun] = []
    failures: list[str] = []
    copied_task_ids: list[str] = []

    with ThreadPoolExecutor(max_workers=args.seed_workers) as pool:
        future_map = {
            pool.submit(
                _run_seed_job,
                spec=spec,
                provider_name=args.provider,
                run_dir=run_dir,
                root_rows=baseline_rows,
                author_retries=args.author_retries,
                queue=args.queue,
                update_manifests=args.update_manifests,
                validation_scope=args.validation_scope,
                dry_run=args.dry_run,
                validate_only=args.validate_only,
                persist_results=args.persist_results,
            ): spec
            for spec in selected_specs
        }
        for future in as_completed(future_map):
            spec = future_map[future]
            try:
                job = future.result()
            except Exception as exc:
                job = SeedJobRun(
                    task_id=spec.task_id,
                    family=spec.family,
                    variant=spec.variant,
                    complexity_level=spec.complexity_level,
                    existing_row=spec.existing_row,
                    worktree_dir=str(
                        run_dir / "worktrees" / _sanitize_slug(spec.task_id)
                    ),
                    failure_reason=str(exc),
                )
            jobs.append(job)
            summary.seed_jobs.append(job)
            if job.success:
                summary.completed_task_ids.append(job.task_id)
                status = "COPIED" if job.copied_back else "VALIDATED"
                print(
                    f"[seed] {status} {job.task_id}: family={job.family} "
                    f"variant={job.variant:02d}"
                )
                if job.copied_back and job.bundle_fingerprint:
                    task_state[job.task_id] = SeedTaskState(
                        task_id=job.task_id,
                        bundle_fingerprint=job.bundle_fingerprint,
                        last_validation_passed=bool(job.last_validation_passed),
                        last_review_passed=bool(job.last_review_passed),
                        source_run_started_at=summary.started_at,
                        source_run_finished_at=None,
                        recorded_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    )
                    _write_seed_task_state(ROOT, task_state)
                    copied_task_ids.append(job.task_id)
            else:
                summary.failed_task_ids.append(job.task_id)
                failures.append(job.task_id)
                print(
                    f"[seed] FAIL {job.task_id}: {job.failure_reason or 'unknown failure'}"
                )
            try:
                _cleanup_worktree(ROOT, Path(job.worktree_dir))
            except Exception:
                pass
            summary_path = _write_summary(run_dir, summary)
            print(f"Summary written to {summary_path}")

    summary.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    summary.success = not failures
    if copied_task_ids:
        for task_id in copied_task_ids:
            state = task_state.get(task_id)
            if state is None:
                continue
            task_state[task_id] = SeedTaskState(
                task_id=state.task_id,
                bundle_fingerprint=state.bundle_fingerprint,
                last_validation_passed=state.last_validation_passed,
                last_review_passed=state.last_review_passed,
                source_run_started_at=state.source_run_started_at,
                source_run_finished_at=summary.finished_at,
                recorded_at=summary.finished_at,
            )
        _write_seed_task_state(ROOT, task_state)
    summary_path = _write_summary(run_dir, summary)

    print(f"Summary written to {summary_path}")
    print(f"Run directory: {run_dir}")
    if summary.completed_task_ids:
        print("Completed seeds: " + ", ".join(sorted(summary.completed_task_ids)))
    if failures:
        print("Failed seeds: " + ", ".join(sorted(failures)))

    return 0 if summary.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
