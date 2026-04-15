---
title: Integration File-Backed Fixture Contract Migration
status: migration
agents_affected:
  - benchmark_planner
  - benchmark_plan_reviewer
  - benchmark_coder
  - benchmark_reviewer
  - engineer_planner
  - engineer_plan_reviewer
  - engineer_coder
  - engineer_execution_reviewer
added_at: '2026-04-15T00:00:00Z'
---

# Integration File-Backed Fixture Contract Migration

<!-- WON'T DO: this migration was superseded; do not continue the file-backed fixture expansion as a core initiative. -->

<!-- Major migration. File-bearing integration fixtures must stay external and path-scoped. -->

## Purpose

This migration makes file-bearing integration fixtures maintainable by requiring
external file assets as the canonical source of truth. The canonical ownership
key is `@pytest.mark.int_id(...)`: the active setup root is derived from that
marker, and the test function name must match the declared id in a canonical
`test_int_123_*` or `test_int_neg_001_*` form. The target contract is the same
fail-closed shape already used by eval seed workspaces (`seed_files`) and by
`tests/integration/mock_responses/`, but extended to every integration
authoring path that still lets file bodies drift into inline strings.

The mock-response corpus remains corpus-local. `scripts/validate_integration_mock_response_preflight.py`
continues to validate `tests/integration/mock_responses/`, while broader
integration test setups use the same file contract through a
function-scoped autouse validator on the active test setup.

This migration follows the architecture source of truth in
`specs/desired_architecture.md` and the integration rules in
`specs/integration-test-rules.md`. It also mirrors the eval-seed precedent in
`scripts/validate_eval_seed.py`, where file-backed seed content is a typed,
validated contract instead of an inline string convention.

A secondary AST guardrail applies to test source files only. It limits long
inline string literals so accidental file generation has a second fail-closed
tripwire. It does not inspect external payload files, shared templates, or
other file-backed fixture assets, because those are validated through the file
contract itself.

## Problem Statement

The runtime already knows how to expand `content_file` and `template_file`
references, but the authoring surface still lets tests embed file contents
directly in Python or YAML. That creates duplicated contracts, stale payloads,
and edit churn when a file changes in one place but not another.

The gap is not runtime expansion. The gap is authoring discipline and a
fail-closed file-validation contract for the active test setup.
`tests/conftest.py` currently enforces mock-response validity only at corpus
startup, and `allow_backend_errors` only covers backend log noise. There is no
dedicated marker-backed ownership contract for tests that are supposed to fail
because a file path is invalid, out of scope, or unexpectedly edited, and there
is no collection-time assertion that the declared `int_id` matches the test
function name.
There is also no fail-fast test-start gate for per-test file-backed integration
setups, so a broken setup can still consume test runtime before the bad
contract is surfaced.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `controller/agent/mock_scenarios.py` | Expands `content_file` and `template_file` into literal `content` at load time. | This proves file references work, but it does not prevent inline stringified file bodies elsewhere. |
| `tests/integration/agent/helpers.py` | Mirrors the same expansion logic for integration helpers, but some helper entrypoints still accept caller-supplied `int_id` values. | The test-side helper already supports the desired shape; the contract still needs to derive ownership from the active test marker instead of arbitrary ids. |
| `tests/integration/mock_responses/README.md` | Documents per-test setup files, adjacent payloads, shared templates, and corpus-local preflight. | The rule exists as guidance, not as a function-scoped contract. |
| `scripts/validate_integration_mock_response_preflight.py` | Validates `tests/integration/mock_responses/` and its referenced payloads, then runs node-entry preflight. | The validator is intentionally narrow and does not cover the wider integration suite. |
| `tests/conftest.py` | Enforces valid mock-response IDs and mock-response file backing at corpus startup, and uses `allow_backend_errors` for backend log suppression. | It does not validate the active test setup at test start or provide a dedicated file-validation failure contract. |
| `pyproject.toml` and `scripts/internal/integration_runner.py` | Register the `int_id` marker and extract ids from test names/docstrings for runner bookkeeping. | The marker is not yet the sole source of truth for ownership, and name/marker agreement is not enforced at collection. |
| `tests/integration/architecture_p0/test_shared_agent_templates.py` | Proves shared template expansion works. | It validates the mechanism, not the broader authoring rule. |
| Representative integration tests such as `tests/integration/architecture_p0/test_architecture_p0.py`, `tests/integration/architecture_p0/test_planner_gates.py`, `tests/integration/architecture_p1/test_infrastructure.py`, `tests/integration/architecture_p1/test_manufacturing.py`, and `tests/e2e/test_int_170_171.py` | Still embed `WriteFileRequest(content=...)` or literal file bodies inline. | These are the maintainability failures this migration removes. |
| `evals/logic/models.py` and `scripts/validate_eval_seed.py` | Show the existing seed-file contract and validator pattern in evals. | They are the precedent to mirror, not the contract to reuse directly. |

