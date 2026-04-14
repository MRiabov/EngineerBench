#!/usr/bin/env python3
"""Internal integration-test orchestration utilities."""

from __future__ import annotations

import argparse
import ast
import asyncio
import concurrent.futures
import copy
import fcntl
import json
import os
import re
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, TextIO
from xml.etree import ElementTree as ET

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.logic.notifications import audibly_notify
from evals.logic.stack_profiles import apply_stack_profile_env

INTEGRATION_WORKFLOW_HINT = (
    "If you are seeing a startup timeout or unhealthy service here, "
    "you are probably not using ./scripts/run_integration_tests.sh. "
    "Integration runs should follow the integration-tests-workflow."
)


def _integration_runner_verbose() -> bool:
    raw = os.environ.get("INTEGRATION_RUNNER_VERBOSE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _runner_status(
    message: str,
    *,
    always: bool = False,
    file: TextIO = sys.stdout,
    end: str = "\n",
    flush: bool = False,
) -> None:
    if always or _integration_runner_verbose():
        print(message, file=file, end=end, flush=flush)


INTEGRATION_RUN_LOCK_PATH = Path("/tmp/problemologist-integration.lock")
INTEGRATION_RUN_STATE_PATH = Path("/tmp/problemologist-integration.run.json")
LONG_INTEGRATION_RUN_THRESHOLD_S = 7 * 60
CTRL_C_BACKEND_ERROR_GRACE_S = 2.0

CheckKind = Literal["http", "tcp", "cmd"]


@dataclass(frozen=True)
class HealthCheck:
    name: str
    kind: CheckKind
    target: str
    contains: str | None = None


@dataclass
class StartedProcess:
    name: str
    process: subprocess.Popen[bytes]


@dataclass
class BackendErrorAllowRule:
    allow_all: bool = False
    patterns: list[re.Pattern[str]] = field(default_factory=list)


@dataclass
class IntegrationRunState:
    pid: int
    ppid: int
    started_at: str
    requested_pytest_args: list[str] = field(default_factory=list)
    requested_int_ids: list[str] = field(default_factory=list)
    current_log_dir: str | None = None
    current_int_ids: list[str] = field(default_factory=list)


@dataclass
class IntegrationRunLease:
    lock_file: TextIO
    lock_path: Path
    state_path: Path
    state: IntegrationRunState

    def update_state(self, **updates: object) -> None:
        for key, value in updates.items():
            setattr(self.state, key, value)
        _write_json_atomic(self.state_path, asdict(self.state))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _extract_int_ids_from_args(values: list[str]) -> list[str]:
    int_ids: set[str] = set()
    for value in values:
        for match in re.finditer(r"INT-(\d{3})", value, re.IGNORECASE):
            int_ids.add(f"INT-{match.group(1)}")
        for match in re.finditer(r"test_int_(\d{3})", value, re.IGNORECASE):
            int_ids.add(f"INT-{match.group(1)}")
        for match in re.finditer(r"test_int_(\d{3})_to_(\d{3})", value, re.IGNORECASE):
            int_ids.add(f"INT-{match.group(1)}")
            int_ids.add(f"INT-{match.group(2)}")
    return sorted(int_ids)


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


def _integration_run_lock_path() -> Path:
    override = os.environ.get("INTEGRATION_RUN_LOCK_PATH", "").strip()
    if override:
        return Path(override)
    return INTEGRATION_RUN_LOCK_PATH


def _integration_run_state_path() -> Path:
    override = os.environ.get("INTEGRATION_RUN_STATE_PATH", "").strip()
    if override:
        return Path(override)
    return INTEGRATION_RUN_STATE_PATH


def _compile_backend_error_allowlist_from_env(
    env: dict[str, str],
) -> list[re.Pattern[str]]:
    raw_patterns = [
        p.strip()
        for p in env.get("BACKEND_ERROR_ALLOWLIST_REGEXES", "").split(";;")
        if p.strip()
    ]
    compiled: list[re.Pattern[str]] = []
    for pattern in raw_patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            print(
                f"[integration-runner] Ignoring invalid BACKEND_ERROR_ALLOWLIST regex: {pattern!r}"
            )
    return compiled


def _extract_backend_error_session_id(normalized_line: str) -> str | None:
    patterns = [
        r"session_id=UUID\('([^']+)'\)",
        r'session_id="([^"]+)"',
        r"session_id='([^']+)'",
        r"session_id=([^\s]+)",
        r'"session_id"\s*:\s*"([^"]+)"',
        r"'session_id'\s*:\s*'([^']+)'",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized_line)
        if not match:
            continue
        candidate = (match.group(1) or "").strip().strip(",")
        if candidate:
            return candidate
    return None


def _extract_int_prefix_from_session_id(session_id: str | None) -> str | None:
    if not session_id:
        return None
    match = re.search(r"(INT-\d{3})", session_id, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper()


def _is_allow_backend_errors_decorator(expr: ast.expr) -> bool:
    target = expr.func if isinstance(expr, ast.Call) else expr
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "allow_backend_errors"
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "mark"
        and isinstance(target.value.value, ast.Name)
        and target.value.value.id == "pytest"
    )


def _is_disable_manifest_update_decorator(expr: ast.expr) -> bool:
    target = expr.func if isinstance(expr, ast.Call) else expr
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "disable_manifest_update"
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "mark"
        and isinstance(target.value.value, ast.Name)
        and target.value.value.id == "pytest"
    )


def _extract_int_ids_from_test_node(node: ast.AST) -> set[str]:
    int_ids: set[str] = set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        name_match = re.search(r"test_int_(\d{3})", node.name, re.IGNORECASE)
        if name_match:
            int_ids.add(f"INT-{name_match.group(1)}")
        doc = ast.get_docstring(node) or ""
        for match in re.finditer(r"INT-(\d{3})", doc, re.IGNORECASE):
            int_ids.add(f"INT-{match.group(1)}")
    return {value.upper() for value in int_ids}


def _extract_allow_backend_errors_from_decorator(
    decorator: ast.expr,
) -> tuple[bool, list[str]]:
    if not isinstance(decorator, ast.Call):
        return True, []

    if not decorator.args and not decorator.keywords:
        raise ValueError(
            "@pytest.mark.allow_backend_errors requires explicit regex patterns; "
            "catch-all usage is forbidden."
        )

    patterns: list[str] = []
    for arg in decorator.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            value = arg.value.strip()
            if value:
                patterns.append(value)

    for keyword in decorator.keywords:
        if keyword.arg not in {"regexes", "patterns", "pattern"}:
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            raw = value.value.strip()
            if raw:
                patterns.append(raw)
            continue
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            for item in value.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    raw = item.value.strip()
                    if raw:
                        patterns.append(raw)
    return False, patterns


def _build_test_level_backend_allowlist_payload_from_ast(
    repo_root: Path,
) -> dict[str, dict[str, object]]:
    index: dict[str, dict[str, object]] = {}
    test_roots = [repo_root / "tests" / "integration", repo_root / "tests" / "e2e"]

    for test_root in test_roots:
        if not test_root.exists():
            continue
        for path in test_root.rglob("test_*.py"):
            try:
                source = path.read_text(encoding="utf-8")
                module = ast.parse(source, filename=str(path))
            except (OSError, SyntaxError):
                continue

            for node in module.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                int_ids = _extract_int_ids_from_test_node(node)
                if not int_ids:
                    continue

                for decorator in node.decorator_list:
                    if not _is_allow_backend_errors_decorator(decorator):
                        continue
                    try:
                        allow_all, raw_patterns = (
                            _extract_allow_backend_errors_from_decorator(decorator)
                        )
                    except ValueError as exc:
                        raise RuntimeError(f"{path}:{node.lineno}: {exc}") from exc
                    compiled_patterns: list[re.Pattern[str]] = []
                    for pattern in raw_patterns:
                        try:
                            compiled_patterns.append(re.compile(pattern, re.IGNORECASE))
                        except re.error:
                            print(
                                "[integration-runner] Ignoring invalid allow_backend_errors regex "
                                f"in {path}: {pattern!r}"
                            )

                    for int_id in int_ids:
                        rule = index.setdefault(
                            int_id, {"allow_all": False, "patterns": []}
                        )
                        if allow_all:
                            rule["allow_all"] = True
                        if compiled_patterns:
                            raw = [pattern.pattern for pattern in compiled_patterns]
                            existing = rule.get("patterns")
                            if not isinstance(existing, list):
                                existing = []
                                rule["patterns"] = existing
                            existing.extend(raw)
    return index


def _manifest_update_disable_cache_path(repo_root: Path) -> Path:
    integration_log_dir_raw = os.environ.get("INTEGRATION_LOG_DIR", "").strip()
    if integration_log_dir_raw:
        return (
            Path(integration_log_dir_raw)
            / "json"
            / "manifest_update_disabled_int_ids.json"
        )
    return (
        repo_root
        / "logs"
        / "integration_tests"
        / "json"
        / "manifest_update_disabled_int_ids.json"
    )


def _build_test_level_manifest_update_disable_payload_from_ast(
    repo_root: Path,
) -> dict[str, bool]:
    index: dict[str, bool] = {}
    test_roots = [repo_root / "tests" / "integration", repo_root / "tests" / "e2e"]

    for test_root in test_roots:
        if not test_root.exists():
            continue
        for path in test_root.rglob("test_*.py"):
            try:
                source = path.read_text(encoding="utf-8")
                module = ast.parse(source, filename=str(path))
            except (OSError, SyntaxError):
                continue

            for node in module.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                int_ids = _extract_int_ids_from_test_node(node)
                if not int_ids:
                    continue

                if not any(
                    _is_disable_manifest_update_decorator(dec)
                    for dec in node.decorator_list
                ):
                    continue

                for int_id in int_ids:
                    index[int_id] = True
    return index


