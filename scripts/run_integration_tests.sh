#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Ensure integration test log directory exists
mkdir -p logs/integration_tests

should_disable_browser_fixtures() {
  local expect_marker_value=false
  local arg

  for arg in "$@"; do
    if [[ "$expect_marker_value" == true ]]; then
      case "$arg" in
        *integration_frontend*)
          return 1
          ;;
      esac
      expect_marker_value=false
      continue
    fi

    case "$arg" in
      -m)
        expect_marker_value=true
        ;;
      tests/integration/frontend*|*/tests/integration/frontend*|tests/e2e*|*/tests/e2e*)
        return 1
        ;;
    esac
  done

  return 0
}

pytest_passthrough_args=()
if should_disable_browser_fixtures "$@"; then
  pytest_passthrough_args=(-p no:tests.support.fixtures.browser)
fi

# Default to fail-fast integration triage when backend errors are already conclusive.
# Override per run with:
#   INTEGRATION_EARLY_STOP_ON_BACKEND_ERRORS=0 ./scripts/run_integration_tests.sh ...
export INTEGRATION_EARLY_STOP_ON_BACKEND_ERRORS="${INTEGRATION_EARLY_STOP_ON_BACKEND_ERRORS:-1}"
# Set INTEGRATION_RUNNER_VERBOSE=1 to restore detailed bootstrap/teardown progress.
# Default full-suite runs are split into deterministic marker buckets so p0/p1
# coverage lands before agent and p2 slices.
export INTEGRATION_ORDERED_MARKER_SPLITS="${INTEGRATION_ORDERED_MARKER_SPLITS:-1}"
# Teardown is serialized with the integration lock so concurrent runs cannot
# clobber each other. The env var is kept for compatibility with older docs.
export INTEGRATION_ASYNC_CLEANUP="${INTEGRATION_ASYNC_CLEANUP:-1}"

exec python3 scripts/internal/integration_runner.py run "${pytest_passthrough_args[@]}" "$@"
