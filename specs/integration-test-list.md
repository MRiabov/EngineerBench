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

### P0: High-risk and high-importance tests; release gates

This section is the smallest must-pass set. Keep it narrowly scoped, deterministic, and directly release-blocking.

| ID | Test | Required assertions |
| -- | -- | -- |
| INT-001 | Compose boot + health contract | `controller`, `worker-light`, `worker-heavy`, `worker-renderer`, `postgres`, and `minio` become healthy/started; health endpoints return expected status payload. |
| INT-002 | Controller execution boundary | Agent-generated execution happens on worker only; controller never runs LLM-generated code. |
| INT-003 | Session filesystem isolation | Two concurrent sessions cannot read each other's files. |
| INT-004 | Heavy-worker single-flight admission | Multiple agents may run, but each heavy-worker instance accepts only one active heavy job; while that job is active, `/ready` reports not-ready, and concurrent requests to the same instance receive deterministic busy responses on the direct worker HTTP path (no in-worker buffering/scheduling). Multi-worker throughput/fan-out behavior is out of scope for this test. |
| INT-187 | Heavy-worker crash containment boundary | Force deterministic simulation child-process failure and assert fail-closed request failure while `worker-heavy` API health stays up and subsequent heavy requests can still be served (no whole-service crash from one simulation failure). |
| INT-005 | Engineer planner mandatory artifact gate | Engineer planner must block handoff unless planner artifacts are present/valid (`engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`) and traces contain explicit `TOOL_START` for `submit_engineering_plan` with `node_type=engineer_planner`. After `submit_engineering_plan`, episode must reach `PLANNED`; if it reaches `FAILED`, test fails. Missing `submit_engineering_plan` must fail closed (no success-like status transition). |
| INT-006 | `engineering_plan.md` structure validation | Exact required engineering plan headings enforced (`## 1. Solution Overview`, `## 2. Parts List`, `## 3. Assembly Strategy`, `## 4. Assumption Register`, `## 5. Detailed Calculations`, `## 6. Critical Constraints / Operating Envelope`, `## 7. Cost & Weight Budget`, `## 8. Risk Assessment`), plus the Detailed Calculations summary table and matching `CALC-*` subsections. |
| INT-007 | `todo.md` checkbox integrity | Required checkbox format is enforced; deleted mandatory checklist entries are rejected. |
| INT-008 | `benchmark_definition.yaml` logic validation | Build/goal/forbid constraints validated: bounds checks, no illegal intersections, valid benchmark-owned fixture metadata (`benchmark_parts` unique IDs/labels, required `material_id` when metadata is declared), mandatory `moved_object.material_id` resolves to a known `manufacturing_config.yaml` material, and benchmark planner estimate fields required for cap derivation are schema-valid. |
| INT-009 | `assembly_definition.yaml` schema gate | Required fields and numeric types enforced per method; malformed/template-like files rejected. |
| INT-010 | Planner pricing script integration | `validate_costing_and_price` runs, computes totals, and blocks handoff when over caps. |
| INT-011 | Planner caps under benchmark caps | Planner-owned `max_unit_cost`/`max_weight` are \<= benchmark/customer limits. |
| INT-015 | Engineer handover immutability checks | Engineer cannot modify benchmark environment geometry (hash/checksum immutability checks across handover). |
| INT-016 | Review decision YAML schema gate | Reviewer decision YAML supports only allowed decision values, valid reviewer stage, and stage-appropriate reason codes. |
| INT-017 | Plan refusal decision loop | Refusal requires proof; reviewer confirm/reject branches route correctly. |
| INT-018 | `validate_and_price` integration gate | `simulate` and coder `submit_for_review(Compound)` are hard-blocked unless the latest `validate_and_price` for the same revision succeeded and produced valid handover artifacts (`validation_results.json`, `simulation_result.json`). `submit_for_review(Compound)` must then produce a valid latest-revision stage-specific manifest (`.manifests/engineering_execution_handoff_manifest.json` for engineering execution review; `.manifests/benchmark_review_manifest.json` for benchmark review), use the stage-correct assembly artifact (`assembly_definition.yaml` for engineering execution review, `benchmark_assembly_definition.yaml` for benchmark review), and reject missing reviewer-stage selection. No fallback or inferred success is allowed. |
| INT-019 | Cost/weight/build-zone hard failure | Validation/simulation/review-submission are blocked when price, weight, or build-zone constraints fail, or when required handover artifacts are missing/invalid for the latest revision. Fail closed with explicit reason codes. |
| INT-020 | Simulation success/failure taxonomy | Goal-hit, forbid-hit, out-of-bounds, timeout, and instability are correctly classified in response payloads/events; benchmark-payload out-of-bounds before the configured observation window is a failure, while late payload drift after the window is recorded as evidence rather than a benchmark-simulation failure. |
| INT-021 | Runtime randomization robustness check | One admitted heavy-worker job executes one backend run with batched parallel jittered scenes (`num_scenes`) and aggregates pass/fail statistics correctly. |
| INT-024 | Worker benchmark validation toolchain | Benchmark `validate` catches intersecting/invalid objective setups across randomization ranges, plus duplicate top-level labels and reserved `environment` / `zone_` namespace collisions before MJCF generation. |
| INT-025 | Events collection end-to-end | Worker emits `events.jsonl`, controller ingests/bulk-persists, event loss does not occur in normal path. |
| INT-026 | Mandatory event families emitted | Tool calls, simulation request/result, manufacturability checks, lint failures, plan submissions, and review decisions are emitted in real runs. |
| INT-027 | Seed/variant observability | Static variant ID + runtime seed tracked for every simulation run. |
| INT-029 | API key enforcement | Protected endpoints reject missing/invalid key and accept valid key. |
| INT-030 | Interrupt propagation | User interrupt on controller cancels active worker job(s) and leaves consistent episode state. |
| INT-053 | Episode lifecycle logging | Starting an episode through the live controller/worker path persists lifecycle transitions (`queued/running/completed/failed`) with timestamps; data is queryable through system persistence and events. |
| INT-055 | S3 artifact upload logging | Successful asset uploads persist storage metadata (bucket/key/etag-or-version where available) and link to episode/asset records. |
| INT-061 | Asset serving security + session isolation contract | `GET /assets/{path}` serves only session-scoped files, returns expected MIME types for supported formats, and rejects stale/broken Python source assets with `422 Unprocessable Entity` when syntax heuristic fails. |
| INT-063 | Mounted path compatibility/read-only contract | `/utils`, `/skills`, `/reviews`, `/config` mounts are present and read-only across light/heavy worker surfaces; write attempts fail while workspace root remains writable. |
| INT-070 | Mounted path traversal protection | Path traversal attempts against mounted/read-only paths are rejected deterministically (`403`) and do not allow escaping mount boundaries. |
| INT-071 | Agent filesystem policy precedence + reviewer write scope | `agents_config.yaml` enforcement matches policy precedence (`deny` > `allow`, unmatched => deny, agent override over defaults), `.manifests/**` is denied to all agent roles (read/write), and reviewer write/edit is restricted to stage-specific review decision/comments YAML pairs only. |
| INT-072 | `plan_refusal.md` validation + reviewer routing | Plan refusal requires valid `plan_refusal.md` frontmatter, role-specific reason enums, non-empty evidence body, supports multi-reason lists, and reviewer `confirm_plan_refusal` / `reject_plan_refusal` routes deterministically. |
| INT-073 | Session/episode/lineage observability linkage | Persisted records/events expose joinable linkage `user_session_id -> episode_id -> (simulation_run_id, review_id)` plus `seed_id`, `seed_dataset`, `seed_match_method`, `generation_kind`, `parent_seed_id`, `is_integration_test`, and `integration_test_id` without conflating session and episode identity. |
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
| INT-033 | Engineering full loop (planner/coder/reviewer) | Planner sets realistic budgets and emits `submit_engineering_plan`; Engineering Plan Reviewer inspects the current revision's real render artifacts before approving the handoff; coder implements the approved revision in `solution_script.py` and calls python `submit_solution_for_review(Compound)` only after passing latest-revision validation/simulation gates and manifest generation; reviewer approves/rejects with typed decision and evidence. |
| INT-034 | Reviewer evidence completeness | Review decisions include expected evidence fields, valid reviewer-specific handover manifest (for example `.manifests/benchmark_plan_review_manifest.json`, `.manifests/benchmark_review_manifest.json`, `.manifests/engineering_plan_review_manifest.json`, or `.manifests/engineering_execution_handoff_manifest.json`) tied to the latest revision and successful simulation result when that stage requires implementation evidence, reviewer-specific persisted review file path for that stage/round, and fail-closed visual-evidence enforcement when latest-revision render images exist (`inspect_media(...)`, `media_inspection`, `llm_media_attached`). |
| INT-035 | Materials config enforcement | Only materials defined in `manufacturing_config.yaml` are accepted by validation/simulation pipeline. |
| INT-036 | Supported workbench methods | CNC, injection molding, and 3D print validation/pricing each function in integrated runs. |
| INT-037 | Joint mapping to MJCF correctness | Build123d joint definitions map to expected MJCF constraints/actuators in integrated export/simulate flow. |
| INT-038 | Controller function family coverage | Constant/sinusoidal/square/trapezoidal (and position controllers where supported) execute via runtime config without schema/tool failures. |
| INT-039 | Render artifact generation policy | On-demand render/video behavior matches policy and artifacts are discoverable by reviewer/consumer paths; persisted simulation video/image artifacts visually retain benchmark objective boxes (goal green, forbid red, build gray) when the benchmark defines them. |
| INT-040 | Asset persistence linkage | Final scripts/renders/mjcf/video are stored in S3 and linked from DB records. |
| INT-058 | Cross-system correlation IDs | A single episode/trace can be correlated across controller logs/events and trace metadata; all non-empty `langfuse_trace_id` values remain consistent within the run. |
| INT-059 | Langfuse trace linkage in live runs | With valid `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`, live episode execution emits trace records linked by non-empty `langfuse_trace_id`; tool/LLM/event traces are correlated to the same run-level trace identity. |
| INT-060 | Langfuse feedback forwarding contract | `POST /episodes/{episode_id}/traces/{trace_id}/feedback` forwards score/comment to Langfuse and persists local feedback fields; missing Langfuse client returns `503`, missing `langfuse_trace_id` returns `400`. |
| INT-217 | Solution motor backend parity | A solution-authored moving part declared once in `assembly_definition.yaml` materializes as a validated controllable actuator on both MuJoCo and Genesis; unresolved or unsupported motor mappings fail closed before simulation can report success; `get_all_actuator_names()` and `get_actuator_state()` expose the same solution motor identity and force limits used by power gating and overload monitoring. |
| INT-218 | Materialized benchmark planner workspace submits | Role-specific workspaces materialize expected files and prompt fragments, `submit_benchmark_plan.sh` returns a success JSON result, and the expected manifest is present. |
| INT-219 | Materialized engineer planner workspace submits | Role-specific workspaces materialize expected files and prompt fragments, `submit_engineering_plan.sh` returns a success JSON result, and the expected manifest is present. |
| INT-222 | Eval profile ignores outer integration env | `run_evals.py --skip-env-up --runner-backend cli` exits 0 under `IS_INTEGRATION_TEST=true`, logs start/finish, and does not use controller-based integration setup. |
| INT-223 | Seed workspace materialization ignores outer integration env | Workspace materialization succeeds, creates the output directory, logs the workspace path, and does not emit the integration-test setup message. |
| INT-228 | Seed stage continues after closing open CLI UI terminal | `run_e2e_seed._run_stage(...)` materializes the workspace, opens the UI, then returns success after the terminal closes. |
| INT-237 | Open CLI UI uses new terminal when requested | `open_cli_ui(...)` launches the UI through a terminal wrapper, preserves the workspace cwd, and forwards `--wait`/title/working-directory flags. |
| INT-242 | Judge path skips reviewers without flag | `_run_cli_eval(...)` succeeds, updates benchmark coder stats, and never calls the reviewer chain when `run_reviewers_with_judge=False`. |
| INT-243 | Codex skill-loop flag enables loop backend | `_run_cli_eval(...)` succeeds with `enable_codex_skill_loop=True` and returns a successful benchmark coder run. |
| INT-244 | Codex skill loop resumes the same session twice | `_run_skill_loop(...)` resumes the same Codex session twice, records self-reflection and skill-update events, and preserves the updated trace. |
| INT-245 | Codex skill loop falls back to the primary session when trace is missing | `_run_skill_loop(...)` uses the primary session id for both resume turns when no trace artifact is available. |
| INT-248 | CLI-provider env isolates home and workspace Python path | `build_cli_env(...)` sets `HOME`, `CODEX_HOME`, `PYTHONPATH`, `PROBLEMOLOGIST_REPO_ROOT`, and `PYTHON_BIN` correctly and preserves auth/config state. |
| INT-250 | Codex env supports repo-root imports | A workspace script can import `shared.models.schemas.PartMetadata` and run under the Codex env. |
| INT-253 | VTK preview renders headlessly | Rendering succeeds with `DISPLAY`/`XAUTHORITY` unset, produces a non-empty preview image, and leaves the ambient display unset. |
| INT-254 | Preview scene bundle carries current role manifest | The preview bundle retains `.manifests/current_role.json` and the extracted manifest parses as the current agent role. |
| INT-255 | Submit helper imports workspace script from cwd | `scripts/submit_solution_for_review.sh` runs from the materialized workspace without `No module named 'script'` or load-stage fallback output. |
| INT-256 | Submit helper forces headless rendering env | The helper clears GUI env vars, sets headless/EGL vars, and preserves the repo-root Python path. |
| INT-260 | Prompt manager unified render uses shared source model | API and CLI renders share the same prompt source, preserve workspace-relative guidance, and keep the runtime-specific appendix ordering. |
| INT-265 | Seed workspace materialization is role-specific and deterministic | Planner/reviewer/coder seeds produce the expected file sets and prompt fragments, and mirrored workspaces remain deterministic. |