def _load_or_generate_test_level_manifest_update_disable_payload(
    repo_root: Path,
) -> dict[str, bool]:
    cache_path = _manifest_update_disable_cache_path(repo_root)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    source_mtime = _latest_test_allowlist_source_mtime(repo_root)

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_source_mtime = float(cached.get("source_mtime", 0.0))
            by_int = cached.get("by_int")
            if cached_source_mtime >= source_mtime and isinstance(by_int, dict):
                return {str(key).upper(): bool(value) for key, value in by_int.items()}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    by_int = _build_test_level_manifest_update_disable_payload_from_ast(repo_root)
    payload = {
        "generated_at_epoch_s": time.time(),
        "source_mtime": source_mtime,
        "by_int": by_int,
    }
    cache_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return by_int


def _allowlist_cache_path(repo_root: Path) -> Path:
    integration_log_dir_raw = os.environ.get("INTEGRATION_LOG_DIR", "").strip()
    if integration_log_dir_raw:
        return (
            Path(integration_log_dir_raw)
            / "json"
            / "backend_error_allowlisted_prefixes.json"
        )
    return (
        repo_root
        / "logs"
        / "integration_tests"
        / "json"
        / "backend_error_allowlisted_prefixes.json"
    )


def _latest_test_allowlist_source_mtime(repo_root: Path) -> float:
    latest = 0.0
    for test_root in (repo_root / "tests" / "integration", repo_root / "tests" / "e2e"):
        if not test_root.exists():
            continue
        for path in test_root.rglob("test_*.py"):
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                continue
    return latest


def _load_or_generate_test_level_backend_allowlist_payload(
    repo_root: Path,
) -> dict[str, dict[str, object]]:
    cache_path = _allowlist_cache_path(repo_root)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    source_mtime = _latest_test_allowlist_source_mtime(repo_root)

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_source_mtime = float(cached.get("source_mtime", 0.0))
            by_int = cached.get("by_int")
            if cached_source_mtime >= source_mtime and isinstance(by_int, dict):
                return by_int
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    by_int = _build_test_level_backend_allowlist_payload_from_ast(repo_root)
    payload = {
        "generated_at_epoch_s": time.time(),
        "source_mtime": source_mtime,
        "by_int": by_int,
    }
    cache_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return by_int


def _compile_test_level_backend_allowlist_by_int_id(
    payload: dict[str, dict[str, object]],
) -> dict[str, BackendErrorAllowRule]:
    index: dict[str, BackendErrorAllowRule] = {}
    for int_id, raw_rule in payload.items():
        if not isinstance(raw_rule, dict):
            continue
        allow_all = bool(raw_rule.get("allow_all", False))
        compiled_patterns: list[re.Pattern[str]] = []
        raw_patterns = raw_rule.get("patterns", [])
        if isinstance(raw_patterns, list):
            for pattern in raw_patterns:
                if not isinstance(pattern, str):
                    continue
                try:
                    compiled_patterns.append(re.compile(pattern, re.IGNORECASE))
                except re.error:
                    print(
                        "[integration-runner] Ignoring invalid cached allow_backend_errors regex "
                        f"for {int_id}: {pattern!r}"
                    )
        index[int_id] = BackendErrorAllowRule(
            allow_all=allow_all, patterns=compiled_patterns
        )
    return index


def _backend_error_line_is_allowlisted(
    normalized_line: str,
    *,
    env_allowlist: list[re.Pattern[str]],
    int_allowlist: dict[str, BackendErrorAllowRule],
    session_id: str | None = None,
) -> bool:
    if any(pattern.search(normalized_line) for pattern in env_allowlist):
        return True

    if not session_id:
        session_id = _extract_backend_error_session_id(normalized_line)
    int_id = _extract_int_prefix_from_session_id(session_id)
    if not int_id:
        return False

    rule = int_allowlist.get(int_id)
    if not rule:
        return False
    if rule.allow_all:
        return True
    return any(pattern.search(normalized_line) for pattern in rule.patterns)


