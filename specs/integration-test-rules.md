# Integration Test Rules

The canonical catalog of `INT-xxx` and `INT-NEG-###` IDs lives in [integration-test-list.md](./integration-test-list.md).

## **CRITICAL NOTE TO IMPLEMENTATION AGENTS**

These workflows are integration workflows. Do **not** satisfy them with unit tests disguised as integration tests.
Do not mock project/runtime boundaries in integration tests; only unavoidable third-party instability may be isolated, and each such case must be justified in the test docstring.

**CONTROL THE TEST EXECUTION *ONLY* BY HTTP REQUESTS IN EVERY TEST. DO NOT DO TESTS THAT ARE EFFECTIVELY UNIT TESTS**
**FILE CREATION SHOULD BE MADE VIA TOOL CALLS. EXECUTION LOGIC SHOULD BE MADE VIA TOOL CALLS. EVERYTHING SHOULD BE MADE VIA HTTP REQUESTS, NOT VIA MOCKS AND UNIT TESTS!**

**ASSERT AGAINST *CONTAINERS* NOT AGAINST PYTHON**

*If you cannot assert something via HTTP calls, assert it via the `events.jsonl` event stream.*

Additionally:

1. `specs/desired_architecture.md` is the central source of truth for the application; all integration tests should be relevant to it and reviewed against it before implementation. Every added test must map to an `INT-xxx` or `INT-NEG-###` ID in the integration-test list.
2. Prefer black-box integration (compose services + real boundaries); avoid heavy mocks except where unavoidable.
3. Include both happy-path and required fail-path assertions (especially gating/validation/refusal/event emission).
4. Do not silently drop existing integration coverage; replacements must preserve or improve mapped coverage.
5. Mark unimplemented IDs explicitly as deferred (P1/P2) instead of omitting them.
6. `INT-NEG-###` is reserved for explicitly negative integration tests. The reserved negative tables in the integration-test list will be populated later starting at `INT-NEG-001`; do not migrate rows yet. As a working convention, expected-failure cases should mostly live there while `INT-xxx` stays happy-path oriented.

## Non-negotiable Integration Execution Contract (applies to every `INT-xxx` and `INT-NEG-###`)

01. Test target is a running compose stack (`controller`, `worker`, `worker-renderer`, infra services), not imported Python functions.
02. Test traffic goes through HTTP APIs only.
03. Files/artifacts are created by API/tool-call pathways, not by direct local writes to app internals.
04. No `patch`, `monkeypatch`, or fake clients for controller/worker/s3 paths in integration tests.
05. Assertions are on observable boundaries: HTTP responses, container logs, DB rows, object storage objects, emitted events.
06. Every test must include at least one expected-fail assertion where architecture specifies fail behavior.
07. Any unavoidable mock must be isolated to external third-party instability only, and must not mock project modules.
08. A test that imports app internals (`controller.*`, `worker.*`) to invoke business logic directly is **not** integration coverage.
09. Every `build123d` script used in tests must ensure every part has a `.metadata` attribute initialized with a `PartMetadata` or `CompoundMetadata` instance (imported from `shared.models.schemas`), following strict typing rules.
10. Every JSON, YAML, XML is converted to models e.g. Pydantic models and only then assertions are happening against them (for test maintainability and explainability). If there is no model for a JSON or similar schema, add it. Fixture authoring follows the same rule: build the typed schema object first and serialize it at the edge; do not treat handwritten YAML blobs as the authoritative source of fixture meaning.
11. Tests must utilize state-based polling (e.g., waiting for specific API responses, DB states, or UI elements) rather than hardcoded sleeps or generic timeouts. This ensures tests are deterministic and fail-fast.
12. Each `INT-xxx` or `INT-NEG-###` ID must map to **exactly one** test function. The canonical ID must be declared once for that function via a dedicated `@pytest.mark.int_id(...)` marker, and the runtime `session_id` must be derived from that declared ID. Creating multiple test functions or multiple canonical declarations for the same ID is forbidden. If a single ID requires multiple sub-assertions, they must be consolidated into one test.
13. Integration tests must be parallelizable under `pytest -n4` without custom per-test parallelization logic. The integration runner is expected to keep xdist enabled for every integration invocation, including `integration_p1`, `integration_frontend`, `tests/e2e`, and the full default suite; marker/file selection must not silently turn xdist off. If a test cannot run in that mode, it is unacceptable unless it is explicitly isolated with `pytest.mark.xdist_group(...)` or is demonstrably CPU-bound or RAM-bound in a way that still would not be a constraint on materially larger machines; MuJoCo-heavy tests are not a blanket exception, because the current suite does not approach OOM and resource pressure is not a valid default waiver.

*Exception to the importing rules*: you can import python models and enums to use appropriate schema to avoid using pure json which will need to be manually updated later.
Commonly, these models and enums would be in `shared/` folder.

## Infrastructure & Helpers

The integration suite is designed for high-velocity local execution and CI parity.

