import contextlib
import datetime
import os
import re
import time
from functools import lru_cache
from pathlib import Path

import httpx
import pytest

from evals.logic.seed_maintenance import refresh_repo_seed_artifact_manifests
from tests.integration.agent.helpers import load_integration_mock_scenarios

pytest_plugins = ["tests.support.fixtures.browser"]

SERVICES = [
    "http://127.0.0.1:18000",  # Controller
    "http://127.0.0.1:18001",  # Worker Light
    "http://127.0.0.1:18002",  # Worker Heavy
]
WORKER_HEAVY_URL = os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002")

# Temporary baseline allowlist for known frontend noise.
# Goal: keep strict mode actionable while we iteratively eliminate existing issues.
DEFAULT_BROWSER_ERROR_ALLOWLIST = [
    r"Failed to parse assembly definition for electronics kb",
    r"Failed to fetch episodes",
    r"TypeError: Failed to fetch",
    r"Failed to hydrate episode after status update TypeError: Failed to fetch",
    r"Failed to load resource: net::ERR_CONNECTION_REFUSED",
    r"Connection check failed: TypeError: Failed to fetch",
    r"Polling failed TypeError: Failed to fetch",
    r"WebSocket connection to .+ failed: Error in connection establishment: net::ERR_CONNECTION_REFUSED",
    r"WebSocket error Event",
]

BACKEND_ERROR_LOG_FILES = {
    "controller": Path("logs/integration_tests/controller_errors.log"),
    "worker_light": Path("logs/integration_tests/worker_light_errors.log"),
    "worker_heavy": Path("logs/integration_tests/worker_heavy_errors.log"),
    "temporal_worker": Path("logs/integration_tests/temporal_worker_errors.log"),
}

INTEGRATION_WORKFLOW_HINT = (
    "If this is a startup timeout or health-check failure, the run is likely "
    "not going through ./scripts/run_integration_tests.sh. Follow the "
    "integration-tests-workflow and use the runner instead of plain pytest."
)


def _is_integration_test(request: pytest.FixtureRequest) -> bool:
    return (
        any(m.name.startswith("integration") for m in request.node.iter_markers())
        or "integration" in request.node.nodeid
    )


def _is_integration_item(item: pytest.Item) -> bool:
    return (
        any(m.name.startswith("integration") for m in item.iter_markers())
        or "integration" in item.nodeid
    )


def _extract_test_int_id(nodeid: str) -> str | None:
    match = re.search(r"test_int_(\d{3})", nodeid, re.IGNORECASE)
    if not match:
        return None
    return f"INT-{match.group(1)}"


def _manifest_update_disabled_for_request(request: pytest.FixtureRequest) -> bool:
    if request.node.get_closest_marker("disable_manifest_update"):
        return True

    disabled_int_ids_raw = os.getenv("MANIFEST_UPDATE_DISABLED_INT_IDS", "").strip()
    if not disabled_int_ids_raw:
        return False

    disabled_int_ids = {
        value.strip().upper()
        for value in disabled_int_ids_raw.split(";;")
        if value.strip()
    }
    current_int_id = _extract_test_int_id(request.node.nodeid)
    return bool(current_int_id and current_int_id in disabled_int_ids)


def _should_enforce_integration_readiness(pytestconfig: pytest.Config) -> bool:
    if os.getenv("IS_INTEGRATION_TEST", "").lower() == "true":
        return True

    markexpr = str(getattr(pytestconfig.option, "markexpr", "") or "")
    if "integration" in markexpr:
        return True

    args = [str(arg) for arg in pytestconfig.invocation_params.args]
    return any("tests/integration" in arg or "tests/e2e" in arg for arg in args)


def _wait_for_service_health_stable(
    service_url: str,
    *,
    client: httpx.Client,
    timeout_s: float = 20.0,
    interval_s: float = 0.25,
    consecutive_successes: int = 3,
) -> None:
    deadline = time.monotonic() + timeout_s
    stable = 0

    while time.monotonic() < deadline:
        try:
            response = client.get(f"{service_url}/health")
            if response.status_code == 200:
                stable += 1
                if stable >= consecutive_successes:
                    return
            else:
                stable = 0
        except Exception:
            stable = 0
        time.sleep(interval_s)

    pytest.exit(
        f"{service_url}/health did not become stable "
        f"({consecutive_successes} consecutive successes required). "
        f"{INTEGRATION_WORKFLOW_HINT}",
        returncode=1,
    )


