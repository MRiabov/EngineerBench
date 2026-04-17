---
name: integration-tests-workflow
description: Run, debug, and implement integration tests at the public boundary of the feature under test. Use when updating system integration tests or deterministic fixture-driven integration coverage.
---

# Integration Tests Workflow

Use this workflow when adding, updating, or debugging integration tests in RunAudit.

The important distinction is the boundary under test:

- Core product flows should exercise the real app/worker/storage boundary.
- Deterministic fixture-driven tests should exercise the real fixture loader/serializer path and any replay-only compatibility layer at the public boundary.

## Non-negotiable rules

01. Test the public boundary of the feature under test.
02. Do not import internal modules to execute business logic directly.
03. Do not patch or mock project modules; only isolate unavoidable third-party instability.
04. Assert against observable outputs: HTTP responses, persisted artifacts, manifests, ledgers, DB rows, object storage, logs, and emitted events.
05. When a test needs deterministic model output or file content, author the fixture as a typed schema instance and serialize it at the edge.
06. Maintain stable test ids:
    - `INT-xxx` for core product integration tests
    - `INT-NEG-###` for explicitly negative integration tests
07. Include at least one expected-fail assertion wherever the architecture specifies fail-closed behavior.
08. Parse JSON, YAML, or similar artifacts into typed models before making assertions.
09. Use state-based polling for readiness and completion rather than hardcoded sleeps.
10. Before trusting logs or artifacts, confirm they belong to the current run.

## Suite shape

- Core product integration tests cover backend, worker, storage, and observability boundaries.
- Deterministic fixtures are allowed only for model outputs or other externally variable content, and they should come from typed schema builders plus shared serializers.
- Any legacy replay corpus under `tests/integration/mock_responses/` is compatibility material only; do not treat it as the source of fixture meaning.
- Fixtures must not bypass fail-closed gates or fabricate benchmark truth.

## Fixture guidance

- Use typed schema objects first, then serialize them through the shared YAML helpers at the edge.
- Keep replay fixtures minimal and stable when a test depends on deterministic model behavior.
- Do not use fixtures to bypass manifest freezes, adapter mapping, or scoring.
- Keep negative cases real enough to reach the intended evaluated stage.

## Common anti-patterns

- Unit-style tests that import internals and skip the real boundary
- Broad mocks that hide boundary failures
- Asserting only on terminal status without artifact evidence
- Treating confidence as a score signal
- Hardcoded sleeps or stale log/artifact assertions

## Validation checklist

Before finishing an integration test change, verify all of the following:

1. The test exercises the public boundary of the feature under test.
2. The test asserts on persisted artifacts, logs, or structured outputs.
3. The test preserves or improves mapped coverage.
4. The test includes a fail-path assertion when applicable.
5. The test id matches the active catalog (`INT-xxx` or `INT-NEG-###`).
6. Any deterministic fixture file is scoped to the specific model-output behavior it controls.
