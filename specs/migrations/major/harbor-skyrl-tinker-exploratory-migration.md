---
title: Harbor, SkyRL, and Tinker Exploratory Migration
status: investigation
agents_affected:
  - benchmark_planner
  - benchmark_plan_reviewer
  - benchmark_coder
  - benchmark_reviewer
  - engineer_planner
  - engineer_plan_reviewer
  - engineer_coder
  - engineer_execution_reviewer
  - skill_agent
added_at: '2026-04-16T00:00:00Z'
---

# Harbor, SkyRL, and Tinker Exploratory Migration

<!-- Investigation doc. No behavior change yet. -->

## Purpose

This document defines an exploratory migration from the current custom eval
launcher and CLI-provider debug path to a three-part stack:

1. `Harbor` owns task packaging, agent execution, dataset registration, and
   job orchestration.
2. `SkyRL` owns GRPO and other RL training loops.
3. `Tinker API` owns the training-time sampling and multimodal model
   interaction surface that SkyRL can call into.

The migration is exploratory because the repository already has a working
custom runner, workspace materialization, repo-owned policy checks, and
artifact retention paths. Nothing in this document removes those paths yet.
The goal is to prove parity, reduce duplication, and standardize exportability
before any cutover.

The source of truth for repository-owned policy, file ownership, and handoff
contracts remains the existing architecture docs, especially:

- [Agent harness](../../architecture/agents/agent-harness.md)
- [Agent tools](../../architecture/agents/tools.md)
- [Prompt management](../../architecture/agents/prompt-management.md)
- [Observability](../../architecture/observability.md)
- [Simulation and rendering](../../architecture/simulation-and-rendering.md)

## Why This Exists

The current stack mixes several responsibilities that should eventually be
separated:

1. Eval launch and workspace materialization.
2. Agent runtime orchestration.
3. Trial execution and sandbox selection.
4. Trace export for replay, debugging, SFT, and RL.
5. Training loop execution for GRPO and related methods.

Harbor already provides the outer task/job abstraction we want. Its docs
describe container environments, jobs, datasets, ATIF trajectories, cloud
sandbox scaling, and pre-integrated agents. SkyRL already provides a full
RL training stack with GRPO and a Tinker integration path. Tinker already
provides sampling/training APIs and explicit multimodal input handling.

The migration is not about inventing a new orchestration layer. It is about
choosing the layer boundaries that already exist in those tools and mapping
the repository onto them cleanly.

## Source Evidence

The current exploratory conclusion is grounded in the following official docs:

- Harbor describes tasks as instruction plus container environment plus test
  script, datasets as collections of tasks, and jobs as collections of trials.
- Harbor supports cloud sandboxes such as Daytona, Modal, E2B, and Runloop
  for horizontal scaling.
- Harbor's ATIF format captures complete interaction history, tool calls,
  environment feedback, token metrics, and multi-agent systems.
- Harbor supports popular agents including Codex CLI, Gemini CLI, Claude
  Code, and OpenHands, and it accepts custom agents without modifying Harbor
  source code.
- Harbor advertises integrations with SkyRL for agent optimization.
- SkyRL is a full-stack RL library and documents GRPO as a first-class
  training path.
- SkyRL documents a Tinker integration that can run Tinker API scripts on
  SkyRL with zero code changes.
- Tinker documents a standard sampling client for inference within training
  runs, and its multimodal `ModelInput` accepts `ImageChunk` payloads.
- Tinker's OpenAI-compatible inference is explicitly beta and intended for
  testing and internal use rather than high-throughput public deployment.

## Proposed Boundary

The migration should keep the following ownership split stable:

