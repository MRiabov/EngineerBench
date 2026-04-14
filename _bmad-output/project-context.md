---
project_name: Problemologist-AI
user_name: Max
date: 2026-03-20
sections_completed:
  - technology_stack
  - repo_structure
  - critical_rules
  - verification_conventions
existing_patterns_found: 12
---

# Project Context for AI Agents

This repo is brownfield. Treat `specs/desired_architecture.md` and the files under `specs/architecture/` as the strongest reference point for architectural intent until you explicitly retire them. The docs bundle mirrors those decisions for day-to-day BMAD runs, but if README/docs disagree with specs, the specs still win.

## Technology Stack

- Backend: Python 3.12 (`~=3.12.0`), FastAPI, Uvicorn, TemporalIO, SQLAlchemy, Alembic, PostgreSQL, MinIO/S3, structlog, Pydantic v2, pydantic-settings.
- Agent/runtime layer: DSPy, LiteLLM, LangGraph, Langfuse, OpenInference for DSPy.
- CAD/simulation: build123d, bd-warehouse, MuJoCo, Genesis, Gmsh, trimesh, NumPy, SciPy, PySpice, torch.
- Frontend: Vite 7.2.4, React 19.2.0, TypeScript ~5.9.3, Vitest, Testing Library, Radix UI, React Three Fiber, three.
- Tooling: `uv`, Ruff, Pyright, pytest, schemathesis, Playwright, Docker/Podman, Docker Compose.

## Repository Layout

- `controller/`: API, LangGraph/DSPy orchestration, Temporal workflows, persistence, observability, node-entry validation.
- `worker_light/`: session filesystem, git, linting, short runtime execution, asset serving.
- `worker_heavy/`: validation, simulation, rendering, manufacturability analysis, preview generation.
- `shared/`: strict schemas, enums, simulation/circuit/wire helpers, observability, COTS helpers.
- `utils/`: agent-facing wrappers. Submission CAD scripts should import `utils.submission` and `utils.metadata`, not `shared.*`.
- `frontend/`: React app and generated API client.
- `skills/`: canonical runtime skill mount.
- `suggested_skills/` and `.codex/skills/`: not the runtime contract.
- `specs/`: architecture and workflow source of truth.
- `_bmad-output/`: generated workflow artifacts, including this file.

## Critical Rules

- Use the architecture docs as the implementation contract. Do not fill gaps from memory when the docs already define the behavior.
- This repo uses integration tests as the real verification path. Prefer black-box integration tests through the compose stack; do not replace them with unit tests or mocked project/runtime boundaries.
- Heavy controller work must route through Temporal/controller-temporal-worker orchestration. `worker-heavy` is single-flight and must fail closed with deterministic busy responses when occupied.
- Do not run LLM-generated CAD/simulation code directly on the controller.
- Planner/reviewer handoffs are strict files, not implicit state. Respect the stage-specific review YAMLs and keep `.manifests/**` system-only.
- Benchmark-owned fixtures in `benchmark_definition.yaml` are read-only task context. Engineer-owned manufacturable parts live in `assembly_definition.yaml` and the authored CAD result.
- Every CAD part/compound should carry strict metadata. Use `PartMetadata` / `CompoundMetadata` and enum-backed categorical fields; unknown schema fields are rejected.
- Agent-authored scripts should be direct, runnable `python script.py` entrypoints. `build()` is compatibility-only, not the canonical contract.
- If renders exist for the current node/revision, required roles must inspect them with `inspect_media(...)`; reading the file path with `read_file` does not count as visual inspection.
- Static validation previews use MuJoCo by default, even when the simulation backend is Genesis. Genesis-specific claims require actual Genesis simulation runs.
- Electromechanical tasks need explicit electrical design, circuit validation, and wire routing when wiring is part of the benchmark. Benchmark-owned electronics may be implicit/read-only only when the benchmark explicitly declares that behavior.
- Treat `user_session_id` and `episode_id` as distinct observability identities. Persist both when possible.
- If you change API contracts, regenerate OpenAPI artifacts and the frontend client instead of hand-editing generated code.
- Path permissions and visual-inspection policy come from `config/agents_config.yaml`. Use workspace-relative paths; `/workspace` is a compatibility fallback, not the preferred contract.
- COTS search is read-only and should be done through the provided subagent or catalog helpers. Any named off-the-shelf component in planner artifacts must resolve to a concrete episode-local catalog `part_id`.
- Benchmark and engineering handoffs are fail-closed: missing files, invalid schemas, stale manifests, or invalid adapters/validation state should reject the run rather than falling back.

## Codebase Patterns

- Python formatting is 88 columns with Ruff; type checking is basic Pyright on Python 3.12.
- Frontend imports use the `@/` alias.
- The frontend dev server proxies `/api` to the controller and `/api/benchmark/build` to `worker_light`.
- OpenAPI artifacts are committed in the repo; generated frontend API code lives under `frontend/src/api/generated`.
- Use `rg` for search when exploring the repo.
- Preserve existing worktree changes unless a task explicitly requires otherwise.

## Verification Conventions

- Prefer real integration tests through `scripts/run_integration_tests.sh`.
- Assert against HTTP responses, DB rows, object storage, logs, render artifacts, and `events.jsonl`.
- Do not assert against internal function calls when the behavior is meant to cross service boundaries.
- When a change touches evaluation, handoff validation, simulation, or rendering, verify against the integration suite and the architecture specs before calling it done.
- We treat "unit" tests as non-reliable in this repository and we don't rely on unit tests. If a test needs to be introduced or changed, it should be documented in `integration-tests.md`, and it must abide rules of the docuement