### P1 negative integration tests (`INT-NEG-###`)

| ID | Test | Required assertions |
| -- | -- | -- |

### P2: Support and tooling contracts

These runner, bootstrap, and seed-maintenance contracts are useful regression coverage, but they do not block release on their own.

| ID | Test | Required assertions |
| -- | -- | -- |
| INT-220 | `run_evals --help` exposes CLI backend | Help exits 0 and includes `--runner-backend`, `--call-paid-api`, `--level`, smoke-test defaults, and `cli`. |
| INT-221 | `skill_training --help` exposes retained bundle CLI | Help exits 0 and includes the retained session metadata/log-root flags. |
| INT-224 | `materialize_seed_workspace` requires explicit yolo choice | The CLI exits 2 when neither `--yolo` nor `--no-yolo` is supplied. |
| INT-225 | `materialize_seed_workspace` uses generic CLI flag names | The parser accepts `--launch-cli-exec` and `--open-cli-ui` with the generic destination names. |
| INT-226 | `materialize_seed_workspace` defaults provider to qwen | The parser defaults `provider` to `qwen` when unset. |
| INT-227 | `materialize_seed_workspace` forwards new-terminal flag | `--new-terminal` is threaded through to `open_cli_ui(...)`. |
| INT-229 | `run_e2e_seed` resume-from-dir uses checkpoint | Resume planning derives the next stage from the saved checkpoint and sets the correct resume label. |
| INT-230 | `run_e2e_seed` resume-from-dir requires checkpoint | Building a resume plan without saved state fails closed with `Resume state missing`. |
| INT-231 | `run_e2e_seed` resume-from-agent handle uses stage dir | Resume planning from an agent handle selects the corresponding stage directory and advances one stage. |
| INT-232 | `run_e2e_seed` resume-from-agent handle uses checkpoint chain | Resume planning follows the saved checkpoint chain for the agent handle and keeps the completed predecessor list intact. |
| INT-233 | `run_e2e_seed` resume-from-agent handle requires predecessor | Resume planning fails closed when the requested agent handle has no completed predecessor. |
| INT-234 | Seed workspace artifacts skip Git metadata | Collected seed artifact paths omit `.git/` entries from both the static listing and the materialized workspace snapshot. |
| INT-235 | CLI provider registry supports qwen | `get_cli_provider("qwen")` returns the qwen provider and preserves its home/runtime command contract. |
| INT-236 | CLI-provider invocation supports prompt flag transport | Prompt-flag transport runs the prompt through `--prompt` and preserves the qwen home env. |
| INT-238 | Skill training preserves legacy provider metadata | Loading a retained skill-training session keeps `provider_name` omitted from metadata and still reports the seeded skills dir. |
| INT-239 | `codex exec --help` exposes workspace-write sandbox | CLI help exits 0 and mentions `workspace-write` plus `--sandbox`. |
| INT-240 | Resume Codex exec uses the provider resume command | Resume execution builds `codex exec resume <session_id>` with `--full-auto` and without `--cd`. |
| INT-241 | Runner parser smoke defaults | Default parser values are `benchmark_planner`, `limit=1`, `concurrency=1`, and unset `level`. |
| INT-246 | Readable logs mirror imported transcript | Imported transcript text is copied into both readable-log locations with `SESSION_META`, message, and tool-call content preserved. |
| INT-247 | Level filter parser accepts combined values | `_parse_level_filters` accepts repeated, bracketed, and `or`-separated values and returns the unique integer set. |
| INT-249 | CLI-provider reasoning-effort translation hook is used | A custom provider remaps `xhigh` to `ultra` in the generated Codex config. |
| INT-251 | Codex env uses role reasoning effort and can disable | Planner configs emit `xhigh`, coder configs emit `high`, and the global toggle removes the field when disabled. |
| INT-252 | `build_dspy_lm` uses configured reasoning effort and toggle | The builder passes `xhigh` for planner roles, omits it when disabled, and preserves node/session identity. |
| INT-257 | Launch Codex exec uses expected sandbox policy | `--no-yolo` maps to `--full-auto`, `--yolo` maps to the bypass flags, and the opposite flag is absent. |
| INT-258 | Launch Codex exec allows host loopback when requested | Host-loopback opt-in switches the launcher to the bypass sandbox path without forcing `--full-auto`. |
| INT-259 | Prompt source role prompts follow runtime order | Prompt source keys are ordered by role family and include the CLI appendix providers. |
| INT-261 | Prompt manager appends CLI-provider-specific appendix | The qwen appendix is appended in CLI mode and the codex-specific appendix is absent. |
| INT-262 | Prompt manager injects bug-reporting appendix only when enabled | Bug-report mode appears only when the config flag is enabled. |
| INT-263 | Materialize seed workspace threads the CLI-provider appendix | The qwen appendix is threaded into the materialized prompt and the codex-specific appendix is absent. |
| INT-264 | Role-scoped planner wrapper rejects mismatched role | Submitting the benchmark-plan helper from an engineer-planner workspace fails closed and reports the role mismatch. |
| INT-266 | `clear_env` re-materializes a seeded workspace in place | Dirty workspace files are reset to the original snapshot and the benchmark definition is restored exactly. |
| INT-267 | Curated seed validation preserves redundancy metadata | `validate_eval_seed.py` passes representative curated rows and the generated manifests retain accepted/rejected counts plus lineage/drop metadata. |
| INT-268 | Seed validator removes preview bundles from seed artifacts | Validation strips transient `current-episode` and `tmp` directories from seeded artifacts. |
| INT-269 | Seed validator filters by complexity level | `--level 0` filters the validation run to the requested row and still passes. |
| INT-270 | `errors-only` suppresses pass output | `--errors-only` succeeds without printing pass lines or the all-passed summary. |
| INT-271 | Skip-env-up can join a shared eval lock | Validation runs under a shared eval lock and cleans up state. |
| INT-272 | Skip-env-up fails while exclusive eval lock is held | Validation exits 1 with the lock-held error and leaves no state file. |
| INT-273 | `run_evals` skip-env-up can join a shared eval lock | `run_evals.py --skip-env-up` succeeds under a shared lock and tears down cleanly. |
| INT-274 | `update_eval_seed_renders` skip-env-up can join a shared eval lock | Render updates fail closed with the lock-held state and report the missing task id. |
| INT-275 | Manifest hash refresh fixes drift | Dry-run reports stale hashes, fix mode rewrites them from file contents, and the updated manifest hash matches the payload. |
| INT-276 | Engineer planner payload-path swept-clearance validation | `validate_node_output()` must run `validate_payload_trajectory_swept_clearance()` for `engineer_planner` when `payload_trajectory_definition.yaml` is present, so the approved payload proof is swept-checked before planner handoff. |
| INT-277 | Engineer planner coarse-motion swept-clearance validation | `validate_planner_handoff_cross_contract()` must run the swept-clearance proof for `assembly_definition.yaml.motion_forecast` on the planner handoff, using the planner evidence geometry and rejecting clearance drift before coder refinement. |

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
| INT-029 | Use live endpoints with missing/invalid/valid API key headers. | Unit-test auth dependency in isolation only. |
| INT-030 | Start long run and interrupt through API; assert worker cancellation and final state. | Mocking interrupt handler methods. |
| INT-031 | Execute full benchmark planner->plan-reviewer->CAD->reviewer workflow over APIs; assert planner `submit_benchmark_plan` trace, benchmark plan-reviewer start blocked until valid latest-revision `.manifests/benchmark_plan_review_manifest.json` exists, benchmark coder materializes `benchmark_script.py` only after approval, and benchmark reviewer start blocked until valid latest-revision `.manifests/benchmark_review_manifest.json` exists. | Patching graph nodes in process. |
| INT-032 | Execute handoff and verify produced package artifacts from real storage paths, including latest-revision review manifest validity checks used by reviewer gate (no trace-only fallback, no model-side manifest reads), plus read-only `benchmark_script.py` and writable `solution_script.py` once the benchmark package is materialized. | Handcrafted dict payload assertions. |
| INT-033 | Run engineering planner/coder/reviewer loop end-to-end through services; assert planner `submit_engineering_plan`, plan-reviewer inspection of the current revision's real render bundle before approval, coder submission semantics (`submit_engineering_plan` vs python `submit_solution_for_review(Compound)`), strict latest-revision preconditions, writable `solution_script.py`, and fail-closed behavior on stale artifacts. | Node-level unit tests with mocked agent outputs or render stubs. |
| INT-034 | Submit real reviews and assert evidence completeness plus persisted reviewer-specific manifest linkage (`.manifests/benchmark_plan_review_manifest.json`, `.manifests/benchmark_review_manifest.json`, `.manifests/engineering_plan_review_manifest.json`, or `.manifests/engineering_execution_handoff_manifest.json`) for the accepted/rejected latest revision, reviewer-specific persisted review decision/comments YAML paths for the stage, fail-closed rejection when latest-revision renders exist but `inspect_media(...)` was not used, and `media_inspection`/`llm_media_attached` evidence for the satisfied path. | Unit-test of review schema only. |
| INT-035 | Use disallowed material in run and assert pipeline rejection from integrated config. | Local config parser unit test only. |
| INT-036 | Exercise CNC/injection/3DP through validation/pricing APIs with real artifacts. | Mocked workbench method returns. |
| INT-037 | Produce assembly and assert exported MJCF joint/actuator mapping from run outputs. | Unit-test mapper function only. |
| INT-038 | Execute controller function modes via runtime config in real simulation runs. | Direct function math unit tests only. |
| INT-039 | Trigger render/video via APIs and assert artifact policy behavior in storage. | Mocking renderer outputs. |
| INT-040 | Verify assets stored in S3 + DB links after real episode completion. | Fake storage client + call-count assertions. |
| INT-053 | Start real episode and assert lifecycle transitions persisted from the live controller/worker path. | Fake workflow objects in unit tests. |
| INT-055 | Complete real upload and assert object metadata persisted with episode linkage. | Storage adapter unit test with fake client only. |
| INT-058 | For one episode, correlate IDs across events and trace metadata from real persistence. | Asserting hardcoded correlation IDs in fixtures. |
| INT-059 | Run live episode with Langfuse configured and assert persisted trace linkage (`langfuse_trace_id`) across emitted traces. | Unit-testing callback wiring or mocking Langfuse handler calls only. |
| INT-060 | Call live feedback endpoint and assert both remote Langfuse scoring effect and local DB feedback persistence + error-path status codes. | Directly invoking feedback route function with mocked DB/Langfuse client only. |
| INT-061 | Request assets via live `GET /assets/{path}` with `X-Session-ID`; assert MIME behavior, cross-session denial, and `422` rejection for syntactically broken Python source. | Calling asset-serving helper directly or checking filesystem paths without HTTP boundary. |
| INT-063 | Attempt writes to mounted paths and writes to workspace root via live file APIs; assert read-only mounts and writable workspace behavior across worker surfaces. | Asserting config constants for mount paths without exercising container mounts. |
| INT-070 | Attempt mounted-path traversal via live file APIs (e.g., `/utils/../...`); assert deterministic `403` and no cross-boundary access. | Path-normalization unit checks without exercising worker HTTP/file boundary. |
| INT-071 | Execute per-agent file operations via live file APIs and assert `agents_config.yaml` precedence (`deny` > `allow`, unmatched deny, agent override), strict deny of `.manifests/**` to all agent roles, and reviewer-only stage-specific write scopes for the review decision/comments YAML pairs. | In-process path policy matcher and precedence helpers only. |
| INT-072 | Submit refusal artifacts through real planner/reviewer flow; assert invalid/missing `plan_refusal.md`, invalid role reasons, or empty evidence are rejected; assert `confirm_plan_refusal`/`reject_plan_refusal` transitions. | Frontmatter parser-only tests without exercising orchestration route/state transitions. |
| INT-073 | Execute real episode runs and assert persisted traces/events expose `user_session_id`, `episode_id`, `simulation_run_id`, `review_id`, `seed_id`, `seed_dataset`, `seed_match_method`, `generation_kind`, `parent_seed_id`, `is_integration_test`, and `integration_test_id` with joinable linkage and no session/episode conflation. | Checking schema fields exist without runtime persistence assertions. |
| INT-101 | Set `physics.backend` in config and hit simulation endpoint; assert backend-selected event and correct engine used. | Importing backend factory and calling it directly. |
| INT-114 | Run benchmark-planner flow over controller APIs and assert traces include `TOOL_START submit_benchmark_plan` with `node_type=benchmark_planner`; assert `.manifests/benchmark_plan_review_manifest.json` is created and benchmark plan reviewer entry is unblocked only for the latest planner revision; after plan-review approval, episode must reach `PLANNED` and not `FAILED`; benchmark planner must not receive `benchmark_script.py` before approval, because that file is introduced later by `Benchmark Coder`; missing submission must not reach success-like status. | Mocking benchmark planner internals or asserting only terminal status without planner submission trace evidence. |
| INT-210 | Run a MuJoCo simulation that captures video frames, assert `VideoRenderer.save()` delegates encoding to `worker-renderer`, and verify the final MP4 is materialized in the session workspace. | Keeping MP4 encoding in-process or asserting only a synthetic video stub. |
| INT-211 | Run a Genesis-backed simulation that captures render frames and assert the same renderer-worker video path and storage contract are used for the final MP4. | Testing Genesis frame capture without verifying the render handoff or artifact persistence. |
| INT-276 | Exercise engineer planner node-output validation with a payload proof present and assert `validate_payload_trajectory_swept_clearance()` is reached for `engineer_planner` before handoff completes. | Calling the coder-only branch or mocking only the submit-time payload validator without exercising planner node-output validation. |
| INT-277 | Exercise engineer planner handoff validation with coarse motion metadata and planner evidence geometry present, and assert `validate_planner_handoff_cross_contract()` runs the swept-clearance proof for `assembly_definition.yaml.motion_forecast` before planner handoff completes. | Calling only the payload-proof validator or bypassing the planner handoff validator. |