@pytest.fixture(scope="session", autouse=True)
def ensure_services_are_ready(pytestconfig: pytest.Config):
    """
    Integration-only startup gate.
    Requires stable /health responses before tests execute to avoid cold-start races.
    """
    if not _should_enforce_integration_readiness(pytestconfig):
        return

    with httpx.Client(timeout=2.0) as client:
        for service_url in SERVICES:
            _wait_for_service_health_stable(service_url, client=client)


@pytest.fixture(scope="session", autouse=True)
def ensure_integration_mock_scenario_ids(pytestconfig: pytest.Config):
    """
    Integration-only startup gate.
    Enforce strict scenario IDs and file-backed fixtures in tests/integration/mock_responses/.
    """
    if not _should_enforce_integration_readiness(pytestconfig):
        return

    try:
        load_integration_mock_scenarios()
    except Exception as exc:
        pytest.fail(
            f"Invalid integration mock scenarios in tests/integration/mock_responses/: {exc}"
        )


@lru_cache(maxsize=1)
def _refresh_seed_manifests_once(repo_root: str) -> tuple[str, ...]:
    updated_paths = refresh_repo_seed_artifact_manifests(Path(repo_root), fix=True)
    return tuple(str(path) for path in updated_paths)


@pytest.fixture(autouse=True)
def ensure_seed_manifests_current(request):
    """
    Keep deterministic seed manifests fresh during integration runs.

    The repair is default-on and cached for the session so the steady-state path stays
    cheap. Tests that intentionally exercise stale-manifest behavior can opt out with
    @pytest.mark.disable_manifest_update.
    """
    if not _is_integration_test(request):
        yield
        return

    if os.getenv("AUTO_MANIFEST_UPDATE", "1") != "1":
        yield
        return

    if _manifest_update_disabled_for_request(request):
        yield
        return

    repo_root = str(Path(__file__).resolve().parents[1])
    with contextlib.suppress(Exception):
        _refresh_seed_manifests_once(repo_root)

    yield


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", text)


def _compile_backend_error_allowlist() -> list[re.Pattern[str]]:
    raw_patterns = [
        p.strip()
        for p in os.getenv("BACKEND_ERROR_ALLOWLIST_REGEXES", "").split(";;")
        if p.strip()
    ]
    return [re.compile(pattern, re.IGNORECASE) for pattern in raw_patterns]


def _match_backend_issue(line: str, allowlist: list[re.Pattern[str]]) -> str | None:
    normalized = _strip_ansi(line).strip()
    if not normalized:
        return None
    if any(pattern.search(normalized) for pattern in allowlist):
        return None
    return normalized


def _backend_error_requires_attribution_id(normalized_line: str) -> bool:
    """Return True when a structured backend error line must include an attribution id."""
    low = normalized_line.lower()
    # Dedicated backend error logs are structured; enforce only on structured records.
    return "[error" in low and "service=" in normalized_line


def _backend_error_has_session_id(normalized_line: str) -> bool:
    """Accept either key=value or JSON-style key formatting for session_id."""
    return (
        "session_id=" in normalized_line
        or '"session_id":' in normalized_line
        or "'session_id':" in normalized_line
    )


def _backend_error_has_episode_id(normalized_line: str) -> bool:
    """Accept either key=value or JSON-style key formatting for episode_id."""
    return (
        "episode_id=" in normalized_line
        or '"episode_id":' in normalized_line
        or "'episode_id':" in normalized_line
    )


