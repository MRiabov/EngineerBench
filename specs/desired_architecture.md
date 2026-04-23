# Desired architecture

## Scope summary

- This file is a navigation index, not a long-form architecture spec.
- It tells agents where each architecture concern is documented in `specs/architecture/**`.
- When a task references `@specs/desired_architecture.md`, route to the relevant detailed file(s) below.

This file is the architecture entrypoint. The architecture has been split into focused documents under `specs/architecture/`.

When a task references `@specs/desired_architecture.md`, treat the files below as the source of truth and read the sections relevant to the task.

## Architecture index

### System goals

- [Primary system objectives](./architecture/primary-system-objectives.md): end goals, expected outputs, and product-level purpose of the benchmark and engineer system.

### Agents

- [Agents overview](./architecture/agents/overview.md): high-level map of benchmark generator and engineer graphs.
- [Agent roles](./architecture/agents/roles.md): role responsibilities, required artifacts, and planner/implementer/reviewer behavior.
- [Detailed role sheets](./architecture/agents/roles-detailed/README.md): per-role inputs, outputs, native tools, runtime helpers, and prompt/skill revision checklists. More detailed descriptions of each role live in `./architecture/agents/roles-detailed/`.
- [Agent handovers and contracts](./architecture/agents/handover-contracts.md): file-level handoff contracts and refusal/review routing.
- [Agent harness](./architecture/agents/agent-harness.md): DSPy/LangGraph runtime, debug CLI-provider backend, workspace/prompt/runner contract, and skill-loading policy.
- [Prompt management](./architecture/agents/prompt-management.md): unified prompt-source model, backend appendices, shared template context, and the skills-versus-prompts boundary.
- [Agent skills](./architecture/agents/agent-skill.md): canonical skill-tree source, authoring contract, workspace materialization, and skill-improvement loop.
- [Agent artifacts and filesystem](./architecture/agents/artifacts-and-filesystem.md): artifact surfaces, file ownership, and path-permission policy.
- [Agent artifact contracts](./architecture/agents/agent-artifacts/README.md): file-level acceptance criteria for seeded workspace artifacts, including hard checks, quality bars, and reviewer look-fors.
- [Agent tools](./architecture/agents/tools.md): ReAct-callable tool surface, Python utility functions, checked-in shell-script bridges for custom command-like operations, and reviewer/planner submission gates. Custom command-like behavior is defined by shell scripts, not newly invented ReAct endpoints.
- [Auxiliary agent tools](./architecture/agents/auxiliary-agent-tools.md): secondary wrappers, diagnostics, and experimental helper surfaces that do not belong in the main tool contract.
- [Definitions of success and failure](./architecture/agents/definitions-of-success-and-failure.md): objective AABB rules, runtime randomization, benchmark-side motion exception, and failure taxonomy.

Within the agents tree, `specs/architecture/agents/roles-detailed/` is the source of role details and role acceptance criteria and `specs/architecture/agents/agent-artifacts/` is the contract of files output by agents.

### Runtime and infrastructure

- [Distributed execution](./architecture/distributed-execution.md): controller plus split worker plane, worker APIs, dedicated renderer worker, persistence, Temporal boundary, and backend-routing rules such as fast validation preview versus physics simulation.
- [Inference pipeline](./architecture/inference-pipeline.md): canonical application inference entrypoint, strict stage graph, job-state persistence, resume behavior, and optional seed backfill.
- [CAD and other infrastructure](./architecture/CAD-and-other-infra.md): CAD metadata, schema contracts, and supporting infra assumptions.
- [Rendering](./architecture/rendering.md): render-worker boundary, preview artifacts, bundle contracts, and visual-evidence policy.
- [Simulation](./architecture/simulation.md): physics assumptions, backend split, constraints model, and motion contracts.

### Evaluation and quality gates

- [Eval architecture](./architecture/evals-architecture.md): how eval tiers, pass criteria, terminalization, and fail-closed gates work.
- [Agent reward architecture](./architecture/agents/reward-architecture.md): reward shaping used for downstream training and optimization.
- [Integration test rules](./integration-test-rules.md) and [integration test catalog](./integration-test-list.md): HTTP-only release-gate contracts and canonical `INT-xxx` / `INT-NEG-###` mappings for the system boundary checks.

### Fluids and deformables

- [Fluids, FEM, and stress validation](./architecture/fluids-and-deformables.md): Genesis-backed fluid simulation, deformable-material contracts, stress objectives, smoke-test policy, and WP2-specific artifacts.

### Observability

- [Observability](./architecture/observability.md): event schema, IDs/lineage, metrics, and logging/backups/user-review data.

### Developer instrumentation

- [Developer instrumentation](./devtools.md): local bootstrap, integration orchestration, eval runners, workspace materialization, and contract validators that support developer workflows but are not part of the core architecture tree.

## Document ownership rule

- Add or update architecture requirements in the corresponding `specs/architecture/**` file.
- Keep this file as an index and stable entrypoint, not as a long-form monolith.
