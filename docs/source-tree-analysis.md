# Problemologist-AI - Source Tree Analysis

**Date:** 2026-03-20

## Overview

The repository is organized around a controller-led runtime with split worker services, a shared contract layer, and a React dashboard. The tree also contains supporting assets for evaluation, research, docs, and local development.

## Abridged Tree

```text
.
|-- controller/
|-- worker_light/
|-- worker_heavy/
|-- shared/
|-- config/
|-- scripts/
|-- tests/
|-- dataset/
|-- _bmad-output/
|-- docs/
|-- .agents/
|   `-- skills/
|-- website/
`-- docker-compose.yml
```

## Critical Directories

| Path | Purpose | Notable Files |
| -- | -- | -- |
| `controller/` | Agent orchestration, HTTP APIs, persistence, and observability | `api/main.py`, `agent/graph.py`, `agent/nodes/`, `clients/worker.py`, `middleware/remote_fs.py`, `persistence/models.py` |
| `worker_light/` | Session filesystem and lightweight execution services | `app.py`, `api/routes.py`, `runtime/executor.py`, `utils/`, `agent_files/` |
| `worker_heavy/` | Validation, simulation, workbench analysis, and simulation render coordination | `app.py`, `api/routes.py`, `simulation/`, `workbenches/`, `runtime/simulation_runner.py`, `utils/` |
| `worker_renderer/` | Dedicated headless preview rendering and render-manifest persistence | `app.py`, `api/routes.py`, `utils/` |
| `shared/` | Shared schemas, enums, observability, workers, and simulation types | `models/`, `observability/`, `simulation/`, `workers/`, `agents/config.py` |
| `config/` | Runtime configuration and policy files | `agents_config.yaml`, `prompts.yaml`, `manufacturing_config.yaml`, `reward_config.yaml`, `lint_config.yaml` |
| `scripts/` | Local environment and test automation scripts | `env_up.sh`, `env_down.sh`, `run_integration_tests.sh`, `cleanup_local_s3.py` |
| `tests/` | Integration coverage and support test data | `integration/`, `e2e/`, `controller/`, `worker_light/`, `worker_heavy/` |
| `dataset/` | Seed data and eval scaffolding | `data/`, `evals/` |
| `_bmad-output/planning-artifacts/` | BMAD planning artifacts such as PRDs, epics, stories, and supporting research notes | `prd.md`, `epics.md`, `*.md` |
| `docs/` | Self-contained project documentation bundle | `index.md`, `project-overview.md`, `source-tree-analysis.md`, `backend-reference.md`, `architecture.md`, `api-contracts.md`, `data-models.md`, `component-inventory.md`, `deployment-guide.md`, `development-guide.md`, `spec-coverage.md` |
| `.agents/skills/` | Canonical skill repository consumed by agent workflows | `build123d-cad-drafting-skill`, `electronics-engineering`, `manufacturing-knowledge`, `mechanical-engineering`, `runtime-script-contract`, `skill-creator`, `spec-editing-style-guide` |
| `website/` | Standalone static mirror of the marketing site | Asset mirror and published site files |

## Entry Points

| Entry Point | What It Starts |
| -- | -- |
| `controller/api/main.py` | Controller FastAPI app on port 8000 in containers and 18000 in local dev |
| `worker_light/app.py` | Worker-light FastAPI app on port 8001 in containers and 18001 in local dev |
| `worker_heavy/app.py` | Worker-heavy FastAPI app on port 8002 in containers and 18002 in local dev |
| `controller/temporal_worker.py` | Controller Temporal worker for durable orchestration |
| `worker_heavy/temporal_worker.py` | Heavy-worker Temporal worker for simulation and validation workflows |
| `worker_renderer/app.py` | Dedicated headless renderer app for preview and media generation |
| `scripts/env_up.sh` | Local infrastructure and application bootstrap |
| `scripts/run_integration_tests.sh` | Canonical integration test runner |

## File Organization Patterns

| Pattern | Meaning |
| -- | -- |
| `api/routes/` | HTTP route groups, usually organized by product area |
| `agent/nodes/` | LangGraph node implementations for planner, coder, and reviewer roles |
| `agent/benchmark/` | Benchmark-generation graph, state, and benchmark-specific utilities |
| `shared/models/` | Strict Pydantic contracts used across services |
| `worker_heavy/workbenches/` | Manufacturing and pricing logic for CNC, injection molding, and 3D printing |

## Notes

The top-level `main.py` file is a legacy convenience shim rather than the canonical runtime entry point. The operational services are the controller and split worker apps.

The `website/` directory is separate from the core product runtime. It mirrors the published marketing site and does not participate in the agent workflows.
