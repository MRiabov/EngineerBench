# Integration Test List

The integration rules live in [integration-test-rules.md](./integration-test-rules.md).

## Required integration test suite

Priorities:

- `P0`: Release-blocking integration tests. Failures here block merge to `main`. Reserve this tier for core user flows, service availability, data integrity, security, and other high-blast-radius contracts.
- `P1`: Important regression tests that should pass in nightly/pre-release runs. Use this tier for material workflows and high-risk behaviors that are not merge-blocking on every PR.
- `P2`: Extended coverage for slower, rarer, statistical, or developer-utility checks. Use this tier for valuable validation that does not need to gate a PR or a pre-release.
- Priority follows risk, not perceived importance. A test belongs in `P0` only when its failure is a clear release blocker; if the failure is localized, recoverable, or non-core, classify it as `P1` or `P2`.

Benchmark-backed entries in this catalog assume the split authored-source
contract: `benchmark_script.py` owns benchmark assembly geometry,
`solution_script.py` owns engineer code, and benchmark rows that claim visible
geometry are invalid until seed and node-entry validation can see
`benchmark_script.py`. Preview tests must compose benchmark assembly from
`build()` and source objective overlays through `utils.objectives_geometry()`.

Preview-helper migration mainly affects this preview-evidence slice of the
catalog: `INT-032`, `INT-033`, `INT-034`, `INT-039`, `INT-040`, and `INT-217`.

### P0: Architecture parity baseline

This section is the smallest must-pass set. Keep it narrowly scoped, deterministic, and directly release-blocking.

