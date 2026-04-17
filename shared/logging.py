import json
import logging
import os
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import structlog
from structlog.types import Processor

from shared.enums import AgentName

_SESSION_KEY_INT_RE = re.compile(r"(INT-\d{3})", re.IGNORECASE)
_SESSION_KEY_EVAL_RE = re.compile(r"\b([a-z]{1,12}-\d{3})\b", re.IGNORECASE)
_TEST_NODE_INT_RE = re.compile(r"test_int_(\d{3})", re.IGNORECASE)
_SAFE_PATH_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SESSION_FANOUT_LOCK = threading.Lock()
_NOISY_LOGGER_PREFIXES = ("build123d",)


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _resolve_session_folder_key(event_dict: dict) -> str | None:
    integration_test_id = event_dict.get("integration_test_id")
    if isinstance(integration_test_id, str):
        match = _SESSION_KEY_INT_RE.search(integration_test_id)
        if match:
            return match.group(1).upper()

    session_id = event_dict.get("session_id")
    if isinstance(session_id, str):
        int_match = _SESSION_KEY_INT_RE.search(session_id)
        if int_match:
            return int_match.group(1).upper()
        eval_match = _SESSION_KEY_EVAL_RE.search(session_id)
        if eval_match:
            return eval_match.group(1).lower()
        normalized = session_id.strip()
        if normalized:
            return _SAFE_PATH_CHARS_RE.sub("_", normalized)[:80]

    test_id = event_dict.get("test_id")
    if isinstance(test_id, str):
        int_match = _SESSION_KEY_INT_RE.search(test_id)
        if int_match:
            return int_match.group(1).upper()
        node_match = _TEST_NODE_INT_RE.search(test_id)
        if node_match:
            return f"INT-{node_match.group(1)}"

    return None


def _append_session_fanout_line(
    *,
    root_dir: Path,
    folder_key: str,
    service_name: str,
    payload: dict,
    is_error: bool,
) -> None:
    safe_key = _SAFE_PATH_CHARS_RE.sub("_", folder_key).strip("._-") or "unscoped"
    safe_service = _SAFE_PATH_CHARS_RE.sub("_", service_name).strip("._-") or "service"
    session_dir = root_dir / safe_key
    session_dir.mkdir(parents=True, exist_ok=True)
    target = session_dir / f"{safe_service}.log"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    if is_error:
        error_target = session_dir / f"{safe_service}_errors.log"
        with error_target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _normalize_context_value(value):
    if value is None:
        return None
    if isinstance(value, AgentName):
        return value.value
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    return str(value)


def _should_drop_noisy_record(record: logging.LogRecord) -> bool:
    return any(
        record.name == prefix or record.name.startswith(f"{prefix}.")
        for prefix in _NOISY_LOGGER_PREFIXES
    )


@contextmanager
def bind_log_context(**context):
    """
    Temporarily bind structlog contextvars for the current execution scope.

    Use this for per-request or per-task metadata such as session_id, agent_role,
    and stage so downstream structlog events inherit the same identifiers.
    """
    normalized = {
        key: _normalize_context_value(value)
        for key, value in context.items()
        if value is not None
    }
    if not normalized:
        yield
        return

    tokens = structlog.contextvars.bind_contextvars(**normalized)
    try:
        yield
    finally:
        structlog.contextvars.reset_contextvars(**tokens)