| Layer | Owner | Notes |
| -- | -- | -- |
| Policy, manifests, handoff files, filesystem permissions | Repo | Never move this into Harbor, SkyRL, or Tinker. |
| Task registry, trial execution, agent container startup | Harbor | Harbor becomes the outer eval harness. |
| Rewarded rollout/training loop | SkyRL | SkyRL becomes the trainer for GRPO and related loops. |
| Sampling/inference during training | Tinker API | Tinker is the model interaction layer, not the source of truth for tasks. |
| Trace promotion and replay artifacts | Repo | Harbor can emit trajectories, but repo-owned storage keeps the durable record. |

Harbor is therefore the execution and registry layer, not the trainer.
SkyRL is the trainer, not the dataset registry.
Tinker is the sampling interface, not the benchmark source of truth.

## Current-State Inventory

The migration mostly touches the current eval and replay stack:

| Current surface | Current role | Likely future role |
| -- | -- | -- |
| `dataset/evals/run_evals.py` | Eval launcher, backend selector, and compatibility entrypoint | Thin Harbor job generator or compatibility wrapper |
| `dataset/evals/materialize_seed_workspace.py` | Seed workspace materialization and local inspection helper | Harbor task builder and environment bootstrap |
| `evals/logic/runner.py` and friends | Eval orchestration, judge wiring, trace capture, and retry logic | Trial ingestion and artifact promotion, with less bespoke orchestration |
| `shared/agent_templates/` and `.agents/skills/` | Workspace inputs and skill-tree source | Still repo-owned inputs to task generation |
| `controller/observability/*` | Persistence and trace promotion | Still repo-owned record-keeping |
| `logs/skill_loop/*` and render / simulation sidecars | Replay and training evidence | Exported data products, ideally standardized |

## Provisional Data Flow

The likely cutover path is:

1. A seeded benchmark or engineering row becomes a Harbor task directory.
2. The task directory contains the instruction, container environment, test
   script, and any static assets required for execution.
3. Harbor runs the task locally first, then on a sandbox provider when scale
   matters.
4. The trial emits a standardized trajectory, with ATIF as the provisional
   cross-tool interchange format.
5. Repo-owned storage keeps the durable trace, review, and artifact bundle.
6. SkyRL consumes the exported data for GRPO or related training loops.
7. Tinker provides the sampling client or compatible API that SkyRL uses for
   training-time model interaction.

## Image Handling

The most important unresolved plumbing question is how multimodal inputs enter
the trial and training path.

The provisional answer is file-backed image assets inside the task bundle or
workspace, with an adapter that turns those files into model-specific image
chunks only at the model boundary.

Why this is the preferred shape:

1. Harbor tasks are already file-based container environments.
2. Tinker explicitly supports `ImageChunk` inside `ModelInput`.
3. File-backed assets keep task replay deterministic and avoid ad hoc base64
   blobs in prompt text.
4. Repo-owned artifact export can keep a checksum, source path, and any resize
   or crop metadata for replay.

This is an inference from the source docs, not an explicit Harbor or Tinker
contract. The migration should prove the image path with a small pilot before
standardizing it.

## Distributed Computing

The second major open question is where distributed execution should live.

The provisional split is:

1. Trial parallelism lives in Harbor jobs and sandboxes.
2. Training parallelism lives in SkyRL's backend layer.
3. Single trials remain isolated and deterministic.
4. Distributed scale changes throughput, not trial semantics.

This means the migration should not mix rollout parallelism and training
parallelism inside the same codepath.

Provisional execution model:

- Local Docker or Docker Compose proves the task and export shape.
- Harbor plus Daytona or another sandbox provider scales trial execution.
- SkyRL plus its training backend scales GRPO and checkpointing.
- Tinker stays on the training-time inference/sampling edge.

## Open Questions

1. Do we standardize on Harbor's ATIF as the canonical export format, or do we
   keep a repo-specific superset and add an ATIF adapter later?
2. Do image assets travel as file paths only, or as file paths plus encoded
   image chunks in the export bundle?
3. Should installed agents or external agents be the default Harbor mode for
   Codex, OpenHands, Gemini CLI, and Claude Code style runs?
4. Should the first distributed cutover use Daytona only, or should we also
   support other Harbor sandbox providers immediately?
