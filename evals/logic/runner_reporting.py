from __future__ import annotations

import ast
import contextlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from evals.logic.codex_session_trace import CodexSessionTraceArtifact
from evals.logic.models import HardCheckFailurePointer, HardCheckRunLogPointer

_DRAWING_EVAL_KEY_RE = re.compile(
    r"([a-z]{1,12}-\d{3}-drawing-(?:off|minimal|full))", re.IGNORECASE
)
_EVAL_KEY_RE = re.compile(r"([a-z]{1,12}-\d{3})", re.IGNORECASE)
_ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_RUN_LOG_EVENT_RE = re.compile(r"\[[^\]]+\]\s+([A-Za-z0-9_]+)\s+\[[^\]]+\]")
_ERROR_LOG_CANDIDATE_FILES = (
    "evals_errors.log",
    "controller_errors.log",
    "worker_light_errors.log",
    "worker_renderer_errors.log",
    "worker_heavy_errors.log",
    "worker-light_errors.log",
    "worker-heavy_errors.log",
    "json/evals_errors.json",
    "json/controller_errors.json",
    "json/worker_light_errors.json",
    "json/worker_renderer_errors.json",
    "json/worker_heavy_errors.json",
)
_MAX_POINTER_CODES = 8
_MAX_POINTER_MESSAGES = 8
_MAX_POINTER_SOURCES = 8
_MAX_POINTER_LOGS = 24
_MAX_RUN_LOG_POINTERS = 3


@dataclass(slots=True)
class RunnerLogContext:
    root: Path
    readable_agent_log_file: Path | None = None
    session_log_root: Path | None = None


def _console_message(message: str) -> None:
    print(message, flush=True)


def _eval_case_label(item: Any, agent_name: Any, mode: Any) -> str:
    episode_id = getattr(item, "id", item)
    agent_label = getattr(agent_name, "value", agent_name)
    mode_label = getattr(mode, "value", mode)
    return f"{agent_label} {episode_id} [{mode_label}]"


def _emit_startup_log_pointers(*, current_link: Path, root: Path) -> None:
    _console_message("Eval log files:")
    _console_message(
        f"{_path_for_report(current_link / 'run_evals.log', root=root)} - structured runner log for this run"
    )
    _console_message(
        f"{_path_for_report(current_link / 'readable_agent_logs.log', root=root)} - condensed human-readable agent trace"
    )
    _console_message(
        f"{_path_for_report(current_link / 'sessions', root=root)} - per-eval session logs and trace fanout"
    )
    _console_message(
        f"{_path_for_report(current_link / 'hard_check_pass_rates.yaml', root=root)} - hard-check summary written at the end"
    )
    _console_message(
        f"{_path_for_report(current_link / 'judge_pass_rates.yaml', root=root)} - judge/checklist summary written when --run-judge is enabled"
    )


def _truncate_text(value: str, *, limit: int = 160) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _sanitize_readable_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""

    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        with contextlib.suppress(json.JSONDecodeError):
            decoded = json.loads(text)
            if isinstance(decoded, str):
                text = decoded

    text = text.encode("utf-8", "backslashreplace").decode("unicode_escape")
    text = "".join(ch if ch.isprintable() or ch in "\n\t" else " " for ch in text)
    text = " ".join(part for part in text.replace("\t", " ").split())
    return text.strip()


def _parse_trace_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(text)

    return None


def _format_elapsed_prefix(*, episode: dict[str, Any], trace: dict[str, Any]) -> str:
    episode_started_at = _parse_trace_datetime(episode.get("created_at"))
    trace_started_at = _parse_trace_datetime(trace.get("created_at"))
    if episode_started_at is None or trace_started_at is None:
        return "t=0s | "

    elapsed_seconds = int((trace_started_at - episode_started_at).total_seconds())
    if elapsed_seconds < 0:
        elapsed_seconds = 0
    return f"t={elapsed_seconds}s | "