## Proposed Target State

01. Any integration fixture that represents a file uses an external file asset or
    shared template as its canonical source of truth.
02. Inline stringified file bodies are no longer the authoring form for
    maintainable integration file contracts.
03. The same shared file-contract core validates both the mock-response corpus
    and the active test's declared setup files.
04. `tests/integration/mock_responses/` remains corpus-local, but its preflight
    uses the same file-contract semantics as the per-test setup validator.
05. `@pytest.mark.int_id(...)` is the ownership source of truth for file-backed
    integration setups. The active test setup and helper code derive from that
    marker, not from caller-supplied ids or test names.
06. Intentional file-validation failures are expressed through
    `@pytest.mark.expect_file_validation_errors(...)` with explicit file paths
    and expected edited files.
07. `@pytest.mark.allow_backend_errors(...)` remains a backend-noise escape
    hatch only and does not represent the file contract.
08. File references stay within their allowed roots: scenario-local payloads stay
    adjacent to the scenario, and reusable payloads live under
    `shared/agent_templates/`.
09. The migration fails closed when a file reference is missing, escapes its
    allowed root, mixes inline and file-backed declarations, or diverges from an
    expected edit list, or when the declared `int_id` disagrees with the test
    function name.
10. The integration file contract is validated by a function-scoped autouse
    fixture for the active test setup, so invalid test fixtures fail before
    that test body runs.
11. Test source files also carry a secondary AST guardrail: multiline string
    literals longer than five physical lines are rejected unless they are
    explicitly allowlisted as non-file text. External fixture files are not part
    of this check.

## Required Work

### Contract Core

- Define a shared file-contract model for integration fixtures that records
  the current test setup root, allowed roots, referenced payload files, and
  expected edited files, plus the canonical `int_id` and function-name
  consistency check for the active test.
- Keep the contract typed and explicit. Do not infer the authoring rules from
  log output or runtime expansion alone.
- Mirror the eval-seed precedent conceptually, but keep the integration
  contract separate from eval seed runtime semantics.

### Validation Plumbing

- Route `controller/agent/mock_scenarios.py`, `tests/integration/agent/helpers.py`,
  and `tests/conftest.py` through one shared file-contract validator.
- Keep `scripts/validate_integration_mock_response_preflight.py` corpus-local,
  but have it call the shared validator core.
- Add a function-scoped autouse fixture that validates the active test setup
  before the test body runs and derives ownership from `request.node` plus the
  canonical `@pytest.mark.int_id(...)` marker.
- Add collection-time validation that the test function name matches the
  declared `int_id` in canonical `test_int_123_*` or `test_int_neg_001_*`
  form.
- Make test-facing helper APIs derive the active case from the fixture context
  instead of accepting arbitrary caller-supplied `int_id` values.
- Keep any offline bulk validator aligned with the same core, but do not make
  it the runtime gate.
- Add the AST guardrail as a source-only check over test files, not as a scan
  over external fixture assets.
- Preserve the current mock-response node-entry checks, but do not make that
  script responsible for negative-test inference.

### Authoring Rules and Fixtures

- Update `tests/integration/mock_responses/README.md` and related integration
  authoring guidance to require external payload files for file bodies.
- Normalize test-specific payloads into adjacent files and reusable starter
  payloads into `shared/agent_templates/`.
- Sweep representative integration test modules so the new contract is visible
  in the main suites, not just in the mock-response corpus.

### Failure Signaling and Tests