def configure_logging(service_name: str):
    """
    Configure structlog for the given service.

    In production (LOG_FORMAT=json), it outputs JSON.
    Otherwise, it outputs colored text for development.

    Supports EXTRA_DEBUG_LOG environment variable to output DEBUG logs to a file
    while keeping stdout at LOG_LEVEL.
    """
    log_format = os.getenv("LOG_FORMAT", "console").lower()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level_num = getattr(logging, log_level, logging.INFO)

    # Extra debug log file
    extra_debug_log = os.getenv("EXTRA_DEBUG_LOG")
    extra_error_log = os.getenv("EXTRA_ERROR_LOG")
    extra_error_json_log = os.getenv("EXTRA_ERROR_JSON_LOG")
    session_log_root_raw = os.getenv("SESSION_LOG_ROOT", "").strip()
    session_log_root = (
        Path(os.path.abspath(session_log_root_raw)) if session_log_root_raw else None
    )

    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            }
        ),
    ]

    # Session context processor
    def add_service_context(logger, method_name, event_dict):
        event_dict["service"] = service_name
        return event_dict

    processors.insert(0, add_service_context)

    # Optional machine-readable dedicated error stream.
    # Emit native structlog event dicts as JSON lines for integration tooling.
    if extra_error_json_log:
        extra_error_json_log_abs = os.path.abspath(extra_error_json_log)
        os.makedirs(os.path.dirname(extra_error_json_log_abs), exist_ok=True)

        def persist_error_json(logger, method_name, event_dict):
            level = str(event_dict.get("level", method_name)).lower()
            if level in {"error", "exception", "critical"}:
                payload = _json_safe(dict(event_dict))
                payload.setdefault("service", service_name)
                try:
                    with open(
                        extra_error_json_log_abs, "a", encoding="utf-8"
                    ) as handle:
                        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                except OSError:
                    # Never block application logging if the sidecar file cannot be written.
                    pass
            return event_dict

        processors.append(persist_error_json)

    if session_log_root is not None:
        session_log_root.mkdir(parents=True, exist_ok=True)

        def persist_session_scoped_log(logger, method_name, event_dict):
            folder_key = _resolve_session_folder_key(event_dict)
            if not folder_key:
                return event_dict

            payload = _json_safe(dict(event_dict))
            payload.setdefault("service", service_name)
            level = str(event_dict.get("level", method_name)).lower()
            is_error = level in {"error", "exception", "critical"}
            try:
                with _SESSION_FANOUT_LOCK:
                    _append_session_fanout_line(
                        root_dir=session_log_root,
                        folder_key=folder_key,
                        service_name=service_name,
                        payload=payload,
                        is_error=is_error,
                    )
            except OSError:
                pass
            return event_dict

        processors.append(persist_session_scoped_log)

    if log_format == "json":
        processors.append(structlog.processors.dict_tracebacks)
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Root logger configuration
    root_logger = logging.getLogger()

    # Clear existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level_num)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    console_handler.addFilter(lambda record: not _should_drop_noisy_record(record))
    root_logger.addHandler(console_handler)

    # Optional file handler for DEBUG logs
    if extra_debug_log:
        # Ensure directory exists
        extra_debug_log_abs = os.path.abspath(extra_debug_log)
        os.makedirs(os.path.dirname(extra_debug_log_abs), exist_ok=True)
        file_handler = logging.FileHandler(extra_debug_log_abs)
        file_handler.setLevel(logging.DEBUG)

        # We use a simple formatter because structlog already formatted the message
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        file_handler.addFilter(lambda record: not _should_drop_noisy_record(record))
        root_logger.addHandler(file_handler)

        # If we have a debug file, root must be at least DEBUG to let messages through
        root_logger.setLevel(logging.DEBUG)
    else:
        root_logger.setLevel(log_level_num)

    # Optional dedicated file handler for ERROR+ logs only.
    # This provides a high-signal stream for integration test gating.
    if extra_error_log:
        extra_error_log_abs = os.path.abspath(extra_error_log)
        os.makedirs(os.path.dirname(extra_error_log_abs), exist_ok=True)
        error_handler = logging.FileHandler(extra_error_log_abs)
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(logging.Formatter("%(message)s"))
        error_handler.addFilter(lambda record: not _should_drop_noisy_record(record))
        root_logger.addHandler(error_handler)

    # Ensure uvicorn loggers follow the global level and propagate to root
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        u_logger = logging.getLogger(logger_name)
        u_logger.handlers = []
        u_logger.propagate = True
        u_logger.setLevel(logging.DEBUG if extra_debug_log else log_level_num)

    # Silence noisy third-party loggers. build123d is intentionally fully
    # suppressed because notebook runs create many transient geometry objects
    # and the library emits very chatty construction logs.
    for noisy_logger in (
        "build123d",
        "botocore",
        "boto3",
        "s3transfer",
        "urllib3",
        "httpcore",
        "httpx",
    ):
        noisy_logger_obj = logging.getLogger(noisy_logger)
        if noisy_logger == "build123d":
            noisy_logger_obj.disabled = True
            noisy_logger_obj.propagate = False
        noisy_logger_obj.setLevel(logging.WARNING)

    # Keep access logs at INFO for visibility during debugging unless debug file is on
    if not extra_debug_log:
        access_logger = logging.getLogger("uvicorn.access")
        access_logger.setLevel(logging.INFO)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def set_trace_context(trace_id: str, span_id: str | None = None):
    """Set trace information in the current context."""
    structlog.contextvars.bind_contextvars(trace_id=trace_id)
    if span_id:
        structlog.contextvars.bind_contextvars(span_id=span_id)


def log_marker_middleware():
    """
    Returns a FastAPI middleware that extracts session and test IDs
    and binds them to the structlog context.
    """
    from fastapi import Request
    from starlette.middleware.base import BaseHTTPMiddleware

    class LogMarkerMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Extract markers
            session_id = request.headers.get("X-Session-ID")
            test_id = request.headers.get("X-Integration-Test-ID")
            agent_role = (
                request.headers.get("X-Agent-Role")
                or request.headers.get("X-Stage")
                or request.headers.get("X-Reviewer-Stage")
            )
            stage = (
                request.headers.get("X-Stage")
                or request.headers.get("X-Reviewer-Stage")
                or agent_role
            )
            query_marker = request.query_params.get("marker")

            # Clear context and bind new markers for the lifetime of this request.
            structlog.contextvars.clear_contextvars()
            with bind_log_context(
                session_id=session_id,
                test_id=test_id,
                agent_role=agent_role,
                stage=stage,
            ):
                if query_marker:
                    # Log a prominent marker if requested via query param
                    logger = structlog.get_logger("marker")
                    logger.info(f"\n\n{'=' * 20} {query_marker} {'=' * 20}\n")

                return await call_next(request)

    return LogMarkerMiddleware