- **`IS_INTEGRATION_TEST=true`**: This environment variable is automatically exported by the runner. It enables "smoke test mode" in simulation kernels, significantly reducing particle counts and simulation time for faster feedback.
- **`INTEGRATION_EARLY_STOP_ON_BACKEND_ERRORS`**: Defaults to `1` in `scripts/run_integration_tests.sh`. When enabled, the runner monitors machine-readable backend error JSON (`logs/integration_tests/current/json/*_errors.json`, with compatibility symlinks at `logs/integration_tests/json/*_errors.json`) for the first **non-allowlisted** error event and reports it; pytest then fails the active test through the backend-error fixture (no runner SIGINT injection). Matching uses global `BACKEND_ERROR_ALLOWLIST_REGEXES` and per-test `@pytest.mark.allow_backend_errors` patterns keyed by `session_id` prefixes (`INT-xxx` and `INT-NEG-###`). Set to `0` to disable this detector and keep full-duration runs.
- **`tests/integration/mock_responses/`**: Integration mode uses `MockDSPyLM` for agent-node LLM responses, and scenarios are loaded from this directory as a compatibility/replay corpus. Each scenario file must use strict test-ID naming (`INT-###.yaml` or `INT-NEG-###.yaml`; for example `INT-074.yaml` or `INT-NEG-001.yaml`), and any other naming convention is rejected by a one-time integration startup assertion. Each `INT-xxx` or `INT-NEG-###` test owns exactly one scenario file in this directory, and that scenario is permanently tied to that test: it may only consume the mock responses defined for that same test ID, and it may not call, reference, or reuse another test's scenario (for example, `INT-031` cannot call `INT-089`, and `INT-NEG-001` cannot call `INT-074`). New fixture semantics should be authored in typed schema instances and serialized to YAML at the edge; large `write_file` payloads may still be extracted into adjacent fixture files via `content_file` references, or referenced by `tool_args.template_file` when the same payload should be shared from `shared/agent_templates/`. Template file paths resolve relative to `shared/agent_templates/`. When `INT-xxx` or `INT-NEG-###` behavior depends on deterministic mock outputs, keep the corresponding scenario entries current.
- **`scripts/run_integration_tests.sh`**: The central entry point for the integration suite. It manages infrastructure spin-up (Docker), local service lifecycle, and `pytest` execution.
- **Integration-run lock / queue**: The runner acquires an exclusive host-level lock at `/tmp/problemologist-integration.lock` before it tears down or starts services. If the lock is already held, the runner fails closed with a message that includes the active `INT-xxx` or `INT-NEG-###` ids when known; passing `--queue` waits for the lock instead of exiting. The companion run-state file at `/tmp/problemologist-integration.run.json` records the requested test selection so callers can decide whether to reuse `logs/integration_tests/current/` rather than start a duplicate run.
- **Profile-scoped local bootstrap**: `scripts/env_up.sh` and `scripts/env_down.sh` are profile-aware. The integration suite remains on the `integration` profile and its existing host ports, while eval runs use the separate `eval` profile and disjoint compose project / PID state so the two stacks can coexist on one machine without tearing each other down.
- **`logs/integration_tests/runs/run_<timestamp>/`**: canonical per-run log root. `logs/integration_tests/current/` points to the active/latest run, and compatibility symlinks remain at `logs/integration_tests/*.log`.
- **`logs/integration_tests/current/json/`**: machine-readable backend error files emitted as JSON Lines from native structlog event dicts (also reachable via compatibility symlinks in `logs/integration_tests/json/`):
  - `controller_errors.json`
  - `worker_light_errors.json`
  - `worker_heavy_errors.json`
  - `backend_error_allowlisted_prefixes.json` (auto-generated/cache file containing per-`INT-xxx` and `INT-NEG-###` backend-error allowlist rules derived from test markers; consumed by integration-runner early-stop filtering)
- **Backend error-log attribution contract**: Structured `ERROR` lines written to dedicated backend error logs must include `session_id` or `episode_id` (ideally both) so strict integration teardown can attribute failures to the owning test context and avoid cross-session leakage.
- **`test_output/`**: Stores JUnit XML results and the persisted test history used for trend analysis.
- **Worker FS read/write permissions bypass mechanism (`agents_config.yaml` enforcement tests)**: privileged bypass of per-agent filesystem policy is enabled only when both are present in the same HTTP request: request payload flag `bypass_agent_permissions=true` and header `X-System-FS-Bypass: 1`. Header-only and payload-only requests must remain policy-enforced (no bypass).

<!--Note: the bypass logic is to bypass permissions that restrict agents, but agents shouldn't be able to (obviously) use the bypass.-->

### Command Reference

```bash
# Run P0 architecture baseline
./scripts/run_integration_tests.sh -m integration_p0

# Run with high-fidelity simulation (disable smoke mode)
./scripts/run_integration_tests.sh --no-smoke

# Force MuJoCo/fast simulation explicitly
./scripts/run_integration_tests.sh --fast-sim

# Flip to Genesis/full-fidelity simulation
./scripts/run_integration_tests.sh --full-sim

# Run specific test file
./scripts/run_integration_tests.sh tests/integration/test_full_workflow.py
```