- Add `@pytest.mark.expect_file_validation_errors(...)` support and tests for
  missing files, out-of-root references, mixed inline/file declarations, and
  unexpected edited files.
- Add regression coverage for mismatched `@pytest.mark.int_id(...)` values and
  test function names.
- Add regression coverage proving test-facing helpers fail closed when a caller
  attempts to borrow another scenario's `int_id`.
- Keep `@pytest.mark.allow_backend_errors(...)` as backend log suppression only.
- Extend `tests/integration/architecture_p0/test_shared_agent_templates.py` or
  equivalent coverage so shared-template expansion stays locked.
- Add regression coverage that proves the validator fails closed before runtime
  when a file payload is stringified inline.

## Non-Goals

- Do not replace the integration suite with a node-entry-validated mock-response
  clone.
- Do not change `scripts/validate_eval_seed.py` or the eval seed contract.
- Do not alter the negative-path ID taxonomy or the negative-path migration
  doc.
- Do not remove `allow_backend_errors`.
- Do not make the mock-response preflight responsible for all integration
  tests.
- Do not require a suite-wide startup pass that validates every test setup
  before the first test body runs.
- Do not let helper APIs accept arbitrary caller-supplied `int_id` values as an
  ownership source.
- Do not let test function names override the declared `@pytest.mark.int_id(...)`
  marker as the ownership source of truth.
- Do not rely on brittle log parsing or runtime heuristics to detect inline file
  payloads.
- Do not apply the AST string-length guardrail to external fixture files or
  shared templates.

## Sequencing

1. Add the shared file-contract core and marker semantics.
2. Wire the mock-response preflight and the active test setup validator into the
   shared core.
3. Add collection-time marker/name agreement validation and make the active
   test setup derive ownership from `@pytest.mark.int_id(...)`.
4. Update authoring docs and representative tests to move file bodies out of
   source literals.
5. Sweep the remaining integration file payloads and lock the regression
   coverage.
6. Add the function-scoped autouse validation gate and the source-only AST
   backstop in the same contract family.

## Acceptance Criteria

01. No integration test or mock response uses inline stringified file bodies as
    the canonical payload form.
02. File references resolve only within their allowed roots.
03. `@pytest.mark.int_id(...)` is the sole ownership source of truth for
    file-backed integration setups, and the declared id matches the test
    function name.
04. Intentional file-validation failures have an explicit marker and path list.
05. `scripts/validate_integration_mock_response_preflight.py` stays corpus-local
    and still passes.
06. Backend-error suppression remains separate from file validation.
07. Shared template expansion remains covered by integration tests.
08. Invalid file-backed test setups fail at test start rather than midway
    through that test execution.
09. The AST guardrail applies only to test source, not to external fixture
    assets.
10. The suite does not need a global pre-execution pass over every test setup to
    catch file-contract failures.

## Migration Checklist

### Contract and Plumbing

- [ ] Define the shared file-contract core and the marker contract.
- [ ] Wire the core into mock-response preflight and the active test setup
  validator.

### Authoring and Fixtures

- [ ] Update integration authoring docs to require external file payloads.
- [ ] Convert representative inline file payload tests to external files.

### Regression Coverage

- [ ] Add regression coverage for missing files, escaped paths, mixed inline
  declarations, and unexpected edits.
- [ ] Verify that `allow_backend_errors` remains unrelated to file validation.
- [ ] Add regression coverage for the source-only AST string-length guardrail.

## File-Level Change Set

- `tests/conftest.py`
- `controller/agent/mock_scenarios.py`
- `tests/integration/agent/helpers.py`
- `scripts/internal/integration_runner.py`
- `pyproject.toml`
- `scripts/validate_integration_mock_response_preflight.py`
- `scripts/validate_integration_fixture_preflight.py` (new)
- `tests/integration/mock_responses/README.md`
- `tests/integration/architecture_p0/test_shared_agent_templates.py`
- Representative inline-file integration tests under
  `tests/integration/architecture_p0/`, `tests/integration/architecture_p1/`,
  and `tests/e2e/`
- Adjacent payload files and shared templates under
  `tests/integration/mock_responses/` and `shared/agent_templates/`