def _check_http(url: str, *, contains: str | None, timeout_s: float) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            if contains is None:
                return True
            payload = response.read().decode("utf-8", errors="ignore")
            return contains in payload
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _check_tcp(host: str, port: int, *, timeout_s: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _check_cmd(command: str) -> bool:
    completed = subprocess.run(
        ["bash", "-o", "pipefail", "-lc", command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


async def _check_once(check: HealthCheck, *, timeout_s: float) -> bool:
    if check.kind == "http":
        return await asyncio.to_thread(
            _check_http, check.target, contains=check.contains, timeout_s=timeout_s
        )
    if check.kind == "tcp":
        host, port_s = check.target.rsplit(":", 1)
        return await asyncio.to_thread(
            _check_tcp, host, int(port_s), timeout_s=timeout_s
        )
    return await asyncio.to_thread(_check_cmd, check.target)


async def wait_for_check(
    check: HealthCheck,
    *,
    timeout_s: float = 120.0,
    interval_s: float = 0.5,
    probe_timeout_s: float = 1.0,
) -> float:
    started = time.monotonic()
    while True:
        if await _check_once(check, timeout_s=probe_timeout_s):
            return time.monotonic() - started
        elapsed = time.monotonic() - started
        if elapsed >= timeout_s:
            raise TimeoutError(
                f"Timed out waiting for {check.name} ({check.kind}:{check.target}). "
                f"{INTEGRATION_WORKFLOW_HINT}"
            )
        await asyncio.sleep(interval_s)


async def wait_for_checks_parallel(
    checks: list[HealthCheck],
    *,
    timeout_s: float = 120.0,
    interval_s: float = 0.5,
    probe_timeout_s: float = 1.0,
) -> dict[str, float]:
    tasks = {
        check.name: asyncio.create_task(
            wait_for_check(
                check,
                timeout_s=timeout_s,
                interval_s=interval_s,
                probe_timeout_s=probe_timeout_s,
            )
        )
        for check in checks
    }
    try:
        results = await asyncio.gather(*tasks.values())
        return dict(zip(tasks.keys(), results, strict=True))
    finally:
        for task in tasks.values():
            if not task.done():
                task.cancel()


def run_pytest_subprocess(
    pytest_args: list[str],
    *,
    reverse: bool = False,
    junit_xml: str = "test_output/junit.xml",
    extra_env: dict[str, str] | None = None,
    early_stop_error_logs: list[Path] | None = None,
) -> int:
    has_explicit_maxfail = any(
        arg == "--maxfail" or arg.startswith("--maxfail=") for arg in pytest_args
    )
    has_explicit_xdist = any(
        arg == "-n"
        or arg.startswith("-n")
        or arg == "--dist"
        or arg.startswith("--dist=")
        or arg == "--numprocesses"
        or arg.startswith("--numprocesses=")
        for arg in pytest_args
    )
    xdist_workers = os.environ.get("INTEGRATION_XDIST_WORKERS", "4").strip()
    xdist_dist = (
        os.environ.get("INTEGRATION_XDIST_DIST", "loadgroup").strip() or "loadgroup"
    )
    # Keep xdist on for every integration path by default. The only supported
    # way to serialize a subset is explicit xdist grouping or an explicit
    # xdist opt-out/override from the caller.
    enable_xdist = (
        not has_explicit_xdist
        and xdist_workers
        and xdist_workers not in {"0", "0.0", "false", "False", "none", "None"}
    )
    cmd = [
        "uv",
        "run",
        "pytest",
        "-v",
        "-o",
        "addopts=-n0",
        "-s",
        "--color=yes",
    ]
    if not has_explicit_maxfail:
        cmd.append("--maxfail=3")
    if reverse:
        cmd.append("--reverse")
    if enable_xdist:
        cmd.extend(["-n", xdist_workers, "--dist", xdist_dist])
    cmd.extend(pytest_args)
    cmd.append(f"--junitxml={junit_xml}")

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    env.setdefault("AUTO_MANIFEST_UPDATE", "1")
    manifest_update_disable_payload = (
        _load_or_generate_test_level_manifest_update_disable_payload(_repo_root())
    )
    env["MANIFEST_UPDATE_DISABLED_INT_IDS"] = ";;".join(
        sorted(
            int_id
            for int_id, disabled in manifest_update_disable_payload.items()
            if disabled
        )
    )
    early_stop_enabled = (
        env.get("INTEGRATION_EARLY_STOP_ON_BACKEND_ERRORS", "0").strip() == "1"
    )
    env_allowlist = _compile_backend_error_allowlist_from_env(env)
    allowlist_payload = _load_or_generate_test_level_backend_allowlist_payload(
        _repo_root()
    )
    int_allowlist = _compile_test_level_backend_allowlist_by_int_id(allowlist_payload)
    error_log_offsets: dict[Path, int] = {}
    if early_stop_error_logs:
        for error_log in early_stop_error_logs:
            try:
                error_log_offsets[error_log] = error_log.stat().st_size
            except OSError:
                error_log_offsets[error_log] = 0

    # Ensure log directory exists
    integration_log_dir_raw = os.environ.get("INTEGRATION_LOG_DIR", "").strip()
    if integration_log_dir_raw:
        log_file = Path(integration_log_dir_raw) / "full_test_output.log"
    else:
        log_file = _repo_root() / "logs" / "integration_tests" / "full_test_output.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    process = subprocess.Popen(
        cmd,
        cwd=_repo_root(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    original_sigint_handler = signal.getsignal(signal.SIGINT)
    original_sigterm_handler = signal.getsignal(signal.SIGTERM)
    early_stop_requested = False
    interrupt_requested = False
    interrupt_requested_at: float | None = None
    interrupt_forwarded = False

    def _forward_signal(sig: int, _: object) -> None:
        nonlocal interrupt_requested, interrupt_requested_at, interrupt_forwarded
        if process.poll() is not None:
            return

        if sig == signal.SIGINT and early_stop_enabled:
            if early_stop_requested:
                if not interrupt_forwarded:
                    interrupt_forwarded = True
                    process.send_signal(sig)
                return

            if not interrupt_requested:
                interrupt_requested = True
                interrupt_requested_at = time.monotonic()
                print(
                    "\n[integration-runner] Ctrl-C received; waiting briefly for "
                    "backend-error detection before interrupting pytest.\n",
                    end="",
                    flush=True,
                )
                return

            if not interrupt_forwarded:
                interrupt_forwarded = True
                process.send_signal(sig)
            return

        if not interrupt_forwarded:
            interrupt_forwarded = True
            process.send_signal(sig)

    signal.signal(signal.SIGINT, _forward_signal)
    signal.signal(signal.SIGTERM, _forward_signal)

    def _find_early_stop_reason() -> str | None:
        if not early_stop_enabled:
            return None
        if not early_stop_error_logs:
            return None
        for error_log in early_stop_error_logs:
            if not error_log.exists():
                continue
            start_offset = error_log_offsets.get(error_log, 0)
            try:
                with error_log.open("r", encoding="utf-8", errors="ignore") as handle:
                    handle.seek(start_offset)
                    for raw_line in handle:
                        try:
                            record = json.loads(raw_line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(record, dict):
                            continue
                        normalized = str(record.get("line") or "").strip()
                        if not normalized:
                            parts: list[str] = []
                            event_text = str(record.get("event") or "").strip()
                            if event_text:
                                parts.append(event_text)
                            for key in sorted(record):
                                if key == "event":
                                    continue
                                value = record.get(key)
                                if isinstance(value, (dict, list)):
                                    rendered = json.dumps(
                                        value, ensure_ascii=False, sort_keys=True
                                    )
                                else:
                                    rendered = str(value)
                                parts.append(f"{key}={rendered}")
                            normalized = " ".join(parts).strip()
                        if not normalized:
                            continue
                        session_id = record.get("session_id")
                        if not isinstance(session_id, str):
                            session_id = None
                        if _backend_error_line_is_allowlisted(
                            normalized,
                            env_allowlist=env_allowlist,
                            int_allowlist=int_allowlist,
                            session_id=session_id,
                        ):
                            continue
                        truncated = (
                            normalized[:220] + "..."
                            if len(normalized) > 220
                            else normalized
                        )
                        return (
                            f"non-allowlisted backend error detected in {error_log}: "
                            f"{truncated}"
                        )
                    error_log_offsets[error_log] = handle.tell()
            except OSError:
                continue
        return None

    assert process.stdout is not None
    try:
        with log_file.open("w", encoding="utf-8") as log_handle:
            while True:
                if not early_stop_requested:
                    early_stop_reason = _find_early_stop_reason()
                    if early_stop_reason:
                        early_stop_requested = True
                        msg = (
                            "\n[integration-runner] Non-allowlisted backend error "
                            "detected (pytest fixture will fail the active test): "
                            f"{early_stop_reason}\n"
                        )
                        print(msg, end="", flush=True)
                        log_handle.write(msg)
                        log_handle.flush()

                if (
                    interrupt_requested
                    and not interrupt_forwarded
                    and not early_stop_requested
                ):
                    if (
                        interrupt_requested_at is not None
                        and time.monotonic() - interrupt_requested_at
                        >= CTRL_C_BACKEND_ERROR_GRACE_S
                    ):
                        interrupt_forwarded = True
                        process.send_signal(signal.SIGINT)

                if process.poll() is not None:
                    for line in process.stdout:
                        print(line, end="")
                        log_handle.write(line)
                    break

                ready, _, _ = select.select([process.stdout], [], [], 0.5)
                if ready:
                    line = process.stdout.readline()
                    if line:
                        print(line, end="")
                        log_handle.write(line)
                        log_handle.flush()
            process.stdout.close()
    finally:
        signal.signal(signal.SIGINT, original_sigint_handler)
        signal.signal(signal.SIGTERM, original_sigterm_handler)

    return process.wait()


def _run(
    cmd: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        cmd,
        check=check,
        cwd=cwd or _repo_root(),
        env=env,
        stdout=stdout,
        stderr=stderr,
    )


def _resolve_alembic_database_url(repo_root: Path) -> str:
    url = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")
    if not url:
        config = Config(str(repo_root / "alembic.ini"))
        url = config.get_main_option("sqlalchemy.url")

    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    return url


def _get_alembic_head_revisions(repo_root: Path) -> set[str]:
    config = Config(str(repo_root / "alembic.ini"))
    return {revision for revision in ScriptDirectory.from_config(config).get_heads()}


def _get_current_alembic_revisions(repo_root: Path) -> set[str]:
    database_url = _resolve_alembic_database_url(repo_root)
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return {
                revision
                for revision in context.get_current_heads()
                if revision is not None
            }
    finally:
        engine.dispose()


def _format_revision_set(revisions: set[str]) -> str:
    if not revisions:
        return "<none>"
    return ", ".join(sorted(revisions))


def _ensure_alembic_migrations(
    repo_root: Path, *, force_run_alembic: bool = False
) -> bool:
    current_revisions = _get_current_alembic_revisions(repo_root)
    head_revisions = _get_alembic_head_revisions(repo_root)

    if not force_run_alembic and current_revisions == head_revisions:
        _runner_status(
            "Integration database is already at Alembic head; skipping migrations.",
            always=True,
        )
        return False

    if force_run_alembic:
        _runner_status("Force-running Alembic migrations...", always=True)
    else:
        _runner_status(
            "Alembic revision mismatch "
            f"(current={_format_revision_set(current_revisions)}, "
            f"head={_format_revision_set(head_revisions)}); running migrations...",
            always=True,
        )

    _run(["uv", "run", "alembic", "upgrade", "head"])
    return True


def _worker_renderer_compose_cmd(*, compose_project_name: str) -> list[str]:
    return ["docker", "compose", "-p", compose_project_name, "-f", "docker-compose.yml"]


def _ensure_worker_renderer_image(*, compose_project_name: str) -> None:
    image_name = "problemologist-ai-worker-renderer:latest"

    probe = _run(
        ["docker", "image", "inspect", image_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode == 0:
        return

    _runner_status("Building Worker Renderer image...")
    _run(
        [
            "docker",
            "build",
            "-f",
            "worker_renderer/Dockerfile",
            "-t",
            image_name,
            ".",
        ]
    )


def _start_worker_renderer_container(
    *,
    compose_project_name: str,
    log_file: Path,
) -> str:
    compose_cmd = _worker_renderer_compose_cmd(
        compose_project_name=compose_project_name
    )
    _ensure_worker_renderer_image(compose_project_name=compose_project_name)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("ab") as handle:
        handle.write(b"Starting Worker Renderer container via docker compose...\n")

    with log_file.open("ab") as handle:
        result = subprocess.run(
            [*compose_cmd, "up", "-d", "--no-deps", "worker-renderer"],
            check=False,
            cwd=_repo_root(),
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            [*compose_cmd, "up", "-d", "--no-deps", "worker-renderer"],
        )

    container_id = ""
    for _ in range(30):
        inspect_result = _run(
            [*compose_cmd, "ps", "-q", "worker-renderer"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        container_id = inspect_result.stdout.decode("utf-8", errors="ignore").strip()
        if container_id:
            break
        time.sleep(0.5)

    if not container_id:
        raise RuntimeError("Worker Renderer container id not found after startup")

    with log_file.open("ab") as handle:
        handle.write(f"Worker Renderer container id: {container_id}\n".encode())

    _runner_status(f"Worker Renderer container started (ID: {container_id})")
    return container_id


def _stop_worker_renderer_container(*, compose_project_name: str) -> None:
    compose_cmd = _worker_renderer_compose_cmd(
        compose_project_name=compose_project_name
    )
    _run([*compose_cmd, "stop", "worker-renderer"], check=False)


def _format_elapsed_duration(elapsed_s: float) -> str:
    total_seconds = max(0, int(round(elapsed_s)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m{seconds:02d}s"


def _maybe_notify_long_integration_run(elapsed_s: float) -> None:
    if elapsed_s <= LONG_INTEGRATION_RUN_THRESHOLD_S:
        return

    duration = _format_elapsed_duration(elapsed_s)
    message = f"integration tests finished after {duration}"
    print(f"[integration-runner] {message}")
    audibly_notify("integration tests finished")


def _parse_check(definition: str, *, kind: CheckKind) -> HealthCheck:
    parts = definition.split("|")
    if len(parts) < 2:
        msg = f"Invalid {kind} check definition: {definition!r}"
        raise argparse.ArgumentTypeError(msg)

    name = parts[0].strip()
    if not name:
        msg = f"Missing check name in definition: {definition!r}"
        raise argparse.ArgumentTypeError(msg)

    if kind == "http":
        target = parts[1].strip()
        contains = parts[2].strip() if len(parts) >= 3 and parts[2].strip() else None
        return HealthCheck(name=name, kind=kind, target=target, contains=contains)

    target = parts[1].strip()
    return HealthCheck(name=name, kind=kind, target=target)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    _runner_status("Loading environment from .env...")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not (key[0].isalpha() or key[0] == "_"):
            continue
        if any(not (ch.isalnum() or ch == "_") for ch in key):
            continue

        if value and value[0] in {"'", '"'} and value[-1:] == value[0]:
            value = value[1:-1]
        else:
            hash_index = value.find("#")
            if hash_index != -1:
                value = value[:hash_index].rstrip()

        os.environ[key] = value


def _format_integration_run_block_message(
    state: dict[str, object] | None,
    *,
    requested_int_ids: list[str],
    requested_pytest_args: list[str],
) -> str:
    active_int_ids: list[str] = []
    if state:
        current = state.get("current_int_ids")
        if isinstance(current, list) and current:
            active_int_ids = [str(item) for item in current if str(item).strip()]
        else:
            requested = state.get("requested_int_ids")
            if isinstance(requested, list):
                active_int_ids = [str(item) for item in requested if str(item).strip()]

    active_display = ", ".join(active_int_ids) if active_int_ids else "unknown"
    if requested_int_ids:
        requested_display = ", ".join(requested_int_ids)
    elif requested_pytest_args:
        requested_display = " ".join(requested_pytest_args)
    else:
        requested_display = "unspecified"
    lines = [
        "Be careful - another integration test suite is already running.",
        f"Active tests: [{active_display}]",
        f"Your requested tests: [{requested_display}]",
        "If these match, you can reuse the active run's logs under "
        "logs/integration_tests/current/ instead of starting a duplicate run.",
        "If you want to wait for the shared lock, rerun with --queue.",
    ]
    return "\n".join(lines)


def _acquire_integration_run_lock(
    *,
    queue: bool,
    requested_pytest_args: list[str],
) -> IntegrationRunLease | None:
    lock_path = _integration_run_lock_path()
    state_path = _integration_run_state_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        if queue:
            state = _read_json_file(state_path)
            if state is not None:
                print(
                    _format_integration_run_block_message(
                        state,
                        requested_int_ids=_extract_int_ids_from_args(
                            requested_pytest_args
                        ),
                        requested_pytest_args=requested_pytest_args,
                    ),
                    file=sys.stderr,
                )
            print(
                f"[integration-runner] Waiting for integration lock at {lock_path}..."
            )
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        else:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                state = _read_json_file(state_path)
                print(
                    _format_integration_run_block_message(
                        state,
                        requested_int_ids=_extract_int_ids_from_args(
                            requested_pytest_args
                        ),
                        requested_pytest_args=requested_pytest_args,
                    ),
                    file=sys.stderr,
                )
                lock_file.close()
                return None

        lease = IntegrationRunLease(
            lock_file=lock_file,
            lock_path=lock_path,
            state_path=state_path,
            state=IntegrationRunState(
                pid=os.getpid(),
                ppid=os.getppid(),
                started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                requested_pytest_args=list(requested_pytest_args),
                requested_int_ids=_extract_int_ids_from_args(requested_pytest_args),
            ),
        )
        _write_json_atomic(lease.state_path, asdict(lease.state))
        return lease
    except Exception:
        lock_file.close()
        raise


def _refresh_integration_run_state(
    lease: IntegrationRunLease, **updates: object
) -> None:
    lease.update_state(**updates)


def _release_integration_run_lock(lease: IntegrationRunLease | None) -> None:
    if lease is None:
        return
    try:
        lease.state_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        lease.lock_file.close()
    except OSError:
        pass


def _ensure_postgres_database(db_name: str) -> None:
    escaped_db_name = db_name.replace("'", "''")
    check_db_cmd = [
        "docker",
        "compose",
        "-f",
        "docker-compose.test.yaml",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-d",
        "postgres",
        "-tAc",
        f"SELECT 1 FROM pg_database WHERE datname='{escaped_db_name}'",
    ]
    check_result = _run(
        check_db_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check_result.stdout.decode("utf-8", errors="ignore").strip() == "1":
        return

    _run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.test.yaml",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-c",
            f"CREATE DATABASE {db_name}",
        ]
    )


def _normalize_pytest_args(pytest_args: list[str]) -> tuple[list[str], bool, bool]:
    has_marker = False
    has_file = False

    for arg in pytest_args:
        if arg == "-m":
            has_marker = True
        if arg.startswith("tests/") or "/tests/" in arg:
            has_file = True

    normalized = list(pytest_args)
    if not has_marker and not has_file:
        if len(normalized) == 1:
            normalized = ["-m", normalized[0]]
        elif len(normalized) == 0:
            normalized = [
                "-m",
                "integration_p0 or integration_p1 or integration_p2 or integration",
            ]

    if not has_file:
        normalized.append("tests/integration")

    return normalized, has_marker, has_file


def _has_explicit_pytest_selection(pytest_args: list[str]) -> bool:
    """Detect whether the caller requested a custom pytest subset."""
    for arg in pytest_args:
        if arg in {"-m", "-k", "--last-failed", "--failed-first", "--lf", "--ff"}:
            return True
        if arg.startswith("-m") or arg.startswith("-k"):
            return True
        if arg.startswith("tests/") or "/tests/" in arg or "::" in arg:
            return True
    return False


def _ordered_integration_marker_slices() -> list[tuple[str, str]]:
    """Return the default integration slice order used by the runner."""
    return [
        ("integration_p0", "integration_p0"),
        (
            "integration_p1",
            "integration_p1 and not integration_p0 and not integration_agent",
        ),
        (
            "integration_agent",
            "integration_agent and not integration_p0",
        ),
        (
            "integration_p2",
            "integration_p2 and not integration_p0 and not integration_p1 and not integration_agent",
        ),
        (
            "integration_rest",
            "integration and not integration_p0 and not integration_p1 and not integration_p2 and not integration_agent",
        ),
    ]


def _merge_junit_xml_files(source_paths: list[Path], output_path: Path) -> None:
    """Combine multiple pytest junitxml files into one synthetic testsuite."""
    tests = failures = errors = skipped = 0
    duration = 0.0
    combined_cases: list[ET.Element] = []

    for source_path in source_paths:
        if not source_path.exists():
            continue
        try:
            tree = ET.parse(source_path)
        except ET.ParseError:
            continue

        root = tree.getroot()
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        for suite in suites:
            try:
                tests += int(suite.get("tests", "0") or 0)
                failures += int(suite.get("failures", "0") or 0)
                errors += int(suite.get("errors", "0") or 0)
                skipped += int(suite.get("skipped", "0") or 0)
                duration += float(suite.get("time", "0") or 0.0)
            except ValueError:
                pass
            combined_cases.extend(
                copy.deepcopy(case) for case in suite.findall("testcase")
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    testsuite = ET.Element(
        "testsuite",
        attrib={
            "name": "integration",
            "tests": str(tests),
            "failures": str(failures),
            "errors": str(errors),
            "skipped": str(skipped),
            "time": f"{duration:.6f}",
        },
    )
    for case in combined_cases:
        testsuite.append(case)

    testsuites = ET.Element("testsuites")
    testsuites.append(testsuite)
    ET.ElementTree(testsuites).write(
        output_path, encoding="utf-8", xml_declaration=True
    )


def _run_ordered_integration_pytest_slices(
    pytest_args: list[str],
    *,
    reverse: bool,
    junit_xml: str,
    early_stop_error_logs: list[Path] | None = None,
) -> int:
    """Run the default integration suite in deterministic marker buckets."""
    repo_root = _repo_root()
    junit_dir = repo_root / "test_output" / "junit_slices"
    junit_dir.mkdir(parents=True, exist_ok=True)

    slice_specs = _ordered_integration_marker_slices()
    if reverse:
        slice_specs = list(reversed(slice_specs))

    slice_reports: list[Path] = []
    for slice_name, marker_expr in slice_specs:
        slice_junit = junit_dir / f"{slice_name}.xml"
        slice_pytest_args = [
            *pytest_args,
            "-m",
            marker_expr,
            "tests/integration",
        ]
        _runner_status(f"Running integration slice {slice_name}: -m {marker_expr}")
        exit_code = run_pytest_subprocess(
            pytest_args=slice_pytest_args,
            reverse=reverse,
            junit_xml=str(slice_junit),
            early_stop_error_logs=early_stop_error_logs,
        )
        if exit_code == 5:
            _runner_status(
                f"Integration slice {slice_name} collected no tests; skipping."
            )
            continue
        slice_reports.append(slice_junit)
        if exit_code != 0:
            _merge_junit_xml_files(slice_reports, repo_root / junit_xml)
            return exit_code

    _merge_junit_xml_files(slice_reports, repo_root / junit_xml)
    return 0


def _frontend_available(repo_root: Path | None = None) -> bool:
    root = repo_root or _repo_root()
    return (root / "frontend").is_dir()


def _should_run_playwright(pytest_args: list[str]) -> bool:
    if not _frontend_available():
        return False

    marker_expr: str | None = None
    for idx, arg in enumerate(pytest_args):
        if arg == "-m" and idx + 1 < len(pytest_args):
            marker_expr = pytest_args[idx + 1]
            break

    if marker_expr and "integration_frontend" in marker_expr:
        return True

    explicit_frontend_selection = False
    integration_root_selected = False

    for arg in pytest_args:
        if arg.startswith("tests/e2e") or "/tests/e2e" in arg:
            return True
        if (
            arg.startswith("tests/integration/frontend")
            or "/tests/integration/frontend" in arg
        ):
            explicit_frontend_selection = True
        if arg == "tests/integration" or arg.endswith("/tests/integration"):
            integration_root_selected = True

    if explicit_frontend_selection:
        return True
    if marker_expr is not None:
        return False
    if integration_root_selected:
        return True
    return False


def _git_output(args: list[str]) -> str:
    completed = _run(
        args, check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.decode("utf-8", errors="ignore").strip()


def _is_non_test_frontend_source_file(file_path: str) -> bool:
    if not file_path.startswith("frontend/"):
        return False
    if ".test." in file_path or ".spec." in file_path:
        return False
    return not ("/__tests__/" in file_path or "/tests/" in file_path)


def _has_non_test_frontend_changes(files: list[str]) -> bool:
    return any(_is_non_test_frontend_source_file(item) for item in files if item)


def _should_rebuild_frontend(frontend_state_file: Path | None) -> bool:
    repo_root = _repo_root()
    dist_dir = repo_root / "frontend" / "dist"
    if not dist_dir.exists():
        return True

    unstaged = _git_output(
        ["git", "diff", "--name-only", "--", "frontend"]
    ).splitlines()
    staged = _git_output(
        ["git", "diff", "--cached", "--name-only", "--", "frontend"]
    ).splitlines()
    untracked = _git_output(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "frontend"]
    ).splitlines()
    if _has_non_test_frontend_changes(sorted(set(unstaged + staged + untracked))):
        return True

    if frontend_state_file is None or not frontend_state_file.exists():
        return True

    last_built_commit = frontend_state_file.read_text(encoding="utf-8").strip()
    if not last_built_commit:
        return True

    if (
        _run(
            ["git", "cat-file", "-e", f"{last_built_commit}^{{commit}}"], check=False
        ).returncode
        != 0
    ):
        return True

    changed_since = _git_output(
        ["git", "diff", "--name-only", f"{last_built_commit}..HEAD", "--", "frontend"]
    ).splitlines()
    return _has_non_test_frontend_changes(changed_since)


def _prepare_parts_db(repo_root: Path) -> None:
    parts_db = repo_root / "parts.db"
    needs_population = not parts_db.exists() or parts_db.stat().st_size == 0

    if not needs_population:
        return

    _runner_status("parts.db missing catalog entries. Populating COTS database...")
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    _run(["uv", "run", "python", "-m", "shared.cots.indexer"], env=env)


def _wait_for_temporal_stable_tcp(
    *,
    host: str = "127.0.0.1",
    port: int = 17233,
    timeout_s: float = 20.0,
    interval_s: float = 0.5,
    consecutive_successes: int = 4,
) -> None:
    started = time.monotonic()
    stable_count = 0
    while True:
        if _check_tcp(host, port, timeout_s=1.0):
            stable_count += 1
            if stable_count >= consecutive_successes:
                return
        else:
            stable_count = 0

        if time.monotonic() - started >= timeout_s:
            raise TimeoutError(
                f"Timed out waiting for temporal gRPC to become stable on {host}:{port}"
            )
        time.sleep(interval_s)


def _integration_infra_reachable_without_docker() -> bool:
    minio_ok = False
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:19000/minio/health/live", timeout=1.0
        ) as response:
            minio_ok = response.status == 200
    except Exception:
        minio_ok = False

    return (
        _check_tcp("127.0.0.1", 15432, timeout_s=1.0)
        and _check_tcp("127.0.0.1", 17233, timeout_s=1.0)
        and minio_ok
    )


def _bring_up_infra_and_migrate(
    integration_db_name: str, *, force_run_alembic: bool = False
) -> None:
    _runner_status("starting containers...")
    compose_cmd = [
        "docker",
        "compose",
        "-f",
        "docker-compose.test.yaml",
        "up",
        "-d",
        "--remove-orphans",
    ]
    compose_result = _run(
        compose_cmd,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if compose_result.returncode != 0:
        _runner_status(
            "docker compose up failed; checking whether integration infra is already reachable..."
        )
        if not _integration_infra_reachable_without_docker():
            raise subprocess.CalledProcessError(compose_result.returncode, compose_cmd)
        _runner_status(
            "Reusing already-running integration infra without docker compose access."
        )

    _runner_status("containers up")
    _runner_status("Waiting for infra to be ready...")
    infra_checks = [
        HealthCheck(name="postgres", kind="tcp", target="127.0.0.1:15432"),
        HealthCheck(
            name="minio",
            kind="http",
            target="http://127.0.0.1:19000/minio/health/live",
        ),
        HealthCheck(name="temporal", kind="tcp", target="127.0.0.1:17233"),
    ]
    asyncio.run(
        wait_for_checks_parallel(
            infra_checks,
            timeout_s=120.0,
            interval_s=0.5,
            probe_timeout_s=1.0,
        )
    )

    _runner_status("Infrastructure is up. Verifying Temporal gRPC stability...")
    _wait_for_temporal_stable_tcp()

    _runner_status("Purging local S3 buckets before the run...")
    _run(["uv", "run", "python", "scripts/cleanup_local_s3.py"])

    _runner_status(f"Ensuring integration database exists ({integration_db_name})...")
    _ensure_postgres_database(integration_db_name)

    _ensure_alembic_migrations(_repo_root(), force_run_alembic=force_run_alembic)


def _prepare_frontend_dist(repo_root: Path, frontend_state_file: Path | None) -> None:
    if _should_rebuild_frontend(frontend_state_file):
        _runner_status(
            "Building frontend (detected non-test frontend changes since last integration build or missing dist)..."
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = "."
        # CI checkouts do not have frontend node_modules populated, so install
        # the locked frontend toolchain before generating API clients or building.
        _run(["npm", "ci"], cwd=repo_root / "frontend")
        _run(["uv", "run", "python", "scripts/generate_openapi.py"], env=env)
        _run(["npm", "run", "gen:api"], cwd=repo_root / "frontend")
        production_env = repo_root / "frontend" / ".env.production"
        production_env.write_text(
            "VITE_API_URL=http://localhost:18000\nVITE_IS_INTEGRATION_TEST=true\n",
            encoding="utf-8",
        )
        shutil.rmtree(repo_root / "frontend" / "dist", ignore_errors=True)
        _run(["npm", "run", "build"], cwd=repo_root / "frontend")
        if frontend_state_file is not None:
            frontend_state_file.parent.mkdir(parents=True, exist_ok=True)
            frontend_state_file.write_text(
                _git_output(["git", "rev-parse", "HEAD"]) + "\n",
                encoding="utf-8",
            )
    else:
        _runner_status(
            "Skipping frontend build (no non-test frontend changes since last integration build)."
        )


@dataclass(frozen=True)
class ProcessSpec:
    name: str
    cmd: list[str]
    log_file: Path
    cwd: Path | None = None
    env_updates: dict[str, str] | None = None
    pid_file: Path | None = None


def _start_process(
    name: str,
    cmd: list[str],
    *,
    log_file: Path,
    cwd: Path | None = None,
    env_updates: dict[str, str] | None = None,
    pid_file: Path | None = None,
) -> StartedProcess:
    env = os.environ.copy()
    if env_updates:
        env.update(env_updates)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_file, "ab")
    process = subprocess.Popen(
        cmd,
        cwd=cwd or _repo_root(),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    handle.close()

    if pid_file is not None:
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(f"{process.pid}\n", encoding="utf-8")

    _runner_status(f"{name} started (PID: {process.pid})")
    return StartedProcess(name=name, process=process)


def _start_processes_parallel(specs: list[ProcessSpec]) -> list[StartedProcess]:
    ordered_results: list[StartedProcess | None] = [None] * len(specs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(specs)) as pool:
        future_to_index = {
            pool.submit(
                _start_process,
                spec.name,
                spec.cmd,
                log_file=spec.log_file,
                cwd=spec.cwd,
                env_updates=spec.env_updates,
                pid_file=spec.pid_file,
            ): index
            for index, spec in enumerate(specs)
        }
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            ordered_results[index] = future.result()

    return [result for result in ordered_results if result is not None]


def _archive_log_dir(log_dir: Path, archive_dir: Path) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    if log_dir.exists() and any(log_dir.iterdir()):
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        archive_target = archive_dir / f"run_{timestamp}"
        shutil.move(str(log_dir), str(archive_target))
    log_dir.mkdir(parents=True, exist_ok=True)

    now = time.time()
    cutoff_seconds = 24 * 60 * 60
    for child in archive_dir.glob("run_*"):
        try:
            if now - child.stat().st_mtime > cutoff_seconds:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
        except OSError:
            continue


def _prepare_integration_run_dir(logs_root: Path) -> Path:
    runs_root = logs_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    run_dir = runs_root / f"run_{time.strftime('%Y%m%d_%H%M%S')}"
    suffix = 1
    while run_dir.exists():
        run_dir = runs_root / f"{run_dir.name}_{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True, exist_ok=True)

    current_link = logs_root / "current"
    if current_link.exists() or current_link.is_symlink():
        current_link.unlink()
    current_link.symlink_to(run_dir.relative_to(logs_root))

    now = time.time()
    cutoff_seconds = 24 * 60 * 60
    for child in runs_root.glob("run_*"):
        try:
            if now - child.stat().st_mtime > cutoff_seconds:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
        except OSError:
            continue

    return run_dir


def _preemptive_cleanup() -> None:
    patterns = [
        "uvicorn.*18000",
        "uvicorn.*18001",
        "uvicorn.*18002",
        "python3 -m http.server 15173",
        "python -m controller.temporal_worker",
        "npm run dev",
        "vite",
        "npx serve",
        "Xvfb",
    ]
    for pattern in patterns:
        _run(["pkill", "-f", pattern], check=False)


def _final_force_cleanup(target_pids: list[int]) -> None:
    unique_pids = sorted(
        {pid for pid in target_pids if isinstance(pid, int) and pid > 0}
    )
    if not unique_pids:
        _runner_status(
            "No force-kill PID targets provided; skipping detached SIGKILL fallback."
        )
        return

    for pid in unique_pids:
        _run(["kill", "-9", str(pid)], check=False)


def _kill_port_occupants(ports: list[int]) -> None:
    """Terminate any local processes that are listening on the given TCP ports."""
    unique_ports = sorted(set(ports))
    if not unique_ports:
        return

    pids: set[int] = set()
    lsof_path = shutil.which("lsof")
    if lsof_path:
        for port in unique_ports:
            result = _run(
                [lsof_path, "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                continue
            for line in result.stdout.decode("utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.add(int(line))

    if pids:
        _runner_status(
            "Freeing occupied integration ports "
            f"{', '.join(str(port) for port in unique_ports)} "
            f"(PIDs: {', '.join(str(pid) for pid in sorted(pids))})"
        )
        for pid in sorted(pids):
            _run(["kill", str(pid)], check=False)
        time.sleep(1)
        for pid in sorted(pids):
            _run(["kill", "-9", str(pid)], check=False)

    fuser_path = shutil.which("fuser")
    if fuser_path:
        for port in unique_ports:
            _run([fuser_path, "-k", "-TERM", f"{port}/tcp"], check=False)
        time.sleep(0.5)
        for port in unique_ports:
            _run([fuser_path, "-k", "-KILL", f"{port}/tcp"], check=False)


def _stop_processes(processes: list[StartedProcess]) -> None:
    for started in processes:
        if started.process.poll() is None:
            started.process.terminate()

    deadline = time.time() + 5
    for started in processes:
        if started.process.poll() is not None:
            continue
        timeout = max(0.0, deadline - time.time())
        try:
            started.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            started.process.kill()


def _cleanup_pid_files(repo_root: Path) -> None:
    for pid_file in [
        repo_root / "logs" / "controller.pid",
        repo_root / "logs" / "temporal_worker.pid",
        repo_root / "logs" / "worker_heavy_temporal.pid",
        repo_root / "logs" / "worker_light.pid",
        repo_root / "logs" / "worker_renderer.pid",
        repo_root / "logs" / "worker_heavy.pid",
        repo_root / "logs" / "worker.pid",
        repo_root / "logs" / "frontend.pid",
    ]:
        pid_file.unlink(missing_ok=True)


def _cleanup_sessions_dir(sessions_dir: str) -> None:
    if Path(sessions_dir).exists():
        shutil.rmtree(sessions_dir, ignore_errors=True)


def _spawn_async_force_cleanup(
    *,
    repo_root: Path,
    delay_seconds: float,
    target_pids: list[int],
) -> None:
    cleanup_log = repo_root / "logs" / "integration_tests" / "cleanup.log"
    cleanup_log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "force-kill",
        "--delay-seconds",
        str(delay_seconds),
    ]
    for pid in sorted({pid for pid in target_pids if isinstance(pid, int) and pid > 0}):
        cmd.extend(["--pid", str(pid)])
    with cleanup_log.open("ab") as handle:
        subprocess.Popen(
            cmd,
            cwd=repo_root,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _spawn_async_cleanup(
    *,
    repo_root: Path,
    sessions_dir: str,
    down: bool,
    target_pids: list[int],
) -> None:
    cleanup_log = repo_root / "logs" / "integration_tests" / "cleanup.log"
    cleanup_log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "cleanup",
        "--repo-root",
        str(repo_root),
        "--sessions-dir",
        sessions_dir,
    ]
    if down:
        cmd.append("--down")
    for pid in sorted({pid for pid in target_pids if isinstance(pid, int) and pid > 0}):
        cmd.extend(["--pid", str(pid)])
    with cleanup_log.open("ab") as handle:
        subprocess.Popen(
            cmd,
            cwd=repo_root,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _run_cleanup_command(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    os.chdir(repo_root)

    target_pids = sorted(
        {
            int(pid)
            for pid in getattr(args, "pid", []) or []
            if str(pid).strip().isdigit() and int(pid) > 0
        }
    )
    _runner_status("Cleaning up processes...")
    _preemptive_cleanup()
    force_kill_grace_s = max(
        0.0,
        float(os.environ.get("INTEGRATION_FINAL_KILL_GRACE_SECONDS", "8")),
    )
    _spawn_async_force_cleanup(
        repo_root=repo_root,
        delay_seconds=force_kill_grace_s,
        target_pids=target_pids,
    )
    _runner_status(
        f"Scheduled detached force-kill fallback (grace={force_kill_grace_s:.1f}s)."
    )
    compose_project_name = os.environ.get("COMPOSE_PROJECT_NAME", "").strip()
    if compose_project_name:
        _stop_worker_renderer_container(compose_project_name=compose_project_name)
    _cleanup_pid_files(repo_root)
    _cleanup_sessions_dir(args.sessions_dir)

    compose_cmd = ["docker", "compose", "-f", "docker-compose.test.yaml"]
    if args.down:
        _runner_status(
            "Bringing down infrastructure containers (--down flag provided)..."
        )
        _run([*compose_cmd, "down", "-v", "--remove-orphans"], check=False)
    else:
        _runner_status("Stopping infrastructure containers...")
        _run([*compose_cmd, "stop"], check=False)
    return 0


def _run_force_kill_command(args: argparse.Namespace) -> int:
    delay_seconds = max(0.0, args.delay_seconds)
    if delay_seconds > 0:
        time.sleep(delay_seconds)
    target_pids = [
        int(pid)
        for pid in getattr(args, "pid", []) or []
        if str(pid).strip().isdigit() and int(pid) > 0
    ]
    _final_force_cleanup(target_pids)
    return 0


def _link_current_logs(run_playwright: bool) -> None:
    repo_root = _repo_root()
    logs_root = repo_root / "logs"
    integration_logs_root = logs_root / "integration_tests"
    current_prefix = "integration_tests/current"
    links = [
        (f"{current_prefix}/controller.log", "controller.log"),
        (f"{current_prefix}/controller_debug.log", "controller_debug.log"),
        (f"{current_prefix}/controller_errors.log", "controller_errors.log"),
        (f"{current_prefix}/json/controller_errors.json", "controller_errors.json"),
        (f"{current_prefix}/worker_light.log", "worker_light.log"),
        (f"{current_prefix}/worker_light_debug.log", "worker_light_debug.log"),
        (f"{current_prefix}/worker_light_errors.log", "worker_light_errors.log"),
        (f"{current_prefix}/json/worker_light_errors.json", "worker_light_errors.json"),
        (f"{current_prefix}/worker_renderer.log", "worker_renderer.log"),
        (f"{current_prefix}/worker_renderer_debug.log", "worker_renderer_debug.log"),
        (f"{current_prefix}/worker_renderer_errors.log", "worker_renderer_errors.log"),
        (
            f"{current_prefix}/json/worker_renderer_errors.json",
            "worker_renderer_errors.json",
        ),
        (f"{current_prefix}/worker_heavy.log", "worker_heavy.log"),
        (f"{current_prefix}/worker_heavy_debug.log", "worker_heavy_debug.log"),
        (f"{current_prefix}/worker_heavy_errors.log", "worker_heavy_errors.log"),
        (f"{current_prefix}/json/worker_heavy_errors.json", "worker_heavy_errors.json"),
        (f"{current_prefix}/worker_heavy_temporal.log", "worker_heavy_temporal.log"),
        (
            f"{current_prefix}/worker_heavy_temporal_debug.log",
            "worker_heavy_temporal_debug.log",
        ),
        (
            f"{current_prefix}/worker_heavy_temporal_errors.log",
            "worker_heavy_temporal_errors.log",
        ),
        (
            f"{current_prefix}/json/worker_heavy_temporal_errors.json",
            "worker_heavy_temporal_errors.json",
        ),
        (f"{current_prefix}/temporal_worker.log", "temporal_worker.log"),
        (f"{current_prefix}/temporal_worker_debug.log", "temporal_worker_debug.log"),
        (f"{current_prefix}/temporal_worker_errors.log", "temporal_worker_errors.log"),
        (
            f"{current_prefix}/json/temporal_worker_errors.json",
            "temporal_worker_errors.json",
        ),
        (f"{current_prefix}/full_test_output.log", "full_test_output.log"),
    ]
    if run_playwright:
        links.extend(
            [
                (f"{current_prefix}/frontend.log", "frontend.log"),
                (f"{current_prefix}/browser_console.log", "browser_console.log"),
            ]
        )

    logs_root.mkdir(parents=True, exist_ok=True)
    integration_logs_root.mkdir(parents=True, exist_ok=True)
    for target, link_name in links:
        link_path = logs_root / link_name
        try:
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            link_path.symlink_to(target)
        except OSError:
            continue

    integration_compat_links = [
        "controller.log",
        "controller_debug.log",
        "controller_errors.log",
        "worker_light.log",
        "worker_light_debug.log",
        "worker_light_errors.log",
        "worker_renderer.log",
        "worker_renderer_debug.log",
        "worker_renderer_errors.log",
        "worker_heavy.log",
        "worker_heavy_debug.log",
        "worker_heavy_errors.log",
        "worker_heavy_temporal.log",
        "worker_heavy_temporal_debug.log",
        "worker_heavy_temporal_errors.log",
        "temporal_worker.log",
        "temporal_worker_debug.log",
        "temporal_worker_errors.log",
        "frontend.log",
        "browser_console.log",
        "full_test_output.log",
    ]
    for name in integration_compat_links:
        compat_path = integration_logs_root / name
        try:
            if compat_path.exists() or compat_path.is_symlink():
                compat_path.unlink()
            compat_path.symlink_to(Path("current") / name)
        except OSError:
            continue

    integration_json_compat = integration_logs_root / "json"
    integration_json_compat.mkdir(parents=True, exist_ok=True)
    for name in [
        "controller_errors.json",
        "worker_light_errors.json",
        "worker_heavy_errors.json",
        "worker_heavy_temporal_errors.json",
        "temporal_worker_errors.json",
        "backend_error_allowlisted_prefixes.json",
    ]:
        compat_path = integration_json_compat / name
        try:
            if compat_path.exists() or compat_path.is_symlink():
                compat_path.unlink()
            compat_path.symlink_to(Path("..") / "current" / "json" / name)
        except OSError:
            continue


def _run_wait_command(args: argparse.Namespace) -> int:
    checks: list[HealthCheck] = []
    checks.extend(_parse_check(item, kind="http") for item in args.http_check)
    checks.extend(_parse_check(item, kind="tcp") for item in args.tcp_check)
    checks.extend(_parse_check(item, kind="cmd") for item in args.cmd_check)

    if not checks:
        print("No checks provided.", file=sys.stderr)
        return 2

    started = time.monotonic()
    try:
        results = asyncio.run(
            wait_for_checks_parallel(
                checks,
                timeout_s=args.timeout,
                interval_s=args.interval,
                probe_timeout_s=args.probe_timeout,
            )
        )
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    total = time.monotonic() - started
    print(f"All checks passed in {total:.2f}s")
    for name, elapsed in sorted(results.items()):
        print(f"  - {name}: {elapsed:.2f}s")
    return 0


def _run_pytest_command(args: argparse.Namespace) -> int:
    pytest_args = args.pytest_args
    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:]
    return run_pytest_subprocess(
        pytest_args=pytest_args,
        reverse=args.reverse,
        junit_xml=args.junit_xml,
    )


def _run_integration_command(
    args: argparse.Namespace, passthrough_pytest_args: list[str]
) -> int:
    repo_root = _repo_root()
    os.chdir(repo_root)
    command_started_at = time.monotonic()

    normalized_pytest_args, _, _ = _normalize_pytest_args(passthrough_pytest_args)
    lease = _acquire_integration_run_lock(
        queue=args.queue,
        requested_pytest_args=normalized_pytest_args,
    )
    if lease is None:
        return 1
    _refresh_integration_run_state(
        lease, current_int_ids=list(lease.state.requested_int_ids)
    )

    _runner_status(f"Integration Tests Started at: {time.ctime()}", always=True)

    os.environ["IS_INTEGRATION_TEST"] = "true"
    os.environ.setdefault("LOG_LEVEL", "INFO")
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["SMOKE_TEST_MODE"] = "true"

    integration_db_name = "problemologist_integration"
    integration_db_url = (
        f"postgresql+asyncpg://postgres:postgres@127.0.0.1:15432/{integration_db_name}"
    )

    os.environ["TEMPORAL_URL"] = "127.0.0.1:17233"
    os.environ["S3_ENDPOINT"] = "http://127.0.0.1:19000"
    os.environ["S3_ENDPOINT_URL"] = "http://127.0.0.1:19000"
    os.environ["S3_ACCESS_KEY"] = "minioadmin"
    os.environ["S3_SECRET_KEY"] = "minioadmin"
    os.environ["AWS_ACCESS_KEY_ID"] = "minioadmin"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "minioadmin"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["WORKER_URL"] = "http://127.0.0.1:18001"
    os.environ["WORKER_HEAVY_URL"] = "http://127.0.0.1:18002"
    os.environ["WORKER_RENDERER_URL"] = "http://127.0.0.1:18003"
    os.environ["ASSET_S3_BUCKET"] = "problemologist"
    os.environ["BACKUP_S3_BUCKET"] = "problemologist-backup"
    os.environ["BENCHMARK_SOURCE_BUCKET"] = "benchmarks-source"
    os.environ["BENCHMARK_ASSETS_BUCKET"] = "benchmarks-assets"
    os.environ["GENESIS_FORCE_CPU"] = "1"

    sessions_dir = tempfile.mkdtemp(prefix="pb-sessions-")
    os.environ["WORKER_SESSIONS_DIR"] = sessions_dir
    _runner_status(f"Shared sessions directory: {sessions_dir}")

    if args.no_smoke:
        _runner_status("High-fidelity simulation ENABLED (smoke test mode DISABLED)")
        os.environ["SMOKE_TEST_MODE"] = "false"

    _load_env_file(repo_root / ".env")
    stack_profile = apply_stack_profile_env(
        "integration", env=os.environ, root=repo_root
    )
    os.environ["IS_INTEGRATION_TEST"] = "true"
    os.environ["SMOKE_TEST_MODE"] = "true"
    os.environ["TEMPORAL_URL"] = "127.0.0.1:17233"
    os.environ["S3_ENDPOINT"] = "http://127.0.0.1:19000"
    os.environ["S3_ENDPOINT_URL"] = "http://127.0.0.1:19000"
    os.environ["S3_ACCESS_KEY"] = "minioadmin"
    os.environ["S3_SECRET_KEY"] = "minioadmin"
    os.environ["AWS_ACCESS_KEY_ID"] = "minioadmin"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "minioadmin"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["WORKER_URL"] = "http://127.0.0.1:18001"
    os.environ["WORKER_HEAVY_URL"] = "http://127.0.0.1:18002"
    os.environ["ASSET_S3_BUCKET"] = "problemologist"
    os.environ["BACKUP_S3_BUCKET"] = "problemologist-backup"
    os.environ["BENCHMARK_SOURCE_BUCKET"] = "benchmarks-source"
    os.environ["BENCHMARK_ASSETS_BUCKET"] = "benchmarks-assets"
    os.environ["GENESIS_FORCE_CPU"] = "1"
    os.environ["WORKER_SESSIONS_DIR"] = sessions_dir

    _run(["bash", "scripts/env_down.sh", "--profile", "integration"])

    if args.full_sim:
        os.environ["SIMULATION_DEFAULT_BACKEND"] = "GENESIS"
        _runner_status("Full-fidelity simulation backend selected: Genesis")
    else:
        os.environ["SIMULATION_DEFAULT_BACKEND"] = "MUJOCO"
        _runner_status("Fast simulation backend selected: MuJoCo")

    # Keep integration-test infra deterministic even when .env defines DB URLs.
    os.environ["POSTGRES_URL"] = integration_db_url
    os.environ["DATABASE_URL"] = integration_db_url

    pytest_args = normalized_pytest_args
    run_playwright = _should_run_playwright(pytest_args)
    git_dir = _git_output(["git", "rev-parse", "--git-dir"]) if run_playwright else ""
    frontend_state_file = (
        Path(git_dir) / "problemologist_integration_frontend_build_commit"
        if git_dir
        else None
    )

    _kill_port_occupants([15173, 18000, 18001, 18002, 18003, 15432, 17233, 19000])

    _run(["bash", "scripts/ensure_docker_vfs.sh"])
    _runner_status(
        "Preparing prerequisites in parallel (infra, parts DB"
        + (", frontend build" if run_playwright else "")
        + ")..."
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        prep_futures: list[concurrent.futures.Future[object]] = [
            pool.submit(
                _bring_up_infra_and_migrate,
                integration_db_name,
                force_run_alembic=args.force_run_alembic,
            ),
            pool.submit(_prepare_parts_db, repo_root),
        ]
        if run_playwright:
            prep_futures.append(
                pool.submit(_prepare_frontend_dist, repo_root, frontend_state_file)
            )
        for future in concurrent.futures.as_completed(prep_futures):
            future.result()

    _runner_status(
        "Starting Application Servers (Controller, Worker, Renderer Container)..."
    )

    integration_logs_root = repo_root / "logs" / "integration_tests"
    log_dir = _prepare_integration_run_dir(integration_logs_root)
    json_log_dir = log_dir / "json"
    os.environ["INTEGRATION_LOG_DIR"] = str(log_dir)
    _refresh_integration_run_state(lease, current_log_dir=str(log_dir))
    _preemptive_cleanup()

    processes: list[StartedProcess] = []
    frontend_pid_path = repo_root / "logs" / "frontend.pid"

    # Keep teardown synchronous so the shared integration lock remains held
    # until the environment is fully quiesced.
    async_cleanup_enabled = False
    cleanup_target_pids: list[int] = []

    try:
        pythonpath = os.environ.get("PYTHONPATH", "")
        combined_pythonpath = f"{pythonpath}:." if pythonpath else "."
        session_log_root = log_dir / "sessions"
        os.environ["WORKER_RENDERER_LOG_DIR"] = str(log_dir)
        _start_worker_renderer_container(
            compose_project_name=stack_profile.compose_project_name,
            log_file=log_dir / "worker_renderer.log",
        )
        processes.extend(
            _start_processes_parallel(
                [
                    ProcessSpec(
                        name="Worker Light",
                        cmd=[
                            "uv",
                            "run",
                            "uvicorn",
                            "worker_light.app:app",
                            "--host",
                            "0.0.0.0",
                            "--port",
                            "18001",
                        ],
                        log_file=log_dir / "worker_light.log",
                        env_updates={
                            "WORKER_TYPE": "light",
                            "EXTRA_DEBUG_LOG": str(log_dir / "worker_light_debug.log"),
                            "EXTRA_ERROR_LOG": str(log_dir / "worker_light_errors.log"),
                            "EXTRA_ERROR_JSON_LOG": str(
                                json_log_dir / "worker_light_errors.json"
                            ),
                            "SESSION_LOG_ROOT": str(session_log_root),
                        },
                        pid_file=repo_root / "logs" / "worker_light.pid",
                    ),
                    ProcessSpec(
                        name="Worker Heavy",
                        cmd=[
                            "uv",
                            "run",
                            "uvicorn",
                            "worker_heavy.app:app",
                            "--host",
                            "0.0.0.0",
                            "--port",
                            "18002",
                        ],
                        log_file=log_dir / "worker_heavy.log",
                        env_updates={
                            "WORKER_TYPE": "heavy",
                            "EXTRA_DEBUG_LOG": str(log_dir / "worker_heavy_debug.log"),
                            "EXTRA_ERROR_LOG": str(log_dir / "worker_heavy_errors.log"),
                            "EXTRA_ERROR_JSON_LOG": str(
                                json_log_dir / "worker_heavy_errors.json"
                            ),
                            "SESSION_LOG_ROOT": str(session_log_root),
                        },
                        pid_file=repo_root / "logs" / "worker_heavy.pid",
                    ),
                    ProcessSpec(
                        name="Controller",
                        cmd=[
                            "uv",
                            "run",
                            "uvicorn",
                            "controller.api.main:app",
                            "--host",
                            "0.0.0.0",
                            "--port",
                            "18000",
                        ],
                        log_file=log_dir / "controller.log",
                        env_updates={
                            "EXTRA_DEBUG_LOG": str(log_dir / "controller_debug.log"),
                            "EXTRA_ERROR_LOG": str(log_dir / "controller_errors.log"),
                            "EXTRA_ERROR_JSON_LOG": str(
                                json_log_dir / "controller_errors.json"
                            ),
                            "SESSION_LOG_ROOT": str(session_log_root),
                        },
                        pid_file=repo_root / "logs" / "controller.pid",
                    ),
                ]
            )
        )

        if run_playwright:
            processes.append(
                _start_process(
                    "Frontend server",
                    [
                        "npx",
                        "http-server",
                        "-p",
                        "15173",
                        "--proxy",
                        "http://localhost:18000?",
                    ],
                    cwd=repo_root / "frontend" / "dist",
                    log_file=log_dir / "frontend.log",
                    pid_file=frontend_pid_path,
                )
            )
            _runner_status("Frontend server available on http://localhost:15173")

        cleanup_target_pids = [started.process.pid for started in processes]

        _link_current_logs(run_playwright)

        _runner_status("Waiting for servers to be healthy...")
        server_checks = [
            HealthCheck(
                name="controller",
                kind="http",
                target="http://127.0.0.1:18000/health",
                contains="healthy",
            ),
            HealthCheck(
                name="worker-light",
                kind="http",
                target="http://127.0.0.1:18001/health",
                contains="healthy",
            ),
            HealthCheck(
                name="worker-renderer",
                kind="http",
                target="http://127.0.0.1:18003/health",
                contains="healthy",
            ),
            HealthCheck(
                name="worker-heavy",
                kind="http",
                target="http://127.0.0.1:18002/health",
                contains="healthy",
            ),
        ]
        if run_playwright:
            server_checks.append(
                HealthCheck(
                    name="frontend", kind="http", target="http://127.0.0.1:15173"
                )
            )

        asyncio.run(
            wait_for_checks_parallel(
                server_checks,
                timeout_s=120.0,
                interval_s=0.5,
                probe_timeout_s=1.0,
            )
        )

        for started in processes:
            if started.name == "Frontend server" and not run_playwright:
                continue
            if started.process.poll() is not None:
                print(f"{started.name} died unexpectedly!", file=sys.stderr)
                return 1

        (repo_root / "test_output").mkdir(parents=True, exist_ok=True)
        ordered_marker_splits_enabled = (
            os.environ.get("INTEGRATION_ORDERED_MARKER_SPLITS", "0").strip() == "1"
        )
        if ordered_marker_splits_enabled and not _has_explicit_pytest_selection(
            passthrough_pytest_args
        ):
            pytest_exit = _run_ordered_integration_pytest_slices(
                pytest_args=passthrough_pytest_args,
                reverse=args.reverse,
                junit_xml="test_output/junit.xml",
                early_stop_error_logs=[
                    json_log_dir / "controller_errors.json",
                    json_log_dir / "worker_light_errors.json",
                    json_log_dir / "worker_renderer_errors.json",
                    json_log_dir / "worker_heavy_errors.json",
                    # Temporal worker services are not part of the active
                    # integration boundary in this repo snapshot.
                ],
            )
        else:
            pytest_exit = run_pytest_subprocess(
                pytest_args=pytest_args,
                reverse=args.reverse,
                junit_xml="test_output/junit.xml",
                early_stop_error_logs=[
                    json_log_dir / "controller_errors.json",
                    json_log_dir / "worker_light_errors.json",
                    json_log_dir / "worker_renderer_errors.json",
                    json_log_dir / "worker_heavy_errors.json",
                    # Temporal worker services are not part of the active
                    # integration boundary in this repo snapshot.
                ],
            )

        _run(["uv", "run", "python", "scripts/persist_test_results.py"], check=False)

        if pytest_exit == 0:
            _runner_status("Integration tests PASSED!", always=True)
        else:
            _runner_status("Integration tests FAILED!", always=True)

        _runner_status(f"Integration Tests Finished at: {time.ctime()}", always=True)
        return pytest_exit
    finally:
        try:
            _stop_processes(processes)
            if async_cleanup_enabled:
                _runner_status("Scheduling async teardown in background...")
                _spawn_async_cleanup(
                    repo_root=repo_root,
                    sessions_dir=sessions_dir,
                    down=args.down,
                    target_pids=cleanup_target_pids,
                )
            else:
                _run_cleanup_command(
                    argparse.Namespace(
                        repo_root=str(repo_root),
                        sessions_dir=sessions_dir,
                        down=args.down,
                        pid=cleanup_target_pids,
                    )
                )
        finally:
            _release_integration_run_lock(lease)
            _maybe_notify_long_integration_run(time.monotonic() - command_started_at)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal integration test helpers")
    sub = parser.add_subparsers(dest="command", required=True)

    wait_parser = sub.add_parser("wait", help="Run readiness checks in parallel")
    wait_parser.add_argument(
        "--http-check",
        action="append",
        default=[],
        help="HTTP check: name|url|contains (contains optional)",
    )
    wait_parser.add_argument(
        "--tcp-check",
        action="append",
        default=[],
        help="TCP check: name|host:port",
    )
    wait_parser.add_argument(
        "--cmd-check",
        action="append",
        default=[],
        help="Command check: name|command",
    )
    wait_parser.add_argument("--timeout", type=float, default=120.0)
    wait_parser.add_argument("--interval", type=float, default=0.5)
    wait_parser.add_argument("--probe-timeout", type=float, default=1.0)

    pytest_parser = sub.add_parser("run-pytest", help="Run pytest as a subprocess")
    pytest_parser.add_argument("--reverse", action="store_true")
    pytest_parser.add_argument("--junit-xml", default="test_output/junit.xml")
    pytest_parser.add_argument("pytest_args", nargs=argparse.REMAINDER)

    run_parser = sub.add_parser("run", help="Run full integration orchestration")
    run_parser.add_argument("--reverse", action="store_true")
    run_parser.add_argument("--down", action="store_true")
    run_parser.add_argument("--no-smoke", action="store_true")
    sim_mode_group = run_parser.add_mutually_exclusive_group()
    sim_mode_group.add_argument(
        "--full-sim",
        dest="full_sim",
        action="store_true",
        help="Use the full-fidelity simulation backend for this run.",
    )
    sim_mode_group.add_argument(
        "--fast-sim",
        dest="full_sim",
        action="store_false",
        help="Use the faster MuJoCo backend for this run (default).",
    )
    sim_mode_group.add_argument(
        "--no-full-sim",
        dest="full_sim",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    run_parser.set_defaults(full_sim=False)
    run_parser.add_argument(
        "--wait-cleanup",
        action="store_true",
        help="Wait for teardown instead of scheduling cleanup in the background.",
    )
    run_parser.add_argument(
        "--queue",
        action="store_true",
        help="Wait for the shared integration lock instead of failing fast when another run is active.",
    )
    run_parser.add_argument(
        "--force-run-alembic",
        action="store_true",
        help="Run Alembic migrations even if the database already appears to be at head.",
    )

    migrate_parser = sub.add_parser(
        "migrate", help="Ensure the configured database schema is at Alembic head"
    )
    migrate_parser.add_argument(
        "--force-run-alembic",
        action="store_true",
        help="Run Alembic migrations even if the database already appears to be at head.",
    )

    cleanup_parser = sub.add_parser(
        "cleanup", help="Internal: perform integration teardown."
    )
    cleanup_parser.add_argument("--repo-root", required=True)
    cleanup_parser.add_argument("--sessions-dir", required=True)
    cleanup_parser.add_argument("--down", action="store_true")
    cleanup_parser.add_argument("--pid", action="append", default=[])

    force_kill_parser = sub.add_parser(
        "force-kill",
        help="Internal: force-kill leftover integration processes (SIGKILL).",
    )
    force_kill_parser.add_argument("--delay-seconds", type=float, default=0.0)
    force_kill_parser.add_argument("--pid", action="append", default=[])

    return parser


def main() -> int:
    parser = _build_parser()
    args, unknown = parser.parse_known_args()

    if args.command == "wait":
        if unknown:
            parser.error(
                f"Unrecognized arguments for wait: {' '.join(shlex.quote(arg) for arg in unknown)}"
            )
        return _run_wait_command(args)

    if args.command == "run-pytest":
        if unknown:
            parser.error(
                f"Unrecognized arguments for run-pytest: {' '.join(shlex.quote(arg) for arg in unknown)}"
            )
        return _run_pytest_command(args)

    if args.command == "run":
        passthrough = list(unknown)
        if passthrough and passthrough[0] == "--":
            passthrough = passthrough[1:]
        return _run_integration_command(args, passthrough)

    if args.command == "migrate":
        if unknown:
            parser.error(
                "Unrecognized arguments for migrate: "
                f"{' '.join(shlex.quote(arg) for arg in unknown)}"
            )
        _ensure_alembic_migrations(
            _repo_root(), force_run_alembic=args.force_run_alembic
        )
        return 0

    if args.command == "cleanup":
        if unknown:
            parser.error(
                "Unrecognized arguments for cleanup: "
                f"{' '.join(shlex.quote(arg) for arg in unknown)}"
            )
        return _run_cleanup_command(args)

    if args.command == "force-kill":
        if unknown:
            parser.error(
                "Unrecognized arguments for force-kill: "
                f"{' '.join(shlex.quote(arg) for arg in unknown)}"
            )
        return _run_force_kill_command(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
