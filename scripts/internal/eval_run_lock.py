from __future__ import annotations

import fcntl
import json
import os
import shlex
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TextIO

from evals.logic.temp_paths import eval_temp_root

DEFAULT_EVAL_RUN_FAMILY_NAME = "eval"
DEFAULT_EVAL_RUN_LOCK_PATH = (
    eval_temp_root(DEFAULT_EVAL_RUN_FAMILY_NAME) / "problemologist-eval.lock"
)
DEFAULT_EVAL_RUN_STATE_PATH = (
    eval_temp_root(DEFAULT_EVAL_RUN_FAMILY_NAME) / "problemologist-eval.run.json"
)


@dataclass(frozen=True, slots=True)
class EvalRunSelection:
    agent: str | None = None
    task_ids: list[str] = field(default_factory=list)
    levels: list[int] = field(default_factory=list)


@dataclass
class EvalRunState:
    pid: int
    ppid: int
    started_at: str
    requested_command: list[str] = field(default_factory=list)
    requested_agent: str | None = None
    requested_task_ids: list[str] = field(default_factory=list)
    requested_levels: list[int] = field(default_factory=list)
    current_log_dir: str | None = None
    current_phase: str | None = None


@dataclass
class EvalRunLease:
    lock_file: TextIO
    lock_path: Path
    state_path: Path | None
    state: EvalRunState | None
    state_writable: bool = True

    def update_state(self, **updates: object) -> None:
        if self.state is None or self.state_path is None or not self.state_writable:
            raise RuntimeError("shared eval lock leases do not carry writable state")
        for key, value in updates.items():
            setattr(self.state, key, value)
        _write_json_atomic(self.state_path, asdict(self.state))


def _eval_run_lock_path() -> Path:
    override = os.environ.get("EVAL_RUN_LOCK_PATH", "").strip()
    if override:
        return Path(override)
    return DEFAULT_EVAL_RUN_LOCK_PATH


def _eval_run_state_path() -> Path:
    override = os.environ.get("EVAL_RUN_STATE_PATH", "").strip()
    if override:
        return Path(override)
    return DEFAULT_EVAL_RUN_STATE_PATH


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _read_json_file(path: Path) -> dict[str, object] | None:
    try:
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _join_command(values: list[str]) -> str:
    if not values:
        return "unspecified"
    return shlex.join(values)


def _format_eval_run_block_message(
    state: dict[str, object] | None,
    *,
    requested_command: list[str],
) -> str:
    active_command = "unknown"
    active_phase = "unknown"
    active_log_dir = "unknown"
    if state:
        requested = state.get("requested_command")
        if isinstance(requested, list) and requested:
            active_command = _join_command([str(item) for item in requested])
        phase = state.get("current_phase")
        if isinstance(phase, str) and phase.strip():
            active_phase = phase.strip()
        log_dir = state.get("current_log_dir")
        if isinstance(log_dir, str) and log_dir.strip():
            active_log_dir = log_dir.strip()

    lines = [
        "Be careful - another eval run is already running.",
        f"Active command: [{active_command}]",
        f"Active phase: [{active_phase}]",
        f"Active logs: [{active_log_dir}]",
        f"Your requested command: [{_join_command(requested_command)}]",
        "If these match, you can reuse the active run's logs under logs/evals/current/ instead of starting a duplicate run.",
        "If you only need validation, rerun that check with --skip-env-up to join the shared validation lock.",
        "If you want to wait for the shared lock, rerun with --queue.",
    ]
    return "\n".join(lines)


def _acquire_eval_run_flock(
    *,
    mode: int,
    queue: bool,
    requested_command: list[str],
    requested_selection: EvalRunSelection | None,
    write_state: bool,
) -> EvalRunLease | None:
    lock_path = _eval_run_lock_path()
    state_path = _eval_run_state_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        if queue:
            state = _read_json_file(state_path)
            if state is not None:
                print(
                    _format_eval_run_block_message(
                        state,
                        requested_command=requested_command,
                    ),
                    file=sys.stderr,
                )
            shared_label = "shared " if mode == fcntl.LOCK_SH else ""
            print(
                f"[eval-run-lock] Waiting for {shared_label}eval lock at {lock_path}..."
            )
            fcntl.flock(lock_file.fileno(), mode)
        else:
            try:
                fcntl.flock(lock_file.fileno(), mode | fcntl.LOCK_NB)
            except BlockingIOError:
                state = _read_json_file(state_path)
                print(
                    _format_eval_run_block_message(
                        state,
                        requested_command=requested_command,
                    ),
                    file=sys.stderr,
                )
                lock_file.close()
                return None

        if not write_state:
            return EvalRunLease(
                lock_file=lock_file,
                lock_path=lock_path,
                state_path=None,
                state=None,
                state_writable=False,
            )

        lease = EvalRunLease(
            lock_file=lock_file,
            lock_path=lock_path,
            state_path=state_path,
            state=EvalRunState(
                pid=os.getpid(),
                ppid=os.getppid(),
                started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                requested_command=list(requested_command),
                requested_agent=(
                    requested_selection.agent if requested_selection else None
                ),
                requested_task_ids=(
                    list(requested_selection.task_ids)
                    if requested_selection is not None
                    else []
                ),
                requested_levels=(
                    list(requested_selection.levels)
                    if requested_selection is not None
                    else []
                ),
            ),
        )
        _write_json_atomic(lease.state_path, asdict(lease.state))
        return lease
    except Exception:
        lock_file.close()
        raise


def acquire_eval_run_lock(
    *,
    queue: bool,
    requested_command: list[str],
    requested_selection: EvalRunSelection | None = None,
) -> EvalRunLease | None:
    return _acquire_eval_run_flock(
        mode=fcntl.LOCK_EX,
        queue=queue,
        requested_command=requested_command,
        requested_selection=requested_selection,
        write_state=True,
    )


def acquire_eval_run_shared_lock(
    *,
    queue: bool,
    requested_command: list[str],
    requested_selection: EvalRunSelection | None = None,
) -> EvalRunLease | None:
    return _acquire_eval_run_flock(
        mode=fcntl.LOCK_SH,
        queue=queue,
        requested_command=requested_command,
        requested_selection=requested_selection,
        write_state=False,
    )


def downgrade_eval_run_lock_to_shared(lease: EvalRunLease) -> None:
    fcntl.flock(lease.lock_file.fileno(), fcntl.LOCK_SH)
    lease.state_writable = False


def release_eval_run_lock(lease: EvalRunLease | None) -> None:
    if lease is None:
        return
    try:
        if lease.state_path is not None:
            lease.state_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        lease.lock_file.close()
    except OSError:
        pass