def _extract_backend_error_session_id(normalized_line: str) -> str | None:
    """Extract session_id from a structured error log line, if present."""
    patterns = [
        r"session_id=UUID\('([^']+)'\)",
        r"session_id=\"([^\"]+)\"",
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


def _extract_backend_error_episode_id(normalized_line: str) -> str | None:
    """Extract episode_id from a structured error log line, if present."""
    patterns = [
        r"episode_id=UUID\('([^']+)'\)",
        r"episode_id=\"([^\"]+)\"",
        r"episode_id='([^']+)'",
        r"episode_id=([^\s]+)",
        r'"episode_id"\s*:\s*"([^"]+)"',
        r"'episode_id'\s*:\s*'([^']+)'",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized_line)
        if not match:
            continue
        candidate = (match.group(1) or "").strip().strip(",")
        if candidate:
            return candidate
    return None


def _collect_expected_test_session_ids(request: pytest.FixtureRequest) -> set[str]:
    """Best-effort extraction of current test-owned session ids from fixture values."""
    sessions: set[str] = set()
    funcargs = getattr(request.node, "funcargs", {}) or {}

    def _add(value: str | None) -> None:
        if not isinstance(value, str):
            return
        v = value.strip()
        if not v:
            return
        sessions.add(v)
        sessions.add(v.lower())

    for name, value in funcargs.items():
        if isinstance(value, str) and name in {"session_id", "user_session_id"}:
            _add(value)
            continue

        if isinstance(value, dict):
            header_sid = value.get("X-Session-ID")
            if isinstance(header_sid, str):
                _add(header_sid)
            for key in ("session_id", "user_session_id"):
                sid = value.get(key)
                if isinstance(sid, str):
                    _add(sid)

    # Some fixtures are not populated in request.node.funcargs at this autouse stage.
    # Pull common session-bearing fixtures explicitly when declared on the test.
    for fixture_name in ("session_id", "base_headers"):
        if fixture_name not in request.fixturenames:
            continue
        with contextlib.suppress(Exception):
            value = request.getfixturevalue(fixture_name)
            if isinstance(value, str) and fixture_name == "session_id":
                _add(value)
            elif isinstance(value, dict):
                header_sid = value.get("X-Session-ID")
                if isinstance(header_sid, str):
                    _add(header_sid)

    return sessions


def _compile_browser_error_allowlist() -> list[re.Pattern[str]]:
    """
    Build an allowlist of browser error regexes.
    Add custom patterns with BROWSER_ERROR_ALLOWLIST_REGEXES separated by `;;`.
    """
    raw_patterns = [*DEFAULT_BROWSER_ERROR_ALLOWLIST]
    raw_patterns.extend(
        p.strip()
        for p in os.getenv("BROWSER_ERROR_ALLOWLIST_REGEXES", "").split(";;")
        if p.strip()
    )
    return [re.compile(pattern, re.IGNORECASE) for pattern in raw_patterns]


def _is_allowed_browser_error(text: str, allowlist: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in allowlist)


def _has_marker(request: pytest.FixtureRequest, marker_name: str) -> bool:
    """Robust marker presence check for fixture gating."""
    return any(marker.name == marker_name for marker in request.node.iter_markers())


def _compile_marker_regex_allowlist(
    request: pytest.FixtureRequest, marker_name: str
) -> tuple[bool, list[re.Pattern[str]]]:
    """
    Parse marker-provided regex allowlist.
    - No-arg marker is forbidden; explicit regexes are required.
    - Marker args/kwargs define scoped regex allowlist.
    """
    patterns: list[str] = []
    has_allow_all = False

    for marker in request.node.iter_markers(name=marker_name):
        if not marker.args and not marker.kwargs:
            raise pytest.UsageError(
                f"@{marker_name} requires explicit regex patterns; "
                "catch-all usage is forbidden."
            )

        for arg in marker.args:
            if isinstance(arg, str) and arg.strip():
                patterns.append(arg.strip())

        for key in ("regexes", "patterns", "pattern"):
            value = marker.kwargs.get(key)
            if isinstance(value, str) and value.strip():
                patterns.append(value.strip())
            elif isinstance(value, (list, tuple, set)):
                patterns.extend(
                    str(item).strip() for item in value if str(item).strip()
                )

    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            raise pytest.UsageError(
                f"Invalid regex in @{marker_name}: {pattern!r} ({exc})"
            ) from exc

    return has_allow_all, compiled


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Expose test call outcome on node so fixtures can adjust teardown behavior."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


@pytest.fixture(autouse=True)
def capture_frontend_logs(request):
    """
    Automatically hooks into the Playwright 'page' fixture (if present) to capture
    console logs and page errors into logs/integration_tests/browser_console.log.
    """
    # Only run for tests that use the 'page' fixture (Playwright)
    if "page" not in request.fixturenames:
        yield
        return

    # request.getfixturevalue("page") will trigger instantiation of the 'page' fixture
    page = request.getfixturevalue("page")
    test_id = request.node.nodeid
    log_dir = "logs/integration_tests"
    log_file = os.path.join(log_dir, "browser_console.log")
    allow_browser_errors = _has_marker(request, "allow_browser_errors")
    strict_mode = os.getenv("STRICT_BROWSER_ERRORS", "1") == "1"
    allowlist = _compile_browser_error_allowlist()
    unexpected_browser_errors: list[str] = []

    # Ensure log directory exists
    os.makedirs(log_dir, exist_ok=True)

    def handle_console(msg):
        # We want to exclude some extremely noisy logs if necessary,
        # but for now, capture everything.
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with open(log_file, "a") as f:
            f.write(f"[{timestamp}] [{test_id}] [{msg.type.upper()}] {msg.text}\n")
        if msg.type == "error":
            text = msg.text or ""
            if not _is_allowed_browser_error(text, allowlist):
                unexpected_browser_errors.append(f"console.error: {text}")

    def handle_error(exc):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        error_text = str(exc)
        with open(log_file, "a") as f:
            f.write(f"[{timestamp}] [{test_id}] [BROWSER_EXCEPTION] {error_text}\n")
        if not _is_allowed_browser_error(error_text, allowlist):
            unexpected_browser_errors.append(f"pageerror: {error_text}")

    page.on("console", handle_console)
    page.on("pageerror", handle_error)

    # Initial marker in console log to delimit tests
    with open(log_file, "a") as f:
        f.write(f"\n--- START TEST BROWSER LOG: {test_id} ---\n")

    yield

    with open(log_file, "a") as f:
        f.write(f"--- FINISH TEST BROWSER LOG: {test_id} ---\n")

    rep_call = getattr(request.node, "rep_call", None)
    test_call_failed = bool(rep_call and rep_call.failed)
    if (
        strict_mode
        and not allow_browser_errors
        and not test_call_failed
        and unexpected_browser_errors
    ):
        sample = "\n".join(f"- {line}" for line in unexpected_browser_errors[:10])
        overflow = len(unexpected_browser_errors) - 10
        suffix = f"\n- ... and {overflow} more" if overflow > 0 else ""
        pytest.fail(
            "Unexpected browser errors detected.\n"
            f"{sample}{suffix}\n"
            f"See detailed browser logs in {log_file}.\n"
            "If this test explicitly expects this particular error by it's definition in "
            "`specs/integration_tests.md`, you can suppress the exception by "
            '@pytest.mark.allow_browser_errors("long_error_substring_or_regex")'
            "or set BROWSER_ERROR_ALLOWLIST_REGEXES for global patterns."
        )


@pytest.fixture(autouse=True)
def capture_backend_errors(request):
    """
    For backend integration tests, fail when new lines appear in dedicated
    service error logs (ERROR+), unless explicitly allowlisted.
    """
    if not _is_integration_test(request):
        yield
        return

    if request.node.get_closest_marker("integration_frontend"):
        yield
        return

    strict_mode = os.getenv("STRICT_BACKEND_ERRORS", "1") == "1"
    integration_runtime_mode = os.getenv("IS_INTEGRATION_TEST", "").lower() == "true"
    allow_all_backend_errors, marker_allowlist = _compile_marker_regex_allowlist(
        request, "allow_backend_errors"
    )
    allowlist = [*_compile_backend_error_allowlist(), *marker_allowlist]
    expected_session_ids_lower: set[str] = set()
    if integration_runtime_mode:
        expected_session_ids = _collect_expected_test_session_ids(request)
        expected_session_ids_lower = {sid.lower() for sid in expected_session_ids}
    expected_episode_ids_lower: set[str] = set()
    start_offsets: dict[str, int] = {}

    for service, path in BACKEND_ERROR_LOG_FILES.items():
        try:
            start_offsets[service] = path.stat().st_size
        except FileNotFoundError:
            start_offsets[service] = 0

    yield

    rep_call = getattr(request.node, "rep_call", None)
    test_call_failed = bool(rep_call and rep_call.failed)
    if not strict_mode or allow_all_backend_errors or test_call_failed:
        return

    issues: list[str] = []
    missing_attribution_id_issues: list[str] = []
    for service, path in BACKEND_ERROR_LOG_FILES.items():
        if not path.exists():
            continue
        start_offset = start_offsets.get(service, 0)
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            handle.seek(start_offset)
            for raw_line in handle:
                normalized = _strip_ansi(raw_line).strip()
                line_session_id = _extract_backend_error_session_id(normalized)
                line_episode_id = _extract_backend_error_episode_id(normalized)

                # Learn episode ids owned by this test from lines that contain both ids.
                if (
                    line_session_id
                    and line_episode_id
                    and line_session_id.lower() in expected_session_ids_lower
                ):
                    expected_episode_ids_lower.add(line_episode_id.lower())

                if integration_runtime_mode:
                    if (
                        normalized
                        and _backend_error_requires_attribution_id(normalized)
                        and not (
                            _backend_error_has_session_id(normalized)
                            or _backend_error_has_episode_id(normalized)
                        )
                    ):
                        missing_attribution_id_issues.append(f"{service}: {normalized}")
                matched = _match_backend_issue(raw_line, allowlist)
                if matched:
                    if integration_runtime_mode and (
                        expected_session_ids_lower or expected_episode_ids_lower
                    ):
                        owns_by_session = bool(
                            line_session_id
                            and line_session_id.lower() in expected_session_ids_lower
                        )
                        owns_by_episode = bool(
                            line_episode_id
                            and line_episode_id.lower() in expected_episode_ids_lower
                        )
                        if not (owns_by_session or owns_by_episode):
                            continue
                    elif integration_runtime_mode and (
                        line_session_id or line_episode_id
                    ):
                        # This test did not expose ownership ids to the fixture, so do
                        # not misattribute structured backend errors from another test's
                        # session that happened to finish during this test's runtime.
                        continue
                    issues.append(f"{service}: {matched}")

    if integration_runtime_mode and missing_attribution_id_issues:
        sample = "\n".join(f"- {line}" for line in missing_attribution_id_issues[:12])
        overflow = len(missing_attribution_id_issues) - 12
        suffix = f"\n- ... and {overflow} more" if overflow > 0 else ""
        pytest.fail(
            "Structured backend error logs must include session_id or episode_id for integration-mode traceability.\n"
            f"{sample}{suffix}\n"
            "Add session_id=<...> and/or episode_id=<...> to every structured ERROR log line in the emitting service."
        )

    if issues:
        sample = "\n".join(f"- {line}" for line in issues[:12])
        overflow = len(issues) - 12
        suffix = f"\n- ... and {overflow} more" if overflow > 0 else ""
        pytest.fail(
            "Unexpected backend errors/exceptions detected in dedicated service error logs.\n"
            f"{sample}{suffix}\n"
            "See logs/integration_tests/{controller,worker_light,worker_heavy,temporal_worker}_errors.log.\n"
            "If this test explicitly expects this particular error by it's definition in "
            "`specs/integration_tests.md`, you can suppress the exception by "
            '@pytest.mark.allow_backend_errors("long_error_substring_or_regex") '
            "or set BACKEND_ERROR_ALLOWLIST_REGEXES for global patterns."
        )


@pytest.fixture(autouse=True)
def log_test_marker(request):
    """
    Automatically sends a log marker to all services before and after each test.
    This helps in delimiting logs by test case.
    """
    # Only run for integration tests
    if not _is_integration_test(request):
        yield
        return

    test_id = request.node.nodeid
    marker_start = f"START TEST: {test_id}"

    # Use a sync client for the fixture to avoid complexity with event loops
    with httpx.Client(timeout=1.0) as client:
        for service_url in SERVICES:
            try:
                client.get(f"{service_url}/health", params={"marker": marker_start})
            except Exception:
                # Service might not be up or endpoint doesn't exist, ignore
                pass

    yield

    marker_finish = f"FINISH TEST: {test_id}"
    with httpx.Client(timeout=1.0) as client:
        for service_url in SERVICES:
            with contextlib.suppress(Exception):
                client.get(f"{service_url}/health", params={"marker": marker_finish})


def _wait_for_worker_heavy_idle(
    client: httpx.Client,
    *,
    timeout_s: float = 120.0,
    interval_s: float = 0.5,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            response = client.get(f"{WORKER_HEAVY_URL}/ready", timeout=2.0)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(interval_s)
    raise RuntimeError("worker-heavy did not become idle before teardown cleanup")


def _cleanup_worker_heavy_simulation_state(client: httpx.Client) -> None:
    response = client.post(
        f"{WORKER_HEAVY_URL}/internal/simulation/cleanup",
        timeout=10.0,
    )
    if response.status_code != 200:
        raise RuntimeError(
            "worker-heavy cleanup failed "
            f"(status={response.status_code}, body={response.text})"
        )


@pytest.fixture(autouse=True)
def cleanup_heavy_sim_after_each_integration_test(request):
    """
    Ensure worker-heavy simulation state is cleaned after each integration test.

    This enforces test-level quiescence for Genesis/MuJoCo state in the long-lived
    worker-heavy process.
    """
    if not _is_integration_test(request):
        yield
        return

    yield

    with httpx.Client(timeout=2.0) as client:
        rep_call = getattr(request.node, "rep_call", None)
        test_call_failed = bool(rep_call and rep_call.failed)
        try:
            _wait_for_worker_heavy_idle(client)
            _cleanup_worker_heavy_simulation_state(client)
        except Exception as exc:
            if not test_call_failed:
                pytest.fail(f"worker-heavy post-test simulation cleanup failed: {exc}")