The integration and eval entrypoints default to MuJoCo. Passing `--fast-sim`
keeps the fast rigid-body backend explicit, while `--full-sim` flips the
simulation backend to Genesis/full-fidelity behavior. `--no-full-sim` remains a
legacy alias for `--fast-sim`.

### Simulation Backend Matrix Execution Contract

The simulation-facing integration suite must run as a two-backend matrix aligned with `specs/architecture/distributed-execution.md` and `specs/architecture/simulation-and-rendering.md`.

- Discovery scope: include tests that call `/benchmark/simulate` or `/benchmark/verify` (directly or via helper wrappers).
- Run order: execute MuJoCo first, then Genesis, to surface compatibility regressions before Genesis-only feature checks.
- Backend selection: use `SIMULATION_DEFAULT_BACKEND` in the integration runner environment and resolve backend in tests through `tests/integration/backend_utils.py:selected_backend()`.
- Portable tests: when a test is expected to pass on both backends, the test payload must set backend from `selected_backend()` instead of hardcoding `"GENESIS"`/`"MUJOCO"`.
- Backend-specific tests: when a test asserts behavior that is intentionally unavailable on one backend, gate it explicitly for that backend.
- MuJoCo exclusion rule: softbody and dynamic-wire behavior tests (for example INT-126 wire-tear dynamics) are not required on MuJoCo and must be skipped there.

Recommended execution pattern:

```bash
# MuJoCo pass
SIMULATION_DEFAULT_BACKEND=MUJOCO ./scripts/run_integration_tests.sh <simulation-test-nodes>

# Genesis pass
SIMULATION_DEFAULT_BACKEND=GENESIS ./scripts/run_integration_tests.sh <simulation-test-nodes>
```

### Backend Skip Policy (`skipif` vs `skip`)

Use explicit backend gating in test definitions.

- Preferred: `@pytest.mark.skipif(...)` for backend exclusions that are known at collection/import time.
- Allowed: `pytest.skip(...)` inside test bodies only when the skip condition depends on runtime-only state (for example downstream service health or artifact/runtime capability discovered after setup).
- Every backend skip must include a concrete reason mentioning the unsupported contract.

Recommended pattern:

```python
import pytest
from shared.simulation.schemas import SimulatorBackendType
from tests.integration.backend_utils import selected_backend

@pytest.mark.skipif(
    selected_backend() != SimulatorBackendType.GENESIS,
    reason="INT-126 requires backend-supported dynamic wire/softbody behavior",
)
async def test_int_126_wire_tear_behavior():
    ...
```

This keeps backend intent explicit in pytest collection output and reduces ambiguity during matrix triage.

### Validation Preview Backend Contract

`/benchmark/validate` is not the simulation-backend parity path.

The architecture contract is:

1. `/benchmark/validate` performs geometric validation plus static preview generation.
2. The static preview generation path uses build123d/VTK by default, even when `physics.backend=GENESIS`.
3. `/benchmark/validate` does not perform an extra Genesis load/render/build gate solely for backend parity.
4. Genesis parity remains covered by the simulation-facing backend matrix and by Genesis simulation tests where Genesis behavior is required.

Validation-preview tests should therefore assert:

1. the preview artifact contract still holds,
2. the preview backend routing is correct,
3. the selected simulation backend is not silently mutated for `/benchmark/simulate`.
4. build123d/VTK-backed preview images persist as RGB/depth/segmentation sibling files in `renders/`.
5. `config/agents_config.yaml render.<modality>.enabled` disables only the requested preview artifact types, while `render.<modality>.axes` and `render.<modality>.edges` independently control overlays for each modality.
6. `renders/<bundle>/render_manifest.json` persists per-image metadata, including segmentation legend entries with semantic labels and unique instance identifiers. `renders/render_manifest.json` may remain as a current-bundle compatibility alias, but historical assertions should prefer the bundle-local manifest or the bundle history contract when available.
7. RGB preview output reflects configured material colors for differing `material_id` values.
8. When `benchmark_definition.yaml` contains `goal_zone`, `forbid_zones`, and `build_zone`, the RGB preview output includes visible green, red, and gray objective boxes rather than dropping those visuals.
9. When axes/edge overlays are enabled on depth and segmentation previews, the generated images include the same world-coordinate axes treatment and use non-black edge accents so the overlays remain visible against their backgrounds.

### Heavy-request routing contract

Controller-initiated heavy operations are expected to travel through the live controller/worker HTTP flow. Integration tests that verify product behavior from controller or agent tool paths should assert persisted events, artifact results, and returned results from the worker-mediated path.

Direct `worker-heavy` HTTP requests remain valid only in integration tests that exercise worker-level boundaries such as single-flight admission, crash containment, and preview artifact generation. They are not the product-path routing model for controller tool calls.

<!--FIXME: so are worker-render-->