def _short_run_label(episode: dict[str, Any]) -> str:
    metadata = episode.get("metadata_vars") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    for candidate in (
        metadata.get("benchmark_id"),
        metadata.get("worker_session_id"),
        episode.get("id"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()[:7]

    return "unknown"


def _parse_trace_json_content(raw_content: Any) -> dict[str, Any] | None:
    if not isinstance(raw_content, str):
        return None

    with contextlib.suppress(json.JSONDecodeError):
        parsed = json.loads(raw_content)
        if isinstance(parsed, dict):
            return parsed

    with contextlib.suppress(ValueError, SyntaxError):
        parsed = ast.literal_eval(raw_content)
        if isinstance(parsed, dict):
            return parsed

    return None


def _strip_ansi(value: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", value)


def _extract_run_log_event(line: str) -> str:
    match = _RUN_LOG_EVENT_RE.search(line)
    if not match:
        return ""
    return _sanitize_readable_text(match.group(1))


def _path_for_report(path: Path, *, root: Path) -> str:
    with contextlib.suppress(ValueError):
        return str(path.relative_to(root))
    return str(path)


def _append_unique_limited(target: list[str], value: Any, *, limit: int) -> None:
    text = _sanitize_readable_text(value)
    if not text:
        return
    if text in target:
        return
    if len(target) >= limit:
        return
    target.append(text)


def _line_matches_tokens(line: str, *, tokens: list[str]) -> bool:
    if not line:
        return False
    lowered = line.lower()
    for token in tokens:
        if token and token in lowered:
            return True
    return False


def _iter_failure_log_paths(
    *,
    session_dir: Path,
    log_context: RunnerLogContext,
) -> list[Path]:
    search_roots: list[Path] = [session_dir]
    if log_context.session_log_root is not None:
        search_roots.append(log_context.session_log_root / "system")
        search_roots.append(log_context.session_log_root.parent)

    candidates: list[Path] = []
    seen: set[str] = set()
    for root in search_roots:
        if not root.exists():
            continue
        for rel_path in _ERROR_LOG_CANDIDATE_FILES:
            path = root / rel_path
            if not path.exists():
                continue
            with contextlib.suppress(OSError):
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
            candidates.append(path)
    return candidates


def _record_matches_failure_scope(
    *,
    line_text: str,
    parsed: dict[str, Any] | None,
    session_id: str,
    episode_id: str,
    task_id: str,
    strict_scope: bool,
) -> bool:
    if strict_scope:
        return True

    tokens = [
        _sanitize_readable_text(session_id).lower(),
        _sanitize_readable_text(episode_id).lower(),
        _sanitize_readable_text(task_id).lower(),
    ]
    if _line_matches_tokens(line_text, tokens=tokens):
        return True

    if not isinstance(parsed, dict):
        return False

    for key in ("session_id", "episode_id", "task_id", "seed_id", "benchmark_id"):
        value = _sanitize_readable_text(parsed.get(key)).lower()
        if value and value in tokens:
            return True
    return False


def _collect_run_log_pointers(
    *,
    run_log_path: Path,
    session_id: str,
    episode_id: str,
    task_id: str,
    preferred_events: list[str],
    log_context: RunnerLogContext,
) -> list[HardCheckRunLogPointer]:
    if not run_log_path.exists():
        return []

    session_token = _sanitize_readable_text(session_id).lower()
    episode_token = _sanitize_readable_text(episode_id).lower()
    task_token = _sanitize_readable_text(task_id).lower()
    event_tokens = [token.lower() for token in preferred_events if token]
    matches: list[tuple[int, int, str, str]] = []

    with contextlib.suppress(Exception):
        with run_log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                clean_line = _sanitize_readable_text(_strip_ansi(raw_line))
                if not clean_line:
                    continue

                event_name = _extract_run_log_event(clean_line)
                event_token = event_name.lower()
                line_token = clean_line.lower()
                preferred_event_match = bool(
                    event_token and event_token in event_tokens
                ) or _line_matches_tokens(line_token, tokens=event_tokens)
                errorish_line = (
                    "[error" in line_token
                    or " traceback" in line_token
                    or " failed" in line_token
                    or "exception" in line_token
                )
                has_scope_match = any(
                    (
                        session_token and session_token in line_token,
                        episode_token and episode_token in line_token,
                        task_token and task_token in line_token,
                    )
                )

                if not has_scope_match and not preferred_event_match:
                    continue
                if not preferred_event_match and not errorish_line:
                    continue

                score = 0
                if session_token and session_token in line_token:
                    score += 5
                if episode_token and episode_token in line_token:
                    score += 4
                if task_token and task_token in line_token:
                    score += 3
                if preferred_event_match:
                    score += 4
                if errorish_line:
                    score += 1

                if score <= 0:
                    continue

                matches.append((score, line_number, event_name, clean_line))

    if not matches:
        return []

    matches.sort(key=lambda row: (row[0], row[1]), reverse=True)
    pointers: list[HardCheckRunLogPointer] = []
    seen_lines: set[int] = set()
    report_path = _path_for_report(run_log_path, root=log_context.root)
    for _, line_number, event_name, clean_line in matches:
        if line_number in seen_lines:
            continue
        seen_lines.add(line_number)
        pointers.append(
            HardCheckRunLogPointer(
                path=report_path,
                line=line_number,
                event=event_name or None,
                hint=_truncate_text(clean_line, limit=220),
            )
        )
        if len(pointers) >= _MAX_RUN_LOG_POINTERS:
            break

    return pointers


def _build_seed_failure_pointer(
    *,
    task_id: str,
    session_id: str,
    episode_data: dict[str, Any] | None,
    log_context: RunnerLogContext,
    failure_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    episode_id = _sanitize_readable_text((episode_data or {}).get("id"))
    pointer = HardCheckFailurePointer(
        session_id=session_id or None,
        session_status=(
            _sanitize_readable_text((episode_data or {}).get("status"))
            if isinstance(episode_data, dict)
            else None
        )
        or None,
    )

    if isinstance(failure_context, dict):
        context_status = _sanitize_readable_text(failure_context.get("session_status"))
        if context_status:
            pointer.session_status = context_status

        _append_unique_limited(
            pointer.error_codes,
            failure_context.get("error_code"),
            limit=_MAX_POINTER_CODES,
        )
        _append_unique_limited(
            pointer.error_messages,
            failure_context.get("error_message"),
            limit=_MAX_POINTER_MESSAGES,
        )
        _append_unique_limited(
            pointer.error_sources,
            failure_context.get("error_source"),
            limit=_MAX_POINTER_SOURCES,
        )

    if log_context.session_log_root is None:
        return pointer.model_dump(mode="json")

    eval_log_key = _resolve_eval_log_key(task_id=task_id, session_id=session_id)
    session_dir = log_context.session_log_root / eval_log_key
    pointer.session_log_dir = _path_for_report(session_dir, root=log_context.root)

    metadata_path = session_dir / "session_metadata.json"
    _append_unique_limited(
        pointer.log_pointers,
        _path_for_report(metadata_path, root=log_context.root),
        limit=_MAX_POINTER_LOGS,
    )
    if metadata_path.exists():
        with contextlib.suppress(Exception):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(metadata, dict):
                metadata_status = _sanitize_readable_text(metadata.get("status"))
                if metadata_status and not pointer.session_status:
                    pointer.session_status = metadata_status

    run_log_path = log_context.session_log_root.parent / "run_evals.log"
    run_log_pointers = _collect_run_log_pointers(
        run_log_path=run_log_path,
        session_id=session_id,
        episode_id=episode_id,
        task_id=task_id,
        preferred_events=list(pointer.error_codes),
        log_context=log_context,
    )
    pointer.run_log_pointers.extend(run_log_pointers)
    if run_log_pointers:
        _append_unique_limited(
            pointer.log_pointers,
            _path_for_report(run_log_path, root=log_context.root),
            limit=_MAX_POINTER_LOGS,
        )

    for log_path in _iter_failure_log_paths(
        session_dir=session_dir, log_context=log_context
    ):
        _append_unique_limited(
            pointer.log_pointers,
            _path_for_report(log_path, root=log_context.root),
            limit=_MAX_POINTER_LOGS,
        )
        strict_scope = log_path.is_relative_to(session_dir)
        with contextlib.suppress(Exception):
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue

                    parsed: dict[str, Any] | None = None
                    with contextlib.suppress(json.JSONDecodeError):
                        parsed_candidate = json.loads(stripped)
                        if isinstance(parsed_candidate, dict):
                            parsed = parsed_candidate

                    clean_line = _sanitize_readable_text(_strip_ansi(stripped))
                    if not _record_matches_failure_scope(
                        line_text=clean_line.lower(),
                        parsed=parsed,
                        session_id=session_id,
                        episode_id=episode_id,
                        task_id=task_id,
                        strict_scope=strict_scope,
                    ):
                        continue

                    if parsed is None:
                        _append_unique_limited(
                            pointer.error_messages,
                            _truncate_text(clean_line, limit=220),
                            limit=_MAX_POINTER_MESSAGES,
                        )
                        continue

                    _append_unique_limited(
                        pointer.error_codes,
                        parsed.get("event"),
                        limit=_MAX_POINTER_CODES,
                    )
                    _append_unique_limited(
                        pointer.error_messages,
                        parsed.get("error"),
                        limit=_MAX_POINTER_MESSAGES,
                    )
                    _append_unique_limited(
                        pointer.error_messages,
                        parsed.get("exception"),
                        limit=_MAX_POINTER_MESSAGES,
                    )
                    _append_unique_limited(
                        pointer.error_messages,
                        parsed.get("response_text"),
                        limit=_MAX_POINTER_MESSAGES,
                    )
                    for err in parsed.get("errors") or []:
                        _append_unique_limited(
                            pointer.error_messages,
                            _truncate_text(str(err), limit=220),
                            limit=_MAX_POINTER_MESSAGES,
                        )

                    source_file = _sanitize_readable_text(parsed.get("filename"))
                    source_line = parsed.get("lineno")
                    if source_file:
                        if isinstance(source_line, int):
                            source_ref = f"{source_file}:{source_line}"
                        else:
                            source_ref = source_file
                        _append_unique_limited(
                            pointer.error_sources,
                            source_ref,
                            limit=_MAX_POINTER_SOURCES,
                        )

    return pointer.model_dump(mode="json")


def _format_tool_args(trace: dict[str, Any]) -> str:
    parsed = _parse_trace_json_content(trace.get("content"))
    if parsed is None:
        raw = _sanitize_readable_text(trace.get("content"))
        return _truncate_text(raw, limit=120) if raw else ""

    kwargs = parsed.get("kwargs")
    args = parsed.get("args")
    parts: list[str] = []

    if isinstance(kwargs, dict):
        preferred_keys = (
            "path",
            "file_path",
            "target_path",
            "directory",
            "command",
            "cmd",
            "query",
            "prompt",
            "plan_path",
            "script_path",
            "backend",
        )
        for key in preferred_keys:
            value = kwargs.get(key)
            if value in (None, "", [], {}, ()):
                continue
            parts.append(
                f"{key}={_truncate_text(_sanitize_readable_text(value), limit=80)}"
            )

        if not parts:
            for key, value in kwargs.items():
                if value in (None, "", [], {}, ()):
                    continue
                if key in {"content", "review_content"}:
                    continue
                parts.append(
                    f"{key}={_truncate_text(_sanitize_readable_text(value), limit=60)}"
                )
                if len(parts) >= 3:
                    break

    if not parts and isinstance(args, list):
        for value in args[:3]:
            parts.append(_truncate_text(_sanitize_readable_text(value), limit=60))

    return " ".join(parts)


def _format_reasoning_suffix(metadata: dict[str, Any]) -> str:
    suffix_parts: list[str] = []
    step_index = metadata.get("reasoning_step_index")
    if isinstance(step_index, int):
        suffix_parts.append(f"step={step_index}")

    source = _sanitize_readable_text(metadata.get("reasoning_source"))
    if source:
        suffix_parts.append(f"source={source}")

    if not suffix_parts:
        return ""
    return " [" + " ".join(suffix_parts) + "]"


def _extract_output_text(content: Any) -> str:
    text = _sanitize_readable_text(content)
    if not text:
        return ""

    marker = "Result:"
    if marker not in text:
        return text

    _, result_text = text.split(marker, 1)
    result_text = result_text.strip()
    return result_text or text


def _format_readable_trace_line(
    *,
    episode: dict[str, Any],
    trace: dict[str, Any],
    default_agent_name: str,
    detail_mode: str = "default",
) -> str | None:
    trace_type = str(trace.get("trace_type") or "").upper()
    run_label = _short_run_label(episode)
    metadata = trace.get("metadata_vars") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    if trace_type == "LLM_END" and detail_mode == "default":
        agent_name = _sanitize_readable_text(trace.get("name")) or default_agent_name
        prefix = _format_elapsed_prefix(episode=episode, trace=trace)
        prefix += f"{agent_name} | {run_label} | "
        text = _sanitize_readable_text(trace.get("content"))
        if not text:
            return None
        return (
            prefix
            + "REASONING"
            + _format_reasoning_suffix(metadata)
            + " "
            + _truncate_text(text, limit=220)
        )

    if trace_type == "LOG" and detail_mode == "default":
        agent_name = _sanitize_readable_text(trace.get("name")) or default_agent_name
        prefix = _format_elapsed_prefix(episode=episode, trace=trace)
        prefix += f"{agent_name} | {run_label} | "
        text = _extract_output_text(trace.get("content"))
        if not text:
            return None
        return prefix + "OUTPUT " + _truncate_text(text, limit=220)

    if trace_type != "TOOL_START":
        return None

    prefix = f"{default_agent_name} | {run_label} | "
    prefix = _format_elapsed_prefix(episode=episode, trace=trace) + prefix
    error_text = _sanitize_readable_text(metadata.get("error"))
    if detail_mode == "error":
        if not error_text:
            return None
        return (
            prefix
            + "TOOL "
            + _sanitize_readable_text(trace.get("name"))
            + (f" ERROR {error_text}")
        )

    observation_text = _sanitize_readable_text(metadata.get("observation"))
    if detail_mode == "result":
        if not observation_text:
            return None
        return (
            prefix
            + "RESULT "
            + _sanitize_readable_text(trace.get("name"))
            + " "
            + _truncate_text(observation_text, limit=220)
        )

    tool_name = _sanitize_readable_text(trace.get("name"))
    tool_args = _format_tool_args(trace)
    base = prefix + "TOOL " + tool_name
    if tool_args:
        base += " " + tool_args
    return base


def _resolve_eval_log_key(*, task_id: str, session_id: str = "") -> str:
    for source in (task_id, session_id):
        if not source:
            continue
        drawing_match = _DRAWING_EVAL_KEY_RE.search(source)
        if drawing_match:
            return drawing_match.group(1).lower()
        match = _EVAL_KEY_RE.search(source)
        if match:
            return match.group(1).lower()
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", task_id.strip())
    return fallback[:80] or "unscoped"


def _append_readable_log_line(
    line: str,
    *,
    log_context: RunnerLogContext,
    eval_log_key: str | None = None,
) -> None:
    if (
        log_context.readable_agent_log_file is None
        and log_context.session_log_root is None
    ):
        return

    if log_context.readable_agent_log_file is not None:
        log_context.readable_agent_log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_context.readable_agent_log_file.open("a", encoding="utf-8") as handle:
            handle.write(line.rstrip() + "\n")
    if log_context.session_log_root is not None and eval_log_key:
        session_file = (
            log_context.session_log_root / eval_log_key / "readable_agent_logs.log"
        )
        session_file.parent.mkdir(parents=True, exist_ok=True)
        with session_file.open("a", encoding="utf-8") as handle:
            handle.write(line.rstrip() + "\n")


def _mirror_session_trace_to_readable_logs(
    trace_artifacts: CodexSessionTraceArtifact,
    *,
    log_context: RunnerLogContext,
    eval_log_key: str | None,
) -> None:
    transcript_path = trace_artifacts.transcript_path
    session_id = _sanitize_readable_text(trace_artifacts.session_id)
    if transcript_path is None:
        _append_readable_log_line(
            f"CODEX_SESSION_TRACE_IMPORTED session_id={session_id} transcript_path=None",
            log_context=log_context,
            eval_log_key=eval_log_key,
        )
        return

    _append_readable_log_line(
        "CODEX_SESSION_TRACE_IMPORTED "
        f"session_id={session_id} "
        f"transcript_path={_sanitize_readable_text(str(transcript_path))}",
        log_context=log_context,
        eval_log_key=eval_log_key,
    )
    try:
        transcript_text = transcript_path.read_text(encoding="utf-8")
    except Exception as exc:
        _append_readable_log_line(
            "CODEX_SESSION_TRACE_READ_FAILED "
            f"session_id={session_id} "
            f"error={_sanitize_readable_text(exc)}",
            log_context=log_context,
            eval_log_key=eval_log_key,
        )
        return

    for line in transcript_text.splitlines():
        if line.strip():
            _append_readable_log_line(
                line, log_context=log_context, eval_log_key=eval_log_key
            )


_mirror_codex_session_trace_to_readable_logs = _mirror_session_trace_to_readable_logs


def _write_eval_session_metadata(
    *,
    log_context: RunnerLogContext,
    eval_log_key: str | None,
    payload: dict[str, Any],
) -> None:
    if log_context.session_log_root is None or not eval_log_key:
        return
    metadata_path = (
        log_context.session_log_root / eval_log_key / "session_metadata.json"
    )
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _append_jsonl_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