| ID | Test | Required assertions |
| -- | -- | -- |
| INT-001 | Compose boot + health contract | `controller`, `worker`, Temporal worker service `controller-temporal-worker`, `postgres`, `minio`, `temporal` become healthy/started; health endpoints return expected status payload. |
| INT-002 | Controller execution boundary | Agent-generated execution happens on worker only; controller never runs LLM-generated code. |
| INT-003 | Session filesystem isolation | Two concurrent sessions cannot read each other's files. |
| INT-004 | Heavy-worker single-flight admission | Multiple agents may run, but each heavy-worker instance accepts only one active heavy job; while that job is active, `/ready` reports not-ready, and concurrent requests to the same instance receive deterministic busy responses on the direct worker HTTP path (no in-worker buffering/scheduling). Multi-worker throughput/fan-out behavior is out of scope for this test. |
| INT-187 | Heavy-worker crash containment boundary | Force deterministic simulation child-process failure and assert fail-closed request failure while `worker-heavy` API health stays up and subsequent heavy requests can still be served (no whole-service crash from one simulation failure). |
| INT-005 | Engineer planner mandatory artifact gate | Engineer planner must block handoff unless planner artifacts are present/valid (`engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`) and traces contain explicit `TOOL_START` for `submit_engineering_plan` with `node_type=engineer_planner`. After `submit_engineering_plan`, episode must reach `PLANNED`; if it reaches `FAILED`, test fails. Missing `submit_engineering_plan` must fail closed (no success-like status transition). |
| INT-006 | `engineering_plan.md` structure validation | Exact required engineering plan headings enforced (`## 1. Solution Overview`, `## 2. Parts List`, `## 3. Assembly Strategy`, `## 4. Assumption Register`, `## 5. Detailed Calculations`, `## 6. Critical Constraints / Operating Envelope`, `## 7. Cost & Weight Budget`, `## 8. Risk Assessment`), plus the Detailed Calculations summary table and matching `CALC-*` subsections. |
| INT-007 | `todo.md` checkbox integrity | Required checkbox format is enforced; deleted mandatory checklist entries are rejected. |
| INT-008 | `benchmark_definition.yaml` logic validation | Build/goal/forbid constraints validated: bounds checks, no illegal intersections, valid benchmark-owned fixture metadata (`benchmark_parts` unique IDs/labels, required `material_id` or `cots_id` when metadata is declared), mandatory `moved_object.material_id` resolves to a known `manufacturing_config.yaml` material, and benchmark planner estimate fields required for cap derivation are schema-valid. |
| INT-009 | `assembly_definition.yaml` schema gate | Required fields and numeric types enforced per method; malformed/template-like files rejected. |
| INT-010 | Planner pricing script integration | `validate_costing_and_price` runs, computes totals, and blocks handoff when over caps. |
| INT-011 | Planner caps under benchmark caps | Planner-owned `max_unit_cost`/`max_weight` are \<= benchmark/customer limits. |
| INT-012 | COTS search read-only behavior | COTS search path can query catalog, cannot mutate DB/files beyond allowed journal logging. |
| INT-013 | COTS output contract | Output contains required candidate fields (`part_id`, manufacturer, specs, price, source, fit rationale) or explicit no-match rationale. |
| INT-014 | COTS propagation into planning artifacts | Selected COTS part IDs/prices propagate into plan and cost-estimation artifacts. |
| INT-015 | Engineer handover immutability checks | Engineer cannot modify benchmark environment geometry (hash/checksum immutability checks across handover). |
| INT-016 | Review decision YAML schema gate | Reviewer decision YAML supports only allowed decision values, valid reviewer stage, and stage-appropriate reason codes. |
| INT-017 | Plan refusal decision loop | Refusal requires proof; reviewer confirm/reject branches route correctly. |
| INT-018 | `validate_and_price` integration gate | `simulate` and coder `submit_for_review(Compound)` are hard-blocked unless the latest `validate_and_price` for the same revision succeeded and produced valid handover artifacts (`validation_results.json`, `simulation_result.json`). `submit_for_review(Compound)` must then produce a valid latest-revision stage-specific manifest (`.manifests/engineering_execution_handoff_manifest.json` for engineering execution review; `.manifests/benchmark_review_manifest.json` for benchmark review), use the stage-correct assembly artifact (`assembly_definition.yaml` for engineering/electronics, `benchmark_assembly_definition.yaml` for benchmark review), and reject missing reviewer-stage selection. No fallback or inferred success is allowed. |
| INT-019 | Cost/weight/build-zone hard failure | Validation/simulation/review-submission are blocked when price, weight, or build-zone constraints fail, or when required handover artifacts are missing/invalid for the latest revision. Fail closed with explicit reason codes. |
| INT-020 | Simulation success/failure taxonomy | Goal-hit, forbid-hit, out-of-bounds, timeout, and instability are correctly classified in response payloads/events; benchmark-payload out-of-bounds before the configured observation window is a failure, while late payload drift after the window is recorded as evidence rather than a benchmark-simulation failure. |
| INT-021 | Runtime randomization robustness check | One admitted heavy-worker job executes one backend run with batched parallel jittered scenes (`num_scenes`) and aggregates pass/fail statistics correctly. |
| INT-024 | Worker benchmark validation toolchain | Benchmark `validate` catches intersecting/invalid objective setups across randomization ranges, plus duplicate top-level labels and reserved `environment` / `zone_` namespace collisions before MJCF generation. |
| INT-025 | Events collection end-to-end | Worker emits `events.jsonl`, controller ingests/bulk-persists, event loss does not occur in normal path. |
| INT-026 | Mandatory event families emitted | Tool calls, simulation request/result, manufacturability checks, lint failures, plan submissions, and review decisions are emitted in real runs. |
| INT-027 | Seed/variant observability | Static variant ID + runtime seed tracked for every simulation run. |
| INT-028 | Strict API schema contract | OpenAPI is valid and runtime responses match schema for controller and Temporal-worker critical endpoints. |
| INT-029 | API key enforcement | Protected endpoints reject missing/invalid key and accept valid key. |
| INT-030 | Interrupt propagation | User interrupt on controller cancels active worker job(s) and leaves consistent episode state. |
| INT-053 | Temporal workflow lifecycle logging | Starting an episode persists workflow identity and lifecycle transitions (`queued/running/completed/failed`) with timestamps; data is queryable through system persistence and events. |
| INT-054 | Temporal outage/failure logging path | If Temporal is unavailable/fails, episode must not report false success; explicit failure state/reason/event must be persisted. |
| INT-055 | S3 artifact upload logging | Successful asset uploads persist storage metadata (bucket/key/etag-or-version where available) and link to episode/asset records. |
| INT-056 | S3 upload failure + retry logging | Forced object-store failure triggers retry/failure policy; final state and failure events are consistent and queryable. |
| INT-061 | Asset serving security + session isolation contract | `GET /assets/{path}` serves only session-scoped files, returns expected MIME types for supported formats, and rejects stale/broken Python source assets with `422 Unprocessable Entity` when syntax heuristic fails. |
| INT-062 | Split-worker OpenAPI artifact contract | Generated worker API schema is either (a) merged light+heavy `worker_openapi.json` or (b) separate `worker_light_openapi.json` + `worker_heavy_openapi.json`; benchmark/simulation endpoints must not disappear from generated artifacts. |
| INT-063 | Mounted path compatibility/read-only contract | `/utils`, `/skills`, `/reviews`, `/config` mounts are present and read-only across light/heavy worker surfaces; write attempts fail while workspace root remains writable. |
| INT-070 | Mounted path traversal protection | Path traversal attempts against mounted/read-only paths are rejected deterministically (`403`) and do not allow escaping mount boundaries. |
| INT-071 | Agent filesystem policy precedence + reviewer write scope | `agents_config.yaml` enforcement matches policy precedence (`deny` > `allow`, unmatched => deny, agent override over defaults), `.manifests/**` is denied to all agent roles (read/write), and reviewer write/edit is restricted to stage-specific review decision/comments YAML pairs only. |
| INT-072 | `plan_refusal.md` validation + reviewer routing | Plan refusal requires valid `plan_refusal.md` frontmatter, role-specific reason enums, non-empty evidence body, supports multi-reason lists, and reviewer `confirm_plan_refusal` / `reject_plan_refusal` routes deterministically. |
| INT-073 | Session/episode/lineage observability linkage | Persisted records/events expose joinable linkage `user_session_id -> episode_id -> (simulation_run_id, cots_query_id, review_id)` plus `seed_id`, `seed_dataset`, `seed_match_method`, `generation_kind`, `parent_seed_id`, `is_integration_test`, and `integration_test_id` without conflating session and episode identity. |
| INT-101 | Physics backend selection contract | Setting `physics.backend: "mujoco"` in config selects the MuJoCo backend; `"genesis"` selects Genesis. Default (`genesis`) is used when not specified. `simulation_backend_selected` event emitted. |
| INT-114 | Benchmark planner explicit submission gate | Benchmark planner must emit explicit `submit_benchmark_plan` (`TOOL_START`) with `node_type=benchmark_planner`; successful submission must materialize `.manifests/benchmark_plan_review_manifest.json`, canonicalize planner-authored benchmark estimate fields into runtime-derived caps (`max_unit_cost`, `max_weight_g`), require schema-valid `benchmark_assembly_definition.yaml`, unblock `Benchmark Plan Reviewer`, and only after benchmark plan-review approval may the episode reach `PLANNED` (and must not transition to `FAILED`). Missing submission fails closed. |

