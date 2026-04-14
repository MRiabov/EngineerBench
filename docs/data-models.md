# Problemologist-AI - Data Models

**Date:** 2026-03-20

## Runtime Persistence Models

| Model | Location | Purpose |
| -- | -- | -- |
| `Episode` | `controller/persistence/models.py` | Primary workflow record for an engineer or benchmark run |
| `Trace` | `controller/persistence/models.py` | Structured event, tool, reasoning, and feedback record |
| `Asset` | `controller/persistence/models.py` | Stored artifact pointer for renders, MJCF, videos, and files |
| `GenerationSession` | `controller/persistence/models.py` | Benchmark-generation session record |
| `BenchmarkAsset` | `controller/persistence/models.py` | Stored benchmark bundle and metadata |
| `UserSteeringPreference` | `controller/persistence/models.py` | User preference storage for steering and feedback workflows |

## Episode and Trace Fields

| Model | Important Fields |
| -- | -- |
| `Episode` | `id`, `user_session_id`, `task`, `status`, `created_at`, `updated_at`, `skill_git_hash`, `template_versions`, `metadata_vars`, `seed_id`, `seed_dataset`, `seed_match_method`, `generation_kind`, `parent_seed_id`, `todo_list`, `journal`, `plan` |
| `Trace` | `id`, `episode_id`, `user_session_id`, `langfuse_trace_id`, `simulation_run_id`, `review_id`, `trace_type`, `name`, `content`, `metadata_vars`, `feedback_score`, `feedback_comment`, `created_at` |
| `Asset` | `id`, `episode_id`, `user_session_id`, `asset_type`, `s3_path`, `content`, `created_at` |

## Benchmark and Handover Schemas

| Model | Purpose |
| -- | -- |
| `EpisodeMetadata` | Stores lineage, generation kind, worker session ID, custom objectives, and execution metadata |
| `TraceMetadata` | Stores trace-specific metadata and provenance |
| `BenchmarkDefinition` | Defines benchmark objectives, moved object, randomization, and benchmark-owned fixture metadata |
| `AssemblyDefinition` | Defines the engineer-owned assembly, costing inputs, wires, and final assembly structure |
| `ReviewResult` | Structured review decision, reason, and checklist payload |
| `ReviewFrontmatter` | YAML frontmatter for reviewer outputs |
| `PlanRefusalFrontmatter` | Structured refusal artifact for valid coder refusal loops |
| `PlannerSubmissionResult` | Result of planner handoff submission checks |

## Simulation and Workbench Models

| Model | Purpose |
| -- | -- |
| `SimulationResult` | Final simulation output with success flag, summary, failure reason, renders, MJCF, stress summaries, fluid metrics, cost, and weight |
| `SimulationFailure` | Structured failure record for physics and electronics outcomes |
| `StressSummary` | Per-part stress summary for FEM-capable runs |
| `FluidMetricResult` | Per-fluid metric record for fluids objectives |
| `MultiRunResult` | Batched runtime-randomization verification result |
| `WorkbenchResult` | Manufacturability and pricing output for a candidate part or assembly |
| `CostBreakdown` | Cost model details for a part or assembly process |
| `ManufacturingConfig` | Material, process, and benchmark-operation cost model |

## Observability Models

| Model | Purpose |
| -- | -- |
| `TraceEvent` | Structured event broadcast for trace delivery and UI updates |
| `AssetRecord` | Persisted asset metadata used by observability and storage flows |
| `BaseEvent` | Common base schema for structured events |
| `ObservabilityEventType` | Shared event taxonomy for logs, tools, simulation, and review events |
| `SimulationMetadata` | Simulation-specific metadata attached to observability events |
| `ReviewEvidenceStats` | Summary statistics used when evaluating review evidence |

## Worker Protocol Models

| Model | Purpose |
| -- | -- |
| `ReadFileRequest` / `ReadFileResponse` | File read payloads used by worker-light |
| `WriteFileRequest` / `EditFileRequest` | Mutating filesystem requests sent to worker-light |
| `DeleteFileRequest` / `ListFilesRequest` | Workspace file management payloads |
| `ExecuteRequest` / `ExecuteResponse` | Shell execution payloads for the runtime executor |
| `ScriptExecutionRequest` | Wrapper used when the controller routes script tools through the worker boundary |
| `BenchmarkToolRequest` / `BenchmarkToolResponse` | Generic controller-to-worker handoff payloads for validate, simulate, and submit flows |
| `HeavyValidationParams` / `HeavySimulationParams` / `HeavyPreviewParams` / `HeavySubmitParams` | Worker-heavy API request models |
| `HeavyValidationResponse` / `HeavyPreviewResponse` | Worker-heavy response models for validation and preview jobs |
| `PreviewDesignRequest` / `PreviewDesignResponse` | Rendering-oriented request/response pair used by preview flows |
| `ReviewManifest` / `PlanReviewManifest` | Submission manifests for planner and reviewer handoff gates |
| `MediaInspectionResult` / `RenderManifest` | Render metadata returned by media inspection and render bundling |
| `SimulationArtifacts` | Wrapper for simulation outputs and render artifacts |
| `LintRequest` / `LintResponse` | Static analysis request and response models |
| `InspectTopologyRequest` / `InspectTopologyResponse` | Topology inspection request and response models |

## Policy and Configuration Models

| Model | Purpose |
| -- | -- |
| `AgentsConfig` | Global agent policy container for filesystem, render, and execution settings |
| `AgentPolicy` | Per-agent read/write tool and visual inspection policy |
| `FilesystemPermissions` | Read/write path allowlist and denylist structure |
| `VisualInspectionPolicy` | Minimum render inspection rules for specific roles |
| `AgentExecutionPolicy` | Per-agent time, turn, token, and tool-loop limits |
| `LLMPolicyConfig` | LLM limits and compaction policy |
| `RenderPolicyConfig` | Render policy for RGB, depth, and segmentation output |

## Important Enums

| Enum | Meaning |
| -- | -- |
| `AgentName` | Canonical identifiers for planners, coders, reviewers, and subagents |
| `EpisodeStatus` | Lifecycle state for an episode |
| `ReviewDecision` | Allowed review outcomes |
| `FailureReason` | Simulation and validation failure taxonomy |
| `ManufacturingMethod` | Supported production methods such as CNC, 3DP, and injection molding |
| `SimulatorBackendType` | `MUJOCO` or `GENESIS` simulation backend selection |
| `TraceType` | Tool, reasoning, logging, and event trace kinds |
| `ResponseStatus` | HTTP-facing status values used by the APIs |

## Strictness Notes

The core handover and policy models are intentionally strict. Critical schemas use Pydantic models that reject unknown fields, so malformed planner artifacts, review outputs, or policy documents fail closed instead of being accepted loosely.