5. Should Tinker's OpenAI-compatible inference be treated as a convenience
   path only, or as a supported public interface after the beta limitations
   are validated?
6. What is the smallest dataset slice that can prove the Harbor -> SkyRL ->
   Tinker chain without introducing a new bespoke parser in the training loop?

## Required Work

### Phase 0: Parity probe

- Wrap one current seeded eval row as a Harbor task.
- Run the task locally and confirm that Harbor can reproduce the same outcome
  as the current custom launcher.
- Export the resulting trial data into a standardized trajectory format.
- Verify that the export retains tool calls, environment feedback, reward
  signals, and artifact references.

### Phase 1: Harbor bridge

- Build a Harbor task generator from the repo's seeded eval material.
- Map the current workspace seed into Harbor task files instead of ad hoc
  in-memory setup.
- Keep the current launcher available as compatibility plumbing until the
  Harbor bridge proves stable.
- Prove that Harbor can cover at least the current local eval/debug path
  without losing repo-owned policy enforcement.

### Phase 2: SkyRL bridge

- Convert accepted trajectories into a SkyRL-compatible training source.
- Prove that SkyRL can ingest exported episodes without a bespoke
  per-benchmark parser in the training loop.
- Use GRPO as the first training target because SkyRL documents it as a
  first-class workflow.
- Keep checkpoints, metrics, and replay artifacts separate from the task
  source bundle.

### Phase 3: Tinker adapter

- Use Tinker's sampling client or Tinker-compatible API for training-time
  model interaction.
- Keep the OpenAI-compatible path optional until throughput and stability are
  proven for this use case.
- Keep multimodal payload handling explicit and file-backed at the adapter
  boundary.

### Phase 4: Scale-out

- Add sandbox parallelism only after the single-trial export shape is stable.
- Add distributed training only after the exported trajectories are
  deterministic and replayable.
- Do not allow the distributed layer to change the semantics of a single
  trial.

## Non-Goals

- Do not move repository policy, permissions, or manifest ownership into
  Harbor, SkyRL, or Tinker.
- Do not delete the current custom eval launcher before Harbor parity exists.
- Do not collapse Harbor, SkyRL, and Tinker into one abstraction layer.
- Do not make Tinker the source of truth for datasets or replay artifacts.
- Do not move benchmark planning or engineering planning contracts into the
  training stack.
- Do not treat Tinker's OpenAI-compatible endpoint as a production public
  service until its beta limitations are verified for this workload.
- Do not mix image ingestion policy into prompt text; it belongs in the task
  or export adapter.

## Acceptance Criteria

- One seeded eval row can be expressed as a Harbor task and run locally.
- The same row can be run in a horizontally scaled Harbor environment without
  changing task semantics.
- The run exports a standardized trajectory that is sufficient for replay,
  debugging, SFT, or RL consumption.
- SkyRL can ingest the exported data and perform a small GRPO update.
- The image path for multimodal tasks is deterministic and reproducible.
- The current custom eval launcher can shrink to a compatibility shim or thin
  wrapper only after Harbor parity is proven.

## Exit Criteria

- If Harbor cannot preserve repo-owned policy and artifact boundaries, it
  stays an external experiment, not the new default.
- If SkyRL cannot consume the exported trajectories without bespoke glue, the
  migration stops at export standardization.
- If multimodal input requires ad hoc base64 or prompt hacks, the migration is
  not ready for cutover.
- If distributed execution changes single-trial behavior, the distributed
  layer is too early.

## Notes For Follow-Up

- If this migration becomes active work, add a pilot dataset row first and do
  not start with the widest benchmark surface.
- If the repo later standardizes one trajectory format for both replay and
  training, ATIF is the strongest current candidate because it already covers
  tool calls, environment feedback, metrics, and multi-agent traces.
- If Harbor proves a better export shape than ATIF for this repo, document the
  exact mismatch instead of allowing a silent converter chain to grow.
