# Problemologist-AI - Deployment Guide

**Date:** 2026-03-22

## Overview

Problemologist-AI runs in two practical modes:

1. A local development mode that starts the services with `scripts/env_up.sh`.
2. A containerized stack defined by `docker-compose.yml` and `docker-compose.test.yaml`.

The local workflow is the main entry point for day-to-day backend engineering. The containerized stack is the closest thing to a production deployment shape and is the reference for service dependencies and ports. The frontend is optional for backend-only work.

## Prerequisites

| Tool | Why It Is Needed |
| -- | -- |
| Python 3.12 | Runs the controller, workers, scripts, and tests |
| `uv` | Installs and runs the Python environment |
| Docker or Podman | Starts PostgreSQL, MinIO, Temporal, and the service containers |
| Node.js and npm | Only needed when you are working on the frontend |

## Local Development Deployment

### Start

```bash
./scripts/env_up.sh
```

This script:

- Stops any existing local environment first.
- Loads `.env` if present.
- Ensures Docker/VFS compatibility for constrained environments.
- Starts the test infrastructure containers from `docker-compose.test.yaml`.
- Runs database migrations.
- Starts the controller, worker-light, worker-heavy, controller-temporal-worker, and worker-heavy Temporal worker as local processes.
- Starts the frontend dev server on port `15173` if the port is free and the UI is needed.

### Stop

```bash
./scripts/env_down.sh
```

This script:

- Stops the local Python and optional frontend processes using the saved PID files.
- Kills any leftover Uvicorn or Temporal worker processes.
- Brings down the test infrastructure containers.
- Removes the local MinIO test volume so object-store state does not leak between runs.

## Containerized Stack

The root `docker-compose.yml` describes the full multi-service stack:

- `controller`
- `controller-temporal-worker`
- `worker-light`
- `worker-heavy`
- `worker-heavy-temporal`
- `postgres`
- `minio`
- `temporal`
- `temporal-ui`
- `migrations`
- `mock-warning`

The stack is configured for the controller to talk to the workers and Temporal over service names on the internal Docker network.

## Test Infrastructure Stack

`docker-compose.test.yaml` provides the infrastructure used by local development and integration tests:

- PostgreSQL
- MinIO
- Temporal
- Temporal UI
- `createbuckets` to seed the expected buckets in MinIO

This stack is intentionally smaller than the full compose file because the application processes themselves are launched locally by `env_up.sh`.

## Service Ports

| Service | Local Port | Container Port | Notes |
| -- | -- | -- | -- |
| Controller | `18000` | `8000` | Main FastAPI API |
| Worker Light | `18001` | `8001` | Filesystem, git, runtime, and linting |
| Worker Heavy | `18002` | `8002` | Validation, simulation, workbench analysis, and simulation render coordination |
| Worker Renderer | `18003` | `8003` | Headless preview rendering and render-manifest persistence |
| PostgreSQL | `15432` | `5432` | Persistent workflow state |
| MinIO S3 API | `19000` | `9000` | Asset storage |
| MinIO Console | `19001` | `9001` | Object-store UI |
| Temporal | `17233` | `7233` | Durable workflow engine |
| Temporal UI | `18081` | `8080` | Temporal dashboard |
| Frontend dev server | `15173` | n/a | Vite dev server |

## Environment Variables

| Variable | Purpose |
| -- | -- |
| `IS_INTEGRATION_TEST` | Enables integration-test behavior, smoke-mode simulation tuning, and test-only routes |
| `OPENAI_API_KEY` | Required for real model calls |
| `OPENAI_API_BASE` | Optional OpenAI-compatible base URL |
| `POSTGRES_URL` | Database connection string |
| `TEMPORAL_URL` | Temporal service endpoint |
| `S3_ENDPOINT` | MinIO or S3-compatible endpoint |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Object-store credentials |
| `WORKER_URL` | Worker-light base URL used by the controller |
| `WORKER_HEAVY_URL` | Worker-heavy base URL used by the controller |
| `WORKER_RENDERER_URL` | Worker-renderer base URL used by preview and media render helpers |
| `WORKER_TYPE` | Switches a worker process into light, heavy, or unified mode |
| `VITE_API_URL` | Frontend API base URL |

## Health And Readiness

| Service | Health Endpoint | Behavior |
| -- | -- | -- |
| Controller | `/health` | Reports controller health and integration-test mode |
| Worker Light | `/health` | Reports worker-light health |
| Worker Heavy | `/health`, `/ready` | Direct worker admission/readiness signal only: `/ready` returns `503 WORKER_BUSY` while a heavy job is active; controller/product routes must not expose that raw status |

## Persistence And Runtime State

| Storage | Purpose |
| -- | -- |
| PostgreSQL | Episodes, traces, assets, sessions, preferences, and review state |
| MinIO | Rendered assets, simulation artifacts, and bundles |
| Worker session filesystem | Live workspace files for each episode/session |
| `logs/manual_run/` | Local log bundle for `env_up.sh` |
| `logs/archives/` | Archived log bundles from previous runs |

## Deployment Notes

- The controller expects Temporal to be reachable before it starts serving traffic.
- `worker-heavy` uses off-screen rendering settings and `xvfb-run` in container mode.
- The controller and workers are designed to talk through their HTTP APIs, not through shared in-memory state.
- `worker-heavy` is single-flight by design, so a busy instance should be treated as temporarily unavailable rather than overloaded.
- `./scripts/run_integration_tests.sh` is the source of truth for integration orchestration; it archives prior `logs/integration_tests/` content into `logs/archives/run_*` and rewires the current-run symlinks for each invocation.
- If the local environment gets stuck on stale ports or unhealthy containers, run `./scripts/env_down.sh` before retrying the integration runner.
- If you change controller routes, regenerate the frontend OpenAPI client under `frontend/src/api/generated/`.

## Common Operational Commands

```bash
./scripts/env_up.sh
./scripts/env_down.sh
./scripts/run_integration_tests.sh
cd frontend && npm run build
```

## Deployment Checklist

1. Confirm `.env` contains the model and storage credentials you intend to use.
2. Start the environment with `./scripts/env_up.sh`.
3. Verify controller, worker-light, worker-heavy, PostgreSQL, MinIO, and Temporal are healthy.
4. Run the integration suite with `./scripts/run_integration_tests.sh`.
5. Check the frontend at `http://127.0.0.1:15173` only if you are working on the UI.
6. Review the logs in `logs/manual_run/` if any service fails to start.
