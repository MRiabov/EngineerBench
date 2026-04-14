# Problemologist-AI - Project Overview

**Date:** 2026-03-20
**Repository Type:** Multi-part platform
**Architecture Pattern:** Backend-first controller-led orchestration with split worker services and a secondary React dashboard

## Executive Summary

Problemologist-AI is an agentic CAD and physics platform for generating benchmark problems and solving them under physical, economic, and manufacturability constraints. The repository contains the controller that runs the agent graphs, the worker services that execute filesystem and simulation work, a shared schema layer that keeps the system contract strict, and a secondary React frontend for inspection and feedback. The publication bundle is a narrower subset of this development tree; this overview calls out the broader tree and marks the secondary or out-of-bundle surfaces where relevant.

The project is brownfield and already has a working integration-test harness. The main operational goal is not just to run the code, but to keep the benchmark-generation and engineer workflows aligned with the backend architecture and evaluation contracts while dataset generation remains the priority.

## Project Classification

| Field | Value |
| -- | -- |
| Repository Type | Multi-part platform |
| Primary Languages | Python first, TypeScript for the secondary UI |
| Main Runtime Style | FastAPI services plus LangGraph/DSPy agent orchestration |
| User-Facing UI | Secondary React dashboard built with Vite |
| Primary Storage | PostgreSQL, MinIO, and session-local worker filesystems |
| Durable Orchestration | Temporal |
| Observability | Structured DB traces plus Langfuse |

## Primary Outputs

| Output Family | What the System Preserves |
| -- | -- |
| Benchmarks | Randomized physics problems that are safe to hand to the engineer graph |
| Reasoning Traces | Tool calls, planner/reviewer reasoning, and execution summaries |
| Solutions | CAD scripts, simulation artifacts, MJCF, renders, and review manifests |
| Skills | Learned `SKILL.md` artifacts and their supporting files |
| Journals | Scannable execution summaries and decision logs |
| Optimization Notes | Interesting improvements that were found but not applied |
| Framework | A reusable backend platform for benchmark generation and mechanical problem solving |

## Major Parts

| Part | Location | Responsibility |
| -- | -- | -- |
| Controller | `controller/` | Owns agent graphs, HTTP APIs, persistence, review gating, and worker routing |
| Worker Light | `worker_light/` | Owns the session filesystem, git, shell execution, linting, assets, and lightweight inspection |
| Worker Heavy | `worker_heavy/` | Owns validation, simulation, manufacturability analysis, heavy handoff paths, and simulation render coordination |
| Worker Renderer | `worker_renderer/` | Owns headless preview rendering, selection snapshots, depth/segmentation previews, and render-manifest persistence |
| Shared | `shared/` | Owns the strict models, enums, observability schemas, simulation contracts, and filesystem policy helpers |
| Frontend | `frontend/` | Secondary operator dashboard for trace inspection, simulation viewers, and feedback flow; not part of the publication bundle |

## Key Features

| Feature | Notes |
| -- | -- |
| Benchmark generation graph | Planner, plan reviewer, coder, and reviewer stages with deterministic handoff checks |
| Engineer graph | Planner, plan reviewer, coder, and execution reviewer |
| Rigid-body mechanics | Pure rigid-body benchmark generation and solution flow |
| Workbench analysis | Cost and manufacturability checks driven by the manufacturing configuration |
| Simulation split | Fast validation preview versus backend simulation are intentionally separate |
| Visual review policy | Render inspection is policy-driven and enforced when images are available |
| Session isolation | Each episode uses an isolated worker session filesystem and per-session tracing |
| Dataset generation priority | Backend workflows and eval gates are the primary focus; the frontend is supporting tooling |

## Technology Stack Summary

| Layer | Technology |
| -- | -- |
| API services | FastAPI |
| Agent orchestration | LangGraph and DSPy-based agent reasoning |
| Language runtime | Python 3.12 |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS |
| Simulation | Genesis and MuJoCo |
| CAD | build123d |
| Persistence | PostgreSQL, SQLAlchemy, Alembic |
| Object storage | MinIO-backed S3-compatible storage |
| Durable workflows | Temporal |
| Observability | Langfuse, structured events, and DB-backed traces |
| Validation and formatting | Ruff, linting helpers, and strict Pydantic schemas |

## Repository Structure

| Top-Level Area | What It Contains |
| -- | -- |
| `controller/` | API entry points, agent nodes, workflows, persistence, and observability |
| `worker_light/` | Filesystem, runtime, git, assets, topology, and lightweight API routes |
| `worker_heavy/` | Simulation runners, workbenches, simulation render helpers, and heavy API routes |
| `worker_renderer/` | Dedicated headless preview renderer, preview post-processing, and render-manifest routes |
| `shared/` | Shared contracts, enums, schemas, workers, observability, and simulation models |
| `frontend/` | Dashboard routes, state providers, visual components, and generated API client |
| `config/` | Agent policy, prompts, manufacturing config, lint config, and reward config |
| `scripts/` | Local environment, cleanup, test runner, and maintenance scripts |
| `tests/` | Integration and support tests |
| `docs/` | This self-contained documentation set |
| `.agents/skills/` | Canonical skill repository; runtime surfaces read it directly or expose it through the `/skills` mount |

## Development Snapshot

| Task | Command |
| -- | -- |
| Start the local environment | `./scripts/env_up.sh` |
| Stop the local environment | `./scripts/env_down.sh` |
| Run integration tests | `./scripts/run_integration_tests.sh` |
| Start the frontend alone (optional UI) | `cd frontend && npm run dev` |
| Build the frontend (optional UI) | `cd frontend && npm run build` |

## Project Notes

The root-level `README.md` still carries the older narrative abstract. The documentation in this folder is the more practical reference for current development because it matches the actual controller, worker, and shared-contract layout in the codebase. The frontend is documented here only as a secondary surface.