### P0 negative integration tests (`INT-NEG-###`)

| ID | Test | Required assertions |
| -- | -- | -- |

### P1: Full architecture workflow coverage

| ID | Test | Required assertions |
| -- | -- | -- |
| INT-031 | Benchmark planner -> plan reviewer -> CAD -> reviewer path | Full benchmark-generation flow validates artifacts, benchmark plan-review loop, accepted handoff object integrity, benchmark-planner `submit_benchmark_plan` trace presence before planner handoff, confirms `benchmark_script.py` is not available to `Benchmark Planner` before plan approval and is materialized later by `Benchmark Coder`, `Benchmark Plan Reviewer` start only after valid latest-revision `.manifests/benchmark_plan_review_manifest.json` exists, and post-coder reviewer start only after valid latest-revision coder handover artifact (`.manifests/benchmark_review_manifest.json`) exists. |
| INT-032 | Benchmark-to-engineer handoff package | Engineer receives expected bundle (`benchmark_definition.yaml`, benchmark-owned fixture metadata including `benchmark_parts`, environment geometry metadata, explicit preview evidence when generated, explicit moving-fixture motion contracts, runtime jitter metadata); downstream reviewer gate must require latest-revision handoff artifacts, not tool-trace presence alone, and engineering intake must include read-only `benchmark_script.py` plus writable `solution_script.py` when benchmark geometry is present. |
| INT-033 | Engineering full loop (planner/coder/reviewer) | Planner sets realistic budgets and emits `submit_engineering_plan`; when drafting mode is enabled, planner also produces valid drafting artifacts (`assembly_definition.yaml.drafting`, `solution_plan_evidence_script.py`, `solution_plan_technical_drawing_script.py`) and `render_technical_drawing()` render evidence; Engineering Plan Reviewer inspects the current revision's real render artifacts before approving the handoff; coder implements the approved revision in `solution_script.py` and calls python `submit_solution_for_review(Compound)` only after passing latest-revision validation/simulation gates and manifest generation; reviewer approves/rejects with typed decision and evidence. |
| INT-034 | Reviewer evidence completeness | Review decisions include expected evidence fields, valid reviewer-specific handover manifest (for example `.manifests/benchmark_plan_review_manifest.json`, `.manifests/benchmark_review_manifest.json`, `.manifests/engineering_plan_review_manifest.json`, `.manifests/engineering_execution_handoff_manifest.json`, or `.manifests/electronics_review_manifest.json`) tied to the latest revision and successful simulation result when that stage requires implementation evidence, reviewer-specific persisted review file path for that stage/round, and fail-closed visual-evidence enforcement when latest-revision render images exist (`inspect_media(...)`, `media_inspection`, `llm_media_attached`). |
| INT-035 | Materials config enforcement | Only materials defined in `manufacturing_config.yaml` are accepted by validation/simulation pipeline. |
| INT-036 | Supported workbench methods | CNC, injection molding, and 3D print validation/pricing each function in integrated runs. |
| INT-037 | Joint mapping to MJCF correctness | Build123d joint definitions map to expected MJCF constraints/actuators in integrated export/simulate flow. |
| INT-038 | Controller function family coverage | Constant/sinusoidal/square/trapezoidal (and position controllers where supported) execute via runtime config without schema/tool failures. |
| INT-039 | Render artifact generation policy | On-demand render/video behavior matches policy and artifacts are discoverable by reviewer/consumer paths; persisted simulation video/image artifacts visually retain benchmark objective boxes (goal green, forbid red, build gray) when the benchmark defines them. |
| INT-040 | Asset persistence linkage | Final scripts/renders/mjcf/video are stored in S3 and linked from DB records. |
| INT-057 | Backup-to-S3 logging flow | Backup endpoint writes expected snapshot/object(s) to S3 and persists backup status metadata (size, duration, key). |
| INT-058 | Cross-system correlation IDs | A single episode/trace can be correlated across controller logs/events, Temporal records, and S3 asset metadata. |
| INT-059 | Langfuse trace linkage in live runs | With valid `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`, live episode execution emits trace records linked by non-empty `langfuse_trace_id`; tool/LLM/event traces are correlated to the same run-level trace identity. |
| INT-060 | Langfuse feedback forwarding contract | `POST /episodes/{episode_id}/traces/{trace_id}/feedback` forwards score/comment to Langfuse and persists local feedback fields; missing Langfuse client returns `503`, missing `langfuse_trace_id` returns `400`. |
| INT-064 | COTS reproducibility metadata persistence | COTS queries/selection persist reproducibility metadata (`catalog_version`, `bd_warehouse_commit`, `generated_at`, `catalog_snapshot_id`) plus normalized query snapshot, ordered candidates, and final selected `part_id`s; all are exposed in downstream artifacts/events used for replayable evaluation, and handoff is invalid when selected parts exist without this metadata. |
| INT-131 | COTS inventory exactness under pair-swapped rows | Pair-swapped COTS rows fail inventory exactness and surface the mismatch through the live integration boundary. |
| INT-217 | Solution motor backend parity | A solution-authored moving part declared once in `assembly_definition.yaml` materializes as a validated controllable actuator on both MuJoCo and Genesis; unresolved or unsupported motor mappings fail closed before simulation can report success; `get_all_actuator_names()` and `get_actuator_state()` expose the same solution motor identity and force limits used by power gating and overload monitoring. |

