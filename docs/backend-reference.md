# Problemologist-AI - Backend Reference

**Date:** 2026-03-20

## Scope

This is the backend-first reference for the repository. It covers the controller, worker split, agent graphs, handoff contracts, simulation and evaluation gates, observability, and the modality-specific branches that matter for dataset generation and backend validation. The publication bundle is a narrower subset of the development tree; this document calls out the retained backend surfaces and leaves the out-of-bundle tools, docs, and auxiliary services to the migration notes.

## 1. Product Purpose

| Output family | What the backend must preserve |
| -- | -- |
| Benchmarks | Randomized physics problems that can be handed to the engineering graph |
| Reasoning traces | Tool calls, planner and reviewer reasoning, execution summaries, and refusal evidence |
| Solutions | CAD scripts, simulation artifacts, MJCF, renders, and review manifests |
| Skills | Learned `SKILL.md` artifacts, session-local skill worktrees/checkpoints, and supporting files |
| Journals | Scannable execution summaries, postmortems, and decision logs |
| Training corpus | Persisted episode bundles, traces, review artifacts, render evidence, and skill-worktree metadata used by downstream skill training |
| Optimization notes | Improvements that were found but not applied |
| Framework | Reusable backend platform for benchmark generation and mechanical problem solving |

The main operational priority is backend dataset generation. The frontend is an inspection surface, not the primary engineering target.

## 2. Runtime Topology

| Part | Responsibility | Operational contract |
| -- | -- | -- |
| Controller | Owns HTTP APIs, agent graphs, persistence, review gating, observability, and worker routing | Never executes generated code directly |
| Worker Light | Owns session filesystem access, git, shell execution, linting, asset serving, and lightweight inspection | Session-scoped workspace, read/write policy enforced by config |
| Worker Heavy | Owns validation, simulation, workbench analysis, heavy handoff gating, and simulation render coordination | Single-flight admission, `503 WORKER_BUSY` while active |
| Worker Renderer | Owns headless preview rendering, selection snapshots, depth/segmentation previews, and render-manifest persistence | Dedicated single-flight renderer service |
| Controller Temporal Worker | Development-tree only orchestration helper | Not included in the publication bundle |
| Worker Heavy Temporal Worker | Development-tree only heavy activity helper | Not included in the publication bundle |
| Shared Layer | Owns Pydantic schemas, enums, simulation models, observability models, and worker contracts | Strict schemas reject unknown fields |

## 3. Agent Graphs