### P2: Developer-utility and repository-contract coverage

| ID | Test | Required assertions |
| -- | -- | -- |
| INT-279 | `dataset.synthetic.tube_guided_synthetic_rigid_body_corpus` and the compatibility wrapper in `notebooks/tube_guided_synthetic_rigid_body_corpus.py` stay importable, expose the same canonical exports, and preserve the six-point `default_route_points()` scaffold plus wrapper delegation for `main()` and `synthesize()`. | Importing the wrapper or package directly is not enough unless the export aliases and route-point ordering remain intact. |
| INT-280 | The generator-tree line-cap guard accepts the current `dataset/synthetic/tube_guided_synthetic_rigid_body_corpus` tree and fails closed on an oversized `.py` file tree that exceeds 800 lines. | Calling the guard on a temp tree with 801 lines must raise the cap error and name the violated limit. |

## Recommended suite organization

- `tests/integration/smoke/`: INT-001..INT-004 (fast baseline).
- `tests/integration/architecture_p0/`: INT-005..INT-021, INT-024..INT-030, INT-053, INT-055, INT-061..INT-063, INT-070..INT-073, INT-101, INT-114, INT-187, INT-218..INT-277.
- `tests/integration/architecture_p1/`: INT-031..INT-040, INT-058..INT-060, INT-210, INT-211, INT-217.
- `tests/integration/architecture_p2/`: INT-279..INT-280 (repo-split regression checks).

## Notes

- This spec intentionally treats architecture statements as test requirements, including expected fail paths.
- Existing unit tests for observability and workbench are useful, but they do not replace integration-level verification across controller, worker, db, and storage boundaries.
- If an implementation PR adds or changes integration tests, it should include the mapped `INT-xxx` or `INT-NEG-###` ID in the canonical `@pytest.mark.int_id(...)` marker.