### P1 negative integration tests (`INT-NEG-###`)

| ID | Test | Required assertions |
| -- | -- | -- |

### P2: Multi-episode and evaluation architecture tests

No P2 rows are retained after publication pruning.

### Negative integration tests (`INT-NEG-###`)

- `INT-NEG-###` is reserved for explicitly negative integration tests whose correct outcome is rejection, denial, or another fail-closed result.
- These tests still run against the real compose stack and HTTP boundaries, and they follow the same observable-boundary rules as positive integration tests.
- Keep negative coverage in this namespace so the positive `INT-xxx` lists stay focused on success-oriented architecture coverage.
- When a negative test uses `MockDSPyLM`, its scenario file must use the matching `INT-NEG-###.yaml` name and remain one-to-one with that test.

## Per-test Unit->Integration Implementation Map (mandatory)

This section exists to force implementation as true integration tests, not unit tests.
It assumes the authored-source split contract from the benchmark migration:
benchmark geometry is exposed via `benchmark_script.py`, engineer code lives in
`solution_script.py`, and those two files are the authored-source contract.

| ID | How to implement as integration | Reject as unit-test anti-pattern |
| -- | -- | -- |
| INT-001 | Bring up compose stack and hit `/health` endpoints over HTTP. | Importing FastAPI app/TestClient only. |
| INT-002 | Trigger real run via API; verify worker-side execution evidence and controller non-execution. | Patching remote FS client or executor calls. |
| INT-003 | Use two real session IDs via HTTP file APIs and assert isolation. | Calling router/helper methods directly in-process. |
| INT-004 | Send parallel simulate requests over HTTP to the same heavy-worker instance; assert one request is admitted, `/ready` reports not-ready while that job is active, and concurrent request(s) receive deterministic busy responses (`503` + `WORKER_BUSY`) on the direct worker HTTP path, with no in-worker queueing/buffering. Do not assert cross-worker load distribution or cluster fan-out in this test. Ensure build scripts use `PartMetadata` class. | Mocking in-worker busy-gate behavior (instead of exercising live HTTP admission) or asserting horizontal scaling behavior from a single-instance test. |
| INT-187 | Trigger a deterministic fatal simulation-child failure through live heavy execution; assert failed response, `worker-heavy /health` remains healthy, and a subsequent heavy request still succeeds without restarting the service. | Unit-testing exception handlers around simulation helpers without live subprocess/service/process-boundary verification. |
| INT-005 | Submit with missing engineer-planner artifacts through API and assert rejection, then run engineer planner flow over controller APIs and assert episode traces include `TOOL_START` with `name=submit_engineering_plan` and `node_type=engineer_planner`; after submission, assert episode reaches `PLANNED` and not `FAILED`. Assert missing submission trace cannot transition to success-like statuses. | Calling artifact validator function directly or asserting only final `PLANNED/COMPLETED` status without planner tool-call evidence. |
| INT-006 | Submit malformed `engineering_plan.md` through real flow and assert heading gate failure. | Unit-testing markdown parser in isolation only. |
| INT-007 | Edit `todo.md` through tool APIs and assert integrity rejection on bad structure. | Directly invoking TODO validator function. |
| INT-008 | Upload invalid `benchmark_definition.yaml` via API and assert logic/bounds failure. | Constructing model objects without API path. |
| INT-009 | Submit malformed `assembly_definition.yaml` in run flow and assert blocked handoff. | Pydantic-schema-only unit checks. |
| INT-010 | Execute planner submission over HTTP and verify pricing script gate behavior. | Mocking script call result. |
| INT-011 | Provide planner caps above benchmark caps via real artifacts and assert refusal. | Comparing dicts in unit-only test. |
| INT-012 | Run COTS query through runtime interface and assert read-only behavior. | Mocking DB/search client end-to-end. |
| INT-013 | Assert required COTS response fields from live API/subagent result. | Asserting a mocked tool return fixture. |
| INT-014 | Run planning flow and verify COTS IDs/prices persisted into produced artifacts. | Checking handcrafted artifact strings only. |
| INT-015 | Attempt environment mutation in engineering flow and assert immutability rejection. | Unit-testing hash helper only. |
| INT-016 | Submit invalid review decision YAML via API and assert strict decision rejection. | Parsing YAML schema in isolation only. |
| INT-017 | Exercise refusal + reviewer confirm/reject branch with real API transitions. | State-machine branch unit test with mocks only. |
| INT-018 | Call `simulate` and coder review-submission endpoints without latest successful `validate_and_price` artifacts and assert deterministic hard block; then provide valid artifacts and assert unblock only when `submit_for_review(Compound)` emits a valid latest-revision stage-specific manifest (`.manifests/engineering_execution_handoff_manifest.json` or `.manifests/benchmark_review_manifest.json`, as applicable). | Directly testing function precondition checks only. |
| INT-019 | Submit overweight/overbudget/out-of-zone or missing-artifact latest revision via API and assert fail-closed reason codes at validation/simulation/review-submission boundaries. | Testing only local numeric comparison helpers. |
| INT-020 | Execute scenarios over HTTP and assert taxonomy in response + events, and assert reviewer handoff remains blocked for invalid geometry, forbid-hit, early benchmark-payload out-of-bounds, timeout, and instability outcomes while late payload drift after the configured observation window is not itself a benchmark-simulation failure. Build scripts must include `PartMetadata` for all parts. | Mocking simulation result enums. |
| INT-021 | Run runtime-randomization verification via API and assert one admitted heavy job produces one backend run with batched jittered scenes plus aggregated robustness output. | Single mocked seed result assertion. |
| INT-024 | Run benchmark validation endpoint on conflicting geometry/objectives and assert failure. | Calling validation module directly in process. |
| INT-025 | Execute real episode; verify worker events ingestion/persistence end-to-end. | Reading only local mock event list. |
| INT-026 | Verify required event families emitted from a real run, not fabricated payloads. | Event model unit tests only. |
| INT-027 | Run simulation and assert persisted static variant/runtime seed fields. | Unit assertion against seeded fixture object. |
| INT-028 | Fetch live OpenAPI from running service and validate real responses. | Static schema file lint without live calls. |
| INT-029 | Use live endpoints with missing/invalid/valid API key headers. | Unit-test auth dependency in isolation only. |
| INT-030 | Start long run and interrupt through API; assert worker cancellation and final state. | Mocking interrupt handler methods. |
| INT-031 | Execute full benchmark planner->plan-reviewer->CAD->reviewer workflow over APIs; assert planner `submit_benchmark_plan` trace, benchmark plan-reviewer start blocked until valid latest-revision `.manifests/benchmark_plan_review_manifest.json` exists, benchmark coder materializes `benchmark_script.py` only after approval, and benchmark reviewer start blocked until valid latest-revision `.manifests/benchmark_review_manifest.json` exists. | Patching graph nodes in process. |
| INT-032 | Execute handoff and verify produced package artifacts from real storage paths, including latest-revision review manifest validity checks used by reviewer gate (no trace-only fallback, no model-side manifest reads), plus read-only `benchmark_script.py` and writable `solution_script.py` once the benchmark package is materialized. | Handcrafted dict payload assertions. |
| INT-033 | Run engineering planner/coder/reviewer loop end-to-end through services; assert planner `submit_engineering_plan`, planner-authored drafting artifacts (`assembly_definition.yaml.drafting`, `solution_plan_evidence_script.py`, `solution_plan_technical_drawing_script.py`), `render_technical_drawing()` render evidence, plan-reviewer inspection of the current revision's real render bundle before approval, coder submission semantics (`submit_engineering_plan` vs python `submit_solution_for_review(Compound)`), strict latest-revision preconditions, writable `solution_script.py`, and fail-closed behavior on stale artifacts. | Node-level unit tests with mocked agent outputs or render stubs. |
| INT-034 | Submit real reviews and assert evidence completeness plus persisted reviewer-specific manifest linkage (`.manifests/benchmark_plan_review_manifest.json`, `.manifests/benchmark_review_manifest.json`, `.manifests/engineering_plan_review_manifest.json`, `.manifests/engineering_execution_handoff_manifest.json`, or `.manifests/electronics_review_manifest.json`) for the accepted/rejected latest revision, reviewer-specific persisted review decision/comments YAML paths for the stage, fail-closed rejection when latest-revision renders exist but `inspect_media(...)` was not used, and `media_inspection`/`llm_media_attached` evidence for the satisfied path. | Unit-test of review schema only. |
| INT-035 | Use disallowed material in run and assert pipeline rejection from integrated config. | Local config parser unit test only. |
| INT-036 | Exercise CNC/injection/3DP through validation/pricing APIs with real artifacts. | Mocked workbench method returns. |
| INT-037 | Produce assembly and assert exported MJCF joint/actuator mapping from run outputs. | Unit-test mapper function only. |
| INT-038 | Execute controller function modes via runtime config in real simulation runs. | Direct function math unit tests only. |
| INT-039 | Trigger render/video via APIs and assert artifact policy behavior in storage. | Mocking renderer outputs. |
| INT-040 | Verify assets stored in S3 + DB links after real episode completion. | Fake storage client + call-count assertions. |
| INT-053 | Start real episode and assert workflow IDs/status transitions persisted from Temporal-integrated path. | Fake workflow objects in unit tests. |
| INT-054 | Disable Temporal service (or break connectivity) in compose and assert failure logging path. | Mocking Temporal client exceptions only. |
| INT-055 | Complete real upload and assert object metadata persisted with episode linkage. | Storage adapter unit test with fake client only. |
| INT-056 | Force real S3/MinIO upload failure and assert retry + terminal logging behavior. | Mocked upload error branch only. |
| INT-057 | Call backup endpoint against live stack and verify object creation + backup metadata logs. | Unit test of backup serializer only. |
| INT-058 | For one episode, correlate IDs across events, Temporal records, and S3 metadata from real persistence. | Asserting hardcoded correlation IDs in fixtures. |
| INT-059 | Run live episode with Langfuse configured and assert persisted trace linkage (`langfuse_trace_id`) across emitted traces. | Unit-testing callback wiring or mocking Langfuse handler calls only. |
| INT-060 | Call live feedback endpoint and assert both remote Langfuse scoring effect and local DB feedback persistence + error-path status codes. | Directly invoking feedback route function with mocked DB/Langfuse client only. |
| INT-061 | Request assets via live `GET /assets/{path}` with `X-Session-ID`; assert MIME behavior, cross-session denial, and `422` rejection for syntactically broken Python source. | Calling asset-serving helper directly or checking filesystem paths without HTTP boundary. |
| INT-062 | Generate/fetch worker OpenAPI artifact(s) in CI/integration environment and assert light+heavy endpoint coverage is present. | Linting a stale committed schema file without runtime generation. |
| INT-063 | Attempt writes to mounted paths and writes to workspace root via live file APIs; assert read-only mounts and writable workspace behavior across worker surfaces. | Asserting config constants for mount paths without exercising container mounts. |
| INT-064 | Execute COTS lookup and artifact handoff via APIs; assert persisted `catalog_version`, `bd_warehouse_commit`, `generated_at`, `catalog_snapshot_id`, normalized query snapshot, ordered candidates, and selected `part_id`s in events/records/artifacts. | Unit-testing metadata dataclass construction only. |
| INT-070 | Attempt mounted-path traversal via live file APIs (e.g., `/utils/../...`); assert deterministic `403` and no cross-boundary access. | Path-normalization unit checks without exercising worker HTTP/file boundary. |
| INT-071 | Execute per-agent file operations via live file APIs and assert `agents_config.yaml` precedence (`deny` > `allow`, unmatched deny, agent override), strict deny of `.manifests/**` to all agent roles, and reviewer-only stage-specific write scopes for the review decision/comments YAML pairs. | In-process path policy matcher and precedence helpers only. |
| INT-072 | Submit refusal artifacts through real planner/reviewer flow; assert invalid/missing `plan_refusal.md`, invalid role reasons, or empty evidence are rejected; assert `confirm_plan_refusal`/`reject_plan_refusal` transitions. | Frontmatter parser-only tests without exercising orchestration route/state transitions. |
| INT-073 | Execute real episode runs and assert persisted traces/events expose `user_session_id`, `episode_id`, `simulation_run_id`, `cots_query_id`, `review_id`, `seed_id`, `seed_dataset`, `seed_match_method`, `generation_kind`, `parent_seed_id`, `is_integration_test`, and `integration_test_id` with joinable linkage and no session/episode conflation. | Checking schema fields exist without runtime persistence assertions. |
| INT-101 | Set `physics.backend` in config and hit simulation endpoint; assert backend-selected event and correct engine used. | Importing backend factory and calling it directly. |
| INT-114 | Run benchmark-planner flow over controller APIs and assert traces include `TOOL_START submit_benchmark_plan` with `node_type=benchmark_planner`; assert `.manifests/benchmark_plan_review_manifest.json` is created and benchmark plan reviewer entry is unblocked only for the latest planner revision; after plan-review approval, episode must reach `PLANNED` and not `FAILED`; benchmark planner must not receive `benchmark_script.py` before approval, because that file is introduced later by `Benchmark Coder`; missing submission must not reach success-like status. | Mocking benchmark planner internals or asserting only terminal status without planner submission trace evidence. |
| INT-210 | Run a MuJoCo simulation that captures video frames, assert `VideoRenderer.save()` delegates encoding to `worker-renderer`, and verify the final MP4 is materialized in the session workspace. | Keeping MP4 encoding in-process or asserting only a synthetic video stub. |
| INT-211 | Run a Genesis-backed simulation that captures render frames and assert the same renderer-worker video path and storage contract are used for the final MP4. | Testing Genesis frame capture without verifying the render handoff or artifact persistence. |

## Recommended suite organization

- `tests/integration/smoke/`: INT-001..INT-004 (fast baseline).
- `tests/integration/architecture_p0/`: INT-005..INT-021, INT-024..INT-030, INT-053..INT-056, INT-061..INT-063, INT-070..INT-073, INT-101, INT-114, INT-187.
- `tests/integration/architecture_p1/`: INT-031..INT-040, INT-057..INT-060, INT-064, INT-131, INT-210, INT-211, INT-217.
- `tests/integration/architecture_p2/`: none retained after publication pruning.

## Notes

- This spec intentionally treats architecture statements as test requirements, including expected fail paths.
- Existing unit tests for observability/workbench/COTS are useful, but they do not replace integration-level verification across controller, Temporal worker, db, and storage boundaries.
- If an implementation PR adds or changes integration tests, it should include the mapped `INT-xxx` or `INT-NEG-###` ID in the canonical `@pytest.mark.int_id(...)` marker.