| Graph | Stage order | Required artifacts | Gate behavior |
| -- | -- | -- | -- |
| Benchmark generator | Planner -> Plan Reviewer -> Coder -> Reviewer | `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml` | Plan review before implementation, execution review after validation and simulation |
| Engineering | Planner -> Plan Reviewer -> Coder -> Electronics Reviewer when needed -> Execution Reviewer | `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, `script.py` | Plan review before coding, execution review after validated simulation |

Runtime conversations use four message roles: `system`, `user`, `assistant`, and `tool`.

### Role responsibilities

| Role | Core responsibility | Failure or refusal contract |
| -- | -- | -- |
| Benchmark Planner | Design a benchmark that teaches a specific capability and writes the benchmark-owned task files | Must supply valid benchmark material IDs, estimate fields, geometry, and randomization data |
| Benchmark Plan Reviewer | Verify cross-artifact consistency before implementation starts | Read-only; routes back on inconsistency, ambiguity, or unsupported motion |
| Benchmark Coder | Implement the approved benchmark | May refuse only when the plan is infeasible to implement |
| Benchmark Reviewer | Verify the implemented benchmark is valid, solvable, and reviewable | Requires latest revision evidence and dynamic evidence for moving fixtures |
| Engineering Planner | Design a physically feasible solution under cost and weight caps | Must keep planner-owned totals under benchmark caps and use realistic COTS pricing |
| Engineering Plan Reviewer | Validate the combined engineering handoff before coding | Must re-run cost/price validation and reject excessive DOFs or impossible designs |
| Engineering Coder | Implement the approved unified solution in one revision | May refuse only with a valid `plan_refusal.md` and proof |
| Engineering Execution Reviewer | Final review after validation and simulation success | Requires latest revision evidence, visual inspection when renders exist, and robustness checks |

## 4. Handover Artifacts

| Stage | Required files | Stage manifest | Persisted review files |
| -- | -- | -- | -- |
| Benchmark planner submission | `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml` | `.manifests/benchmark_plan_review_manifest.json` | N/A |
| Benchmark execution review | Latest validated `script.py` and benchmark artifacts | `.manifests/benchmark_review_manifest.json` | `reviews/benchmark-execution-review-decision-round-<n>.yaml`, `reviews/benchmark-execution-review-comments-round-<n>.yaml` |
| Engineering planner submission | `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml` | `.manifests/engineering_plan_review_manifest.json` | N/A |
| Engineering execution review | Latest validated `script.py` and engineering artifacts; coder-written handoff manifest shared with the reviewer gate | `.manifests/engineering_execution_handoff_manifest.json` | `reviews/engineering-execution-review-decision-round-<n>.yaml`, `reviews/engineering-execution-review-comments-round-<n>.yaml` |
| Electronics review | Development-tree only electromechanical review artifacts | `.manifests/electronics_review_manifest.json` | `reviews/electronics-review-decision-round-<n>.yaml`, `reviews/electronics-review-comments-round-<n>.yaml` |

### Handover rules

| Rule | Meaning |
| -- | -- |
| Strict schema | Unknown or extra fields fail closed in planner and reviewer artifacts |
| Read-only benchmark fixtures | Benchmark-owned fixtures are observation context, not engineer-owned solution metadata |
| Refusal artifact | `plan_refusal.md` is required for valid coder refusal loops and must carry proof for the reviewer gate |
| Refusal routing | Valid coder refusal requires evidence and routes back through plan review |
| Manifest ownership | `.manifests/**` is system-owned and denied to agent file access |
| Review persistence | Decision YAML drives routing; comments YAML is explanatory and evaluative |

## 5. Filesystem and Tool Surface

| Surface or tool | Contract |
| -- | -- |
| `execute_command` | Shell execution from the session workspace root |
| `read_file` / `write_file` / `edit_file` / `grep` / `list_files` | Respect path policy and session isolation |
| `inspect_media` | The only agent-facing tool that counts as visual inspection |
| `submit_benchmark_plan()` / `submit_engineering_plan()` | Mandatory planner completion gate |
| `submit_benchmark_for_review()` / `submit_solution_for_review()` | Role-scoped coder handoff submission gate |
| `submit_review` | Mandatory reviewer completion gate |
| `validate_benchmark()` / `validate_engineering()` | Role-scoped geometry validation plus fast preview generation |
| `simulate_benchmark()` / `simulate_engineering()` | Physics-backed simulation or benchmark simulation path |
| `validate_and_price` | Manufacturability and price validation for engineer-owned parts and assemblies |
| `invoke_cots_search_subagent` | Single prompt-only request to the shared COTS Search node |
| Workspace paths | Canonical paths are workspace-relative; `/workspace` exists only as a compatibility alias |

### Filesystem ownership

| Role family | Read scope | Write scope |
| -- | -- | -- |
| Benchmark planner | Skills, utils, and benchmark planner artifacts | Planner-owned benchmark files only |
| Benchmark reviewer | Planner artifacts, renders, journals, and implementation artifacts needed for review | Stage-specific review YAML pairs only |
| Engineer planner | Skills, utils, benchmark inputs, and planner artifacts | Planner-owned engineering files only |
| Engineer coder | Planner artifacts, reviewer outputs, renders, and helper files | `script.py`, helper modules, journal, refusal file, and progress-only TODO updates |
| Reviewers | Approval evidence, renders, planner artifacts, and implementation files | Stage-specific review YAML pairs only |

## 6. Distributed Execution

| Concern | Contract |
| -- | -- |
| Controller execution | Controller owns orchestration and API traffic, not generated code execution |
| Worker-light | Handles filesystem, git, shell, lint, and asset serving |
| Worker-heavy | Handles validation, simulation, preview, and manufacturing analysis |
| Temporal boundary | Long-running heavy work goes through Temporal-backed orchestration |
| Admission control | Heavy workers are single-flight and return deterministic busy responses |
| Session isolation | Every episode uses a session-scoped workspace keyed by `X-Session-ID` |
| Validation preview split | `/benchmark/validate` and `/engineering/validate` produce fast preview artifacts and do not double as the Genesis parity path |
| Heavy requests | Controller path proxies through the orchestration layer; direct worker-heavy HTTP is reserved for integration boundaries |

## 7. CAD, Workbench, and Artifact Rules

| Topic | Contract |
| -- | -- |
| Part metadata | Engineer-owned parts must carry manufacturing metadata; benchmark fixtures may carry read-only fixture metadata |
| Ownership split | Benchmark environment, input objects, and objective markers are read-only task fixtures |
| COTS parts | Catalog parts may appear in benchmark fixtures or engineer solutions, but pricing only counts engineer-owned outputs |
| Supported workbenches | CNC, injection molding, and 3D printing |
| Fasteners | Rigid connections use build123d joints and bd-warehouse fasteners |
| DOFs | Engineering solutions default to static parts; non-empty DOFs must be mechanism-necessary |
| Benchmark fixture motion | Benchmark fixtures may use any explicit motion profile, including fully free rigid bodies, but the benchmark contract must declare and validate the motion; benchmark-side motion is not subject to the engineering minimum-DOF rule |
| Drill policy | Benchmark-owned drilling is forbidden unless the benchmark explicitly declares a drill policy |
| Renders | Static validation preview uses 24 views by default, with RGB, depth, and segmentation siblings and a `render_manifest.json` companion |
| Segmentation legend | Legend entries must distinguish semantic labels from instance identifiers |

## 8. Simulation and Definition of Done

| Topic | Contract |
| -- | -- |
| Backend selection | `physics.backend` selects MuJoCo or Genesis; Genesis is required for fluids, deformables, and stress-aware runs |
| Validation | `/benchmark/validate` and `/engineering/validate` use MuJoCo for static preview by default even if the simulation backend is Genesis |
| Success | The target object reaches the goal zone without violating forbid zones or other success constraints |
| Failure taxonomy | Out-of-bounds, timeout, instability, breakage, forbidden contact, and circuit/power failures must be classified explicitly |
| Constraint realism | Engineer-authored constraints must be physically plausible; CAD constraints cannot stand in for real-world fasteners or joints |
| Joints | `RigidJoint` maps to welds, `RevoluteJoint` maps to hinges, and `PrismaticJoint` maps to slides in the simulator contract |
| Motion evidence | Moving benchmarks require dynamic evidence in addition to static preview images, and the observed motion must match the declared benchmark contract |
| Benchmark exception | Benchmark-owned moving fixtures may be less complete than engineer solutions, but they cannot be teleporting or unstable |
| Timing | The rigid-body timestep is `0.002 s` and max simulation time is `30 s` unless a config says otherwise |

### Capability branches

| Branch | Stable contract |
| -- | -- |
| Fluids and deformables | Genesis is the required backend, materials must carry stress-relevant properties, and benchmark definitions may declare fluid and stress objectives |
| Electronics and electromechanics | Benchmark definitions may declare electrical requirements, unified engineering solutions may define `electronics` in `assembly_definition.yaml`, and circuit validity gates motion |

## 9. Evals and Gates

| Tier | Purpose | Contract |
| -- | -- | -- |
| Fast | Markdown, YAML, code validity, and basic schema checks | Used as a cheap correctness screen |
| Medium | Role-specific planner, coder, and reviewer performance checks | Measures quality and robustness across seeded cases |
| Slow | End-to-end production-like evaluation | Used for full workflow regression and dataset-quality gates |

| Gate | Contract |
| -- | -- |
| Planner submission | Must call `submit_benchmark_plan()` or `submit_engineering_plan()` and receive `ok=true` before handoff |
| Reviewer completion | Must use the stage-correct manifest and review persistence files |
| Visual inspection | If renders exist for a required role, the role must call `inspect_media(...)` before approval or finish |
| Skill training | `train_skills.py` or equivalent owns the standalone replay/training loop over retained bundles and session-local skill overlays; a separate promotion arbiter publishes approved diffs into canonical `.agents/skills/`; `run_evals.py` stays a thin eval launcher |
| Fail closed | Missing artifacts, invalid schema, or stale manifests block progress rather than being auto-healed |

## 10. Observability and Lineage

| Category | Contract |
| -- | -- |
| Core IDs | `user_session_id`, `episode_id`, `simulation_run_id`, `cots_query_id`, `review_id`, and `trace_id` |
| Lineage fields | `seed_id`, `seed_dataset`, `seed_match_method`, `generation_kind`, `parent_seed_id`, `is_integration_test`, `integration_test_id` |
| Event families | Tool calls, simulations, manufacturability checks, review decisions, refusals, lint failures, and media inspections |
| Error stream | Machine-readable backend errors must remain attributable to a run-level identifier |
| Backups | Durable state is backed up and the backup path must be observable |
| Feedback | Trace feedback is persisted locally and may be forwarded to Langfuse |
| Metrics | Solvability, plan adherence, price/weight accuracy, robustness, visual-evidence usage, and reviewer precision/recall are all tracked |

## 11. Backend Reading Order

| Need | Start here |
| -- | -- |
| Dataset generation and benchmark workflow | This backend reference, then the architecture and API docs |
| Simulation and manufacturability work | This backend reference, then the data-model and deployment docs |
| Agent handoff or review work | This backend reference, then the architecture and API docs |
| Observability work | This backend reference, then the data-model and deployment docs |
| UI-only work | The component inventory is the better entry point |
