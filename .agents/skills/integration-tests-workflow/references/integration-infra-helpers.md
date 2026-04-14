# Integration Infra & Helper Reference

This reference documents integration-run helpers and implicit dependencies that commonly affect `INT-xxx` behavior.

## Core integration mode toggles

- `IS_INTEGRATION_TEST=true`
  - Exported by `scripts/run_integration_tests.sh`.
  - Enables integration behavior switches across services (for example, mock LLM usage and tracing changes).
- `SMOKE_TEST_MODE`
  - In heavy worker config, defaults to `true` during integration unless explicitly set.
  - Runner flag `--no-smoke` sets `SMOKE_TEST_MODE=false` for high-fidelity runs.

## Deterministic mock LLM scenarios

- `tests/integration/mock_responses.yaml`
  - Loaded by `controller/agent/mock_llm.py` (`MockDSPyLM`) for integration-mode agent responses.
  - Keep scenario entries aligned with tests that rely on deterministic mock outcomes.

## Runner preflight and data prerequisites

- `scripts/ensure_docker_vfs.sh`
  - Compatibility helper for environments where Docker storage drivers are problematic.
- `parts.db`
  - Auto-populated by `shared.cots.indexer` when missing/empty.
  - Used by COTS integration flows.

## Session, logs, and persisted results

- `WORKER_SESSIONS_DIR`
  - Created as a temporary shared sessions root at run start.
  - Cleaned up during runner teardown.
- `logs/integration_tests/`
  - Canonical current-run service logs.
  - Prior runs archived under `logs/archives/run_*`.
- `test_output/junit.xml`
  - JUnit report written by the runner.
- `test_output/integration_test_history.json`
- `test_output/integration_test_archive.json`
  - Maintained by `scripts/persist_test_results.py`.

## Frontend integration helpers

- Frontend build cache marker:
  - `.git/problemologist_integration_frontend_build_commit`
  - Used to skip unnecessary rebuilds.
- Generated integration frontend env:
  - `frontend/.env.production` with `VITE_API_URL` and `VITE_IS_INTEGRATION_TEST=true`.
- Frontend API generation/build steps:
  - `scripts/generate_openapi.py`
  - `frontend npm run gen:api`
  - `frontend npm run build`

## Events stream behavior used by integration assertions

- `events.jsonl`
  - Default event sink from `shared/observability/events.py` (`EVENTS_FILE` override supported).
  - During simulation validation, heavy worker points `EVENTS_FILE` at session-local `events.jsonl`.
  - Events are collected and deleted by worker persistence helpers to avoid cross-run contamination.

## Integration-only observability behavior

- Langfuse tracing/client are disabled when `IS_INTEGRATION_TEST=true`.
  - This is expected behavior; avoid treating missing Langfuse traces as integration failures.
