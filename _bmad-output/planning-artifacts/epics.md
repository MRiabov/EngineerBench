---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
  - specs/desired_architecture.md
  - specs/business-usecase.md
  - specs/dataset-generation.md
  - specs/frontend-specs.md
  - specs/integration-tests.md
  - specs/todos.md
  - specs/architecture/primary-system-objectives.md
  - specs/architecture/agents/overview.md
  - specs/architecture/agents/roles.md
  - specs/architecture/agents/handover-contracts.md
  - specs/architecture/agents/artifacts-and-filesystem.md
  - specs/architecture/agents/tools.md
  - specs/architecture/agent/debug-codex-agent.md
  - specs/architecture/distributed-execution.md
  - specs/architecture/CAD-and-other-infra.md
  - specs/architecture/evals-and-gates.md
  - specs/architecture/simulation-and-dod.md
  - specs/architecture/observability.md
  - specs/architecture/fluids-and-deformables.md
  - specs/architecture/electronics-and-electromechanics.md
  - specs/architecture/workbenches.md
  - specs/architecture/auxillary/simulation-optimization-attempts.md
  - specs/architecture/dependency-research/dspy-react.md
  - specs/architecture/spec-reviews/round-1.md
  - specs/plan-style-traits.md
---

# Problemologist-AI - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for Problemologist-AI, decomposing the requirements from the PRD, architecture, and supporting specs into implementable stories.

The roadmap now spans 25 epics.

## Requirements Inventory

### Functional Requirements

FR1: Human engineers can define a benchmark as a solution verification setup for a bounded engineering problem.
FR2: Human engineers can set the benchmark goals, forbidden zones, build zone, allowed interactions, and randomization.
FR3: The system can represent benchmark-owned fixtures and benchmark-owned electronics as read-only context unless interaction is explicitly allowed.
FR4: The system can represent allowed attachment and drilling points and explicit benchmark fixture motion contracts in the benchmark setup.
FR5: The system can validate that a benchmark is solvable and reject ambiguous, impossible, or incomplete setups.
FR6: The system can pass benchmark setup artifacts into the solution workflow.
FR7: Human engineers can receive verified design solutions to a benchmark.
FR8: Human engineers can revise a failed solution and try again against the same benchmark.
FR9: The system can support benchmark-definition and solution workflows as separate but connected episode types.
FR10: The system can preserve handoff artifacts between benchmark setup and solution work.
FR11: The system can support reasoned accept/reject decisions for benchmark and solution outputs.
FR12: Human engineers can choose rigid-body preview simulation or higher-fidelity FEM when needed.
FR13: The system can require circuit validity before electromechanical simulation.
FR14: The system can support fluids, deformables, and stress-aware validation when selected.
FR15: The system can preserve simulation and render evidence for later inspection.
FR16: Users can configure the prices used for costing.
FR17: The system can evaluate whether a solution is manufacturable at the requested production volume.
FR18: The system can evaluate setup cost and variable cost separately.
FR19: The system can evaluate weight, size, and form-factor constraints together.
FR20: The system can compare manufacturing options across quantities and choose the appropriate one.
FR21: The system can include COTS parts in cost and manufacturability evaluation.
FR22: The system can identify unnecessary or unjustified degrees of freedom in a solution.
FR23: The system can prefer the valid candidate with fewer unnecessary degrees of freedom, actuators, and parts when multiple solutions satisfy the benchmark.
FR24: The system can flag over-actuated solutions and solutions with unnecessary degrees of freedom during review.
FR25: The system can persist complete episode traces, artifacts, and lineage.
FR26: The system can export solved episodes and benchmarks as training-ready dataset rows.
FR27: Researchers and companies can use completed episodes for training or RL.
FR28: Dataset operators can exclude episodes that fail schema validity, completeness, or lineage integrity checks.
FR29: Dataset operators can manage coverage by seed and problem family.
FR30: The system can generate repeatable episode variants from different seeds.
FR31: The system can expose logs, traces, and terminal reasons for each episode.
FR32: Maintainers can reproduce and diagnose failed episodes from persisted artifacts and traces.
FR33: The system can surface explicit fallback behavior and failure classification.
FR34: The system can compare executed runtime paths against the documented supported feature set and flag mismatches as validation failures.
FR35: The system can keep failed episodes replayable from persisted artifacts and traces.
FR36: The system can accept corrective steering prompts during an active run with attached structured CAD, code, file, or media context.
FR37: The system can let users switch CAD selection mode between faces, parts/bodies, and subassemblies, and preserve the selected entity in the prompt payload.
FR38: The system can preserve steering context, selection metadata, and resulting edits in traces and replay artifacts.
FR39: The system can generate preview-ready image, video, netlist, and schematic artifacts for simulation-family runs and expose them to authorized viewers.
FR40: The system can render advanced simulation artifacts in-browser with interactive inspection and in-scene selections for steering.
FR41: Users can upload CAD models as input objects or benchmark environments and validate imported motion and constraint metadata from the uploaded asset set.
FR42: Users can inspect imported CAD constraints, mates, and joints in the visualization surface and toggle their visibility.
FR43: The system can expose continuous, smooth numerical reward signals from the environment for reinforcement learning and skill iteration.
FR44: The system can support trainer-agnostic online GRPO rollouts against live episodes using streaming observations, actions, rewards, and terminal signals.

### NonFunctional Requirements

NFR1: The benchmark-verification and solution-revision loop shall complete in under 15 minutes at the 95th percentile for the standard Phase 1 benchmark suite.
NFR2: Static preview artifacts shall be available for 100% of benchmarks that produce render evidence before final proof artifacts are accepted.
NFR3: Benchmarks that do not declare a physics mode shall not trigger heavy physics, FEM, or fluid evaluation.
NFR4: Planning and review requests shall return an initial response within 2 seconds at the 95th percentile while heavy evaluation is pending.
NFR5: Repeated validation of the same unchanged revision shall produce 0 new heavy evaluations and shall return the previously persisted result or a no-op status.
NFR6: Any request with missing artifacts, invalid schemas, stale manifests, unsupported mechanisms, invalid circuits, or missing review evidence shall end in terminal failure with no success state.
NFR7: Partial output, inferred success, and silent fallback shall never be classified as success.
NFR8: Configuration mismatches, capacity limits, and retry exhaustion shall return deterministic terminal reasons and a retriable/non-retriable classification.
NFR9: 100% of terminal episodes shall include a concrete terminal reason and failure classification.
NFR10: 100% of completed episodes shall be reconstructable from persisted traces, logs, artifacts, and lineage IDs without rerunning the solver.
NFR11: Every user session, episode, simulation run, review, COTS query, and seed record shall have joinable identifiers in persisted records and exports.
NFR12: Every tool call, review decision, media inspection action, and error event shall emit a machine-readable record and remain available for the debugging retention window.
NFR13: Every failed episode shall include a replay bundle that reproduces the failure state in replay mode.
NFR14: Reasoning and tool-call traces shall be retained for the full episode lifetime and remain accessible in replay views.
NFR15: When render evidence exists, the review record shall identify the exact latest-revision media artifact that was inspected.
NFR16: Episode lineage and seed lineage shall persist across benchmark generation and engineering execution for 100% of exported episodes.
NFR17: Every dataset export shall include the source episode ID, revision hash, and artifact hash.
NFR18: Training dataset exports shall exclude integration-test runs and known-corrupted episodes.
NFR19: Handoff artifacts shall validate against the same schema at creation, storage, review, and export time; any schema drift shall reject the episode.
NFR20: Backups shall restore persisted run metadata and artifact references with 100% integrity in periodic restore tests.
NFR21: Untrusted generated code shall not mutate persistent workflow state directly; all state changes shall be mediated by validated artifacts and recorded actions.
NFR22: Concurrent heavy evaluation requests for the same episode shall either start, return a deterministic busy status, or fail with a terminal reason within the request timeout.
NFR23: Benchmark-owned artifacts shall remain read-only during engineering runs, and engineer-owned outputs shall remain separate from benchmark context.
NFR24: 100% of accepted solutions shall include a final proof artifact that is distinct from any preview artifact.
NFR25: Validation, review, and export artifacts shall round-trip through storage and retrieval without loss of required fields or schema drift.

### Additional Requirements

- Controller/worker/Temporal split remains mandatory; generated code executes off the controller in isolated worker processes.
- Planner and reviewer handoffs are strict-schema artifacts with stage-specific manifests, no silent fallback, and fail-closed routing on stale, missing, or invalid artifacts.
- Planner-owned derived values such as cost caps are deterministic outputs of validator tooling, not freeform authoring.
- Benchmark-owned fixtures and motion context are read-only unless the benchmark explicitly declares engineer interaction. Benchmark-side motion may be fixed, partially constrained, motorized, or fully free when the benchmark contract explicitly declares it.
- Benchmark-owned fixtures are validation setup, not engineer-owned solution hardware; they may be fixed, partially constrained, motorized, or fully free when the benchmark contract says so, and they are excluded from engineer manufacturability and pricing gates.
- Benchmark setup must preserve distinct benchmark-owned vs engineer-owned artifact boundaries and hash-based immutability across handoff.
- `/benchmark/validate` uses MuJoCo for static preview by default; Genesis parity is validated through dedicated simulation paths, not preview reruns.
- Static preview must persist RGB, depth, segmentation, and render manifests when enabled.
- Reviewer roles must inspect render media with `inspect_media(...)` when render evidence exists; text-only file listing is insufficient.
- Simulation and validation must emit durable artifacts, events, and lineage; `events.jsonl` is batch transport, while Postgres and Langfuse are query sources.
- Simulation-family epics must emit preview-ready image and video artifacts for each renderable revision, and authorized viewers must be able to display every persisted render artifact in the browser.
- Electronics simulation must additionally persist a netlist artifact and a schematic image alongside the render artifacts.
- Dataset generation must preserve seed, episode, and review lineage, exclude integration-test and corrupted windows, and support replayable exports.
- Electromechanical tasks require explicit circuit validation, power budgets, wire routing, wire tear handling, and electrical evidence surfaces.
- Fluids, deformables, and stress-aware tasks require Genesis-backed final validation and structured stress/fluid artifacts.
- The roadmap expands through manufacturability, gravity, actuators, FEM, fluids, and electronics, with each family split into simulation, benchmark-generation agents, and engineering agents.
- Steering is a late-stage cross-cutting capability over the agents, not a first-milestone feature, and belongs after the gravity baseline is defined.
- Supported workbenches and mechanisms are finite and explicit; unsupported mechanisms fail closed.
- The frontend is an evidence surface for session history, chat/trace inspection, CAD viewer, code viewer, simulation playback, and feedback, not the source of truth.
- Advanced UI inspection and hardening work is deferred until after the MVP and is handled in Epic 26; the MVP UI only needs simple workflow control, inspection, and review actions.
- Live steering must preserve selection metadata for faces, parts, bodies, subassemblies, code ranges, file references, and media references in traces and prompt payloads.
- Codex debug mode uses workspace-relative paths, a local submission helper, and the same fail-closed workspace contract as runtime.
- Local CLI agent flexibility is an optional, non-exclusive development and eval-debug path; supported CLI backends may supply benchmark and engineering decisions only when they satisfy the same workspace, prompt, artifact, and fail-closed validation contracts as the controller-backed runtime.
- OpenAPI generation, strict schemas, and integration tests remain part of the repository contract and must stay in sync with controller behavior.
- No silent fallback or degraded-success paths: any fallback must be explicit, traceable, and machine-readable.

### UX Design Requirements

- No separate UX design specification was provided in the planning artifacts.
- Frontend requirements from `specs/frontend-specs.md` were treated as cross-check requirements and are captured in the additional requirements set.

### FR Coverage Map

FR1: Epic 1 - Human engineers can define a benchmark as a solution verification setup for a bounded engineering problem
FR2: Epic 1 - Human engineers can set the benchmark goals, forbidden zones, build zone, allowed interactions, and randomization
FR3: Epic 1 - Benchmark-owned fixtures remain read-only unless interaction is explicit
FR4: Epic 12 - Allowed attachment, drilling points, and explicit motion contracts are declared in the benchmark setup
FR5: Epic 1 - Benchmark solvability is validated and ambiguous or impossible setups are rejected
FR6: Epic 1 - Benchmark setup artifacts are passed into the solution workflow
FR7: Epic 2 - Human engineers can receive verified design solutions to a benchmark
FR8: Epic 2 - Human engineers can revise failed solutions against the same benchmark
FR9: Epic 2 - Benchmark and solution workflows remain separate but connected
FR10: Epic 2 - Handoff artifacts are preserved between benchmark setup and solution work
FR11: Epic 2 - Review decisions support accept/reject of benchmark and solution outputs
FR12: Epic 8 / Epic 14 / Epic 17 - Human engineers can choose rigid-body preview simulation or higher-fidelity FEM when needed
FR13: Epic 23 - Circuit validity is required before electromechanical simulation
FR14: Epic 17 / Epic 20 - Fluids, deformables, and stress-aware validation are supported when selected
FR15: Epic 4 - Simulation and render evidence is preserved for later inspection
FR16: Epic 11 - Users can configure the prices used for costing
FR17: Epic 11 - The system can evaluate manufacturability at the requested production volume
FR18: Epic 11 - The system can separate setup cost from variable cost
FR19: Epic 11 - The system can evaluate weight, size, and form-factor constraints together
FR20: Epic 11 - The system can compare manufacturing options across quantities
FR21: Epic 11 - The system can include COTS parts in cost and manufacturability evaluation
FR22: Epic 13 - The system can identify unnecessary or unjustified degrees of freedom
FR23: Epic 13 - The system can prefer the valid candidate with fewer unnecessary degrees of freedom, actuators, and parts
FR24: Epic 13 - The system can flag over-actuated solutions during review
FR25: Epic 4 - Complete episode traces, artifacts, and lineage are persisted
FR26: Epic 4 - Solved episodes and benchmarks can be exported as training-ready dataset rows
FR27: Epic 4 - Completed episodes can be used for training or RL
FR28: Epic 4 - Episodes that fail schema, completeness, or lineage checks can be excluded
FR29: Epic 4 - Coverage by seed and problem family can be managed
FR30: Epic 4 - Repeatable episode variants can be generated from different seeds
FR31: Epic 4 - Logs, traces, and terminal reasons are exposed for each episode
FR32: Epic 4 - Failed episodes can be reproduced and diagnosed from persisted artifacts and traces
FR33: Epic 4 - Explicit fallback behavior and failure classification are surfaced
FR34: Epic 4 - Runtime paths can be compared against the documented supported feature set and mismatches flagged
FR35: Epic 4 - Failed episodes remain replayable from persisted artifacts and traces
FR36: Epic 27 - Corrective steering prompts can be attached with CAD, code, file, or media context
FR37: Epic 27 - CAD selection mode can switch between faces, parts/bodies, and subassemblies while preserving selection
FR38: Epic 27 - Steering context, selection metadata, and resulting edits are preserved in traces and replay artifacts
FR39: Epic 8 / Epic 14 / Epic 17 / Epic 20 / Epic 23 - Simulation-family epics emit preview-ready artifacts that authorized viewers can inspect in-browser
FR40: Epic 26 - Advanced visualization renders FEM, fluids, and electronics artifacts in-browser and supports in-scene steering selections
FR41: Epic 29 - Users can upload CAD models as input objects or benchmark environments and validate imported motion and constraint metadata from the uploaded asset set
FR42: Epic 26 - Users can inspect imported CAD constraints, mates, and joints in the visualization surface and toggle their visibility
FR43: Epic 4 - The system can expose continuous, smooth numerical reward signals from the environment for reinforcement learning and skill iteration
FR44: Epic 4 - The system can support trainer-agnostic online GRPO rollouts against live episodes using streaming observations, actions, rewards, and terminal signals

## Epic List

Epics 1, 2, 4, and 6-10 form the platform and gravity baseline. Epics 11-13 cover manufacturability. Epic 26 is deferred UI, visualization, and demo work placed after the electronics family. The remaining epics are capability-family epics. The baseline family is simple rigid-body simulation with gravity enabled, using MuJoCo-style simulators or equivalents, and steering is intentionally late-stage.

### Epic 1: Benchmark Creation & Validation

Human operators can author benchmark packages, preview the CAD model and simulation evidence for those packages, and the system rejects invalid benchmark definitions with explicit, deterministic reasons before acceptance. The baseline simple rigid-body simulation contract with gravity enabled is included here as a validation dependency, not as a separate epic.

### Epic 2: Human Solution Workflow

Human engineers can take an approved benchmark, run candidate solutions against it, inspect CAD, render, and simulation evidence, and iterate after failure without rebuilding the benchmark.

### Epic 4: Dataset Export & Replay

Researchers and companies can export completed runs as inspectable, reproducible dataset rows with traces, artifacts, lineage, and replayable failures.

The benchmark and engineering stories below target the MVP difficulty band: up to about 5 meaningful, realistic parts. More complex cases belong to later complexity levels and later epics.

### Epic 6: Gravity: Benchmarks (Fixed Engineer Parts)

Benchmark generator agents can reliably ship simple rigid-body benchmark packages with gravity enabled that a human operator can use without cleanup, and the packages are explicit enough for an engineering agent to solve them without modifying them. Invalid or unsupported benchmark requests are rejected before generation starts, and invalid artifacts or handoffs are rejected during the pipeline instead of being silently adapted. In this rollout phase, engineer-created parts are fixed in the air during solution validation.

The Epic 6 reliability target is end-to-end: given a realistic benchmark request, Codex-backed benchmark generation should produce a valid benchmark package that a human operator can use without manual cleanup in most cases, with the evaluation set tracking that rate explicitly.

### Epic 7: Gravity: Engineering (Fixed Engineer Parts)

Engineering agents can solve the simple rigid-body benchmark packages produced by Epic 6 with verified solutions. The engineering flow uses the benchmark package as provided; it does not edit the benchmark package, and if the package is unsuitable the engineering run fails. A human can rerun benchmark generation separately. In this rollout phase, engineer-created parts remain fixed in the air.

### Epic 8: Actuators: Simulation (Fixed Engineer Parts)

Upgrade simulation fidelity for powered motion, actuators, and motion limits so that actuator benchmark packages can be validated for human review and solved by engineering agents against a concrete powered-motion contract, and emit preview video and still-frame artifacts for inspection. In this rollout phase, engineer-created parts are fixed in the air.

### Epic 9: Gravity: Benchmarks (Movable Engineer Parts)

Benchmark generator agents can reliably ship simple rigid-body benchmark packages with gravity enabled that a human operator can use without cleanup, and the packages are explicit enough for an engineering agent to solve them without modifying them. Invalid or unsupported benchmark requests are rejected before generation starts, and invalid artifacts or handoffs are rejected during the pipeline instead of being silently adapted. In this rollout phase, engineer-created parts can move in simulation.

### Epic 10: Gravity: Engineering (Movable Engineer Parts)

Engineering agents can solve the simple rigid-body benchmark packages produced by Epic 9 with verified solutions. The engineering flow uses the benchmark package as provided; it does not edit the benchmark package, and if the package is unsuitable the engineering run fails. A human can rerun benchmark generation separately. In this rollout phase, engineer-created parts can move in simulation.

### Epic 11: Manufacturability: Simulation

Human operators can validate solutions against cost, weight, form factor, manufacturability, and COTS data using real manufacturing data.

### Epic 12: Manufacturability: Benchmarks

Human operators can represent allowed attachment and drilling points in benchmark setups so CAD and manufacturability review can validate how the design may be connected or modified.

### Epic 13: Manufacturability: Engineering

Human operators can identify unnecessary or unjustified degrees of freedom and prefer the simpler valid design during review.

### Epic 14: Actuators: Simulation (Movable Engineer Parts)

Upgrade simulation fidelity for powered motion, actuators, and motion limits so that actuator benchmark packages can be validated for human review and solved by engineering agents against a concrete powered-motion contract, and emit preview video and still-frame artifacts for inspection. In this rollout phase, engineer-created parts can move in simulation.

### Epic 15: Actuators: Benchmarks

Benchmark generator agents can ship actuator benchmark packages that a human operator can use without cleanup, and the packages describe powered motion explicitly enough for an engineering agent to solve them without modifying them.

### Epic 16: Actuators: Engineering

Engineering agents can solve the actuator benchmark packages produced by Epic 15 without modifying the benchmark package, with verified solutions that respect powered motion limits and remain stable under review.

### Epic 17: FEM: Simulation

Upgrade simulation fidelity for deformables, stress, and breakage so that FEM benchmark packages can be validated for human review and solved by engineering agents against a concrete stress-aware contract, and emit mesh preview images and stress/strain field artifacts for inspection.

### Epic 18: FEM: Benchmarks

Benchmark generator agents can ship FEM benchmark packages that a human operator can use without cleanup, and the packages describe deformable behavior explicitly enough for an engineering agent to solve them without modifying them.

### Epic 19: FEM: Engineering

Engineering agents can solve the FEM benchmark packages produced by Epic 18 without modifying the benchmark package, with verified, stress-aware solutions that remain stable under review and produce acceptable structural outcomes.

### Epic 20: Fluids: Simulation

Upgrade simulation fidelity for fluid containment, flow, and fluid-solid interaction so that fluid benchmark packages can be validated for human review and solved by engineering agents against a concrete containment and flow contract, and emit preview video and still-frame artifacts for inspection.

### Epic 21: Fluids: Benchmarks

Benchmark generator agents can ship fluid benchmark packages that a human operator can use without cleanup, and the packages describe fluid behavior explicitly enough for an engineering agent to solve them without modifying them.

### Epic 22: Fluids: Engineering

Engineering agents can solve the fluid benchmark packages produced by Epic 21 without modifying the benchmark package, with verified solutions that respect containment, flow, and stability requirements.

### Epic 23: Electronics: Simulation

Upgrade simulation fidelity for circuit validity, wire routing, and power-gated actuation so that electromechanical benchmark packages can be validated for human review and solved by engineering agents against a concrete electrical contract, and emit a netlist, schematic image, and preview artifacts for inspection.

### Epic 24: Electronics: Benchmarks

Benchmark generator agents can ship electromechanical benchmark packages that a human operator can use without cleanup, and the packages describe powered behavior explicitly enough for an engineering agent to solve them without modifying them.

### Epic 25: Electronics: Engineering

Engineering agents can solve the electromechanical benchmark packages produced by Epic 24 without modifying the benchmark package, with verified circuit, wiring, and motion behavior.

### Epic 26: UI, Visualization, and Demo

Human operators can inspect runs, visualize CAD and simulation evidence, create benchmark drafts, accept or reject simple plan artifacts, resume sessions, and present the system through a browser UI. This work is deferred until after the electronics family and remains outside the early MVP path.

### Epic 27: Steering & Control

Human operators can steer the active benchmark generator and engineering agents with selected CAD/code context and targeted corrections. This is the active control surface, not the read-only evidence surface.

### Epic 28: Market Fit & Hardening

Define the first target market and harden the product around that market so that the release has a clear customer profile, quality bar, and scope boundary.

### Epic 29: Uploaded CAD Models

Users can upload CAD models as input objects or benchmark environments and validate imported motion and constraint metadata so that native CAD inputs can enter the product without first being manually rebuilt into a benchmark.

## Epic 1: Benchmark Creation & Validation

Human operators can author benchmark packages, and the system rejects invalid benchmark definitions with explicit, deterministic reasons before acceptance. The baseline simple rigid-body simulation contract with gravity enabled is included here as a validation dependency, not as a separate epic.

### Story 1.1: Benchmark Geometry and Objectives

As a human operator, I want to define benchmark goals, forbid zones, build zones, and runtime randomization so that the benchmark has a clear, bounded, solvable contract.

**Acceptance Criteria:**

**Given** valid geometry inputs
**When** the benchmark is validated
**Then** the system accepts only non-intersecting, in-bounds objective geometry
**And** the benchmark package preserves the declared goal, forbid, and build zones

**Given** runtime randomization values
**When** the benchmark is saved
**Then** those ranges are persisted and visible in the benchmark package

### Story 1.2: Benchmark-Owned Fixtures and Interaction Rules

As a human operator, I want to declare benchmark-owned fixtures with explicit interaction permissions so that benchmark context stays read-only for an engineer solving the benchmark unless interaction is explicitly allowed.

**Acceptance Criteria:**

**Given** benchmark-owned fixtures
**When** they are declared
**Then** they remain read-only for the engineer by default

**Given** a fixture marked as interactable
**When** the benchmark is validated
**Then** the interaction surface is explicit and machine-readable

### Story 1.3: Solvability Validation and Fail-Closed Rejection

As a human operator, I want the system to validate solvability and reject invalid setups so that ambiguous, impossible, or unsupported benchmark definitions never enter the solution workflow.

**Acceptance Criteria:**

**Given** an invalid benchmark candidate
**When** validation runs
**Then** the system fails closed with an explicit reason code

**Given** obstructed goals, impossible geometry, or unsupported motion
**When** the preview or validation path runs
**Then** the benchmark is rejected rather than partially accepted

**Given** a benchmark that is technically valid but still not solvable logically
**When** the validation tool evaluates it
**Then** the tool rejects it explicitly

### Story 1.4: Handoff Artifacts, Versioning, and Reproducibility

As a human operator, I want validated benchmark artifacts, CAD previews, and preview evidence persisted so that downstream solution workflows can consume a stable, inspectable benchmark package, and I want to have no questions about reproducibility of the experiment.

**Acceptance Criteria:**

**Given** a valid benchmark
**When** it is submitted
**Then** the required handoff artifacts, environment version, and manifest are persisted for the latest revision only

**Given** render evidence exists
**When** the benchmark is reviewed
**Then** the latest-revision preview artifacts are available for inspection and traceable in the episode record

**Given** preview artifacts exist
**When** I inspect the benchmark package
**Then** I can view the rendered CAD model and the simulation preview for the latest revision

**Given** the persisted benchmark package
**When** it is reloaded later
**Then** the environment version and artifact hashes make the experiment reproducible

### Story 1.5: Review Colleague Benchmarks for Solvability

As a human operator, I want to review a colleague's benchmark for solvability so that I can reject technically valid but logically unsolvable problems before they are handed to engineering.

**Acceptance Criteria:**

**Given** a benchmark that passes schema and geometry checks but is logically unsolvable
**When** I review it
**Then** I can reject it explicitly

**Given** a benchmark that is solvable
**When** I review it
**Then** I can approve it for downstream solution work

**Given** a benchmark draft with preview artifacts
**When** I review it
**Then** I can inspect the rendered CAD model and simulation preview before deciding whether to approve it for downstream solution work

## Epic 2: Human Solution Workflow

Human engineers can take an approved benchmark, work a solution against it, inspect CAD, render, simulation and pass/fail evidence, and iterate after failure. Human engineers can also review a colleague's solution for physical robustness under runtime jitter and reject flaky results.

### Story 2.1: Start Solution Episode from Approved Benchmark

As a human engineer, I want to start solution work from an approved benchmark so that I can solve against the same benchmark context that was validated.

**Acceptance Criteria:**

**Given** an approved benchmark revision
**When** solution work starts
**Then** the benchmark package and environment version are carried forward unchanged into the solution workspace

**Given** a simple rigid-body benchmark
**When** solution work starts
**Then** the solution is evaluated in physically correct rigid-body simulation and the outcome follows physical reality

**Given** an unapproved or stale benchmark revision
**When** I start solution work
**Then** the system blocks the episode with an explicit failure reason

### Story 2.2: Inspect Solution Evidence and Terminal Outcome

As a human engineer, I want to inspect CAD previews, simulation results, render evidence, and terminal reasons so that I know why a candidate solution passed or failed.

**Acceptance Criteria:**

**Given** a completed attempt
**When** I inspect the run
**Then** the system exposes the latest validation or simulation evidence and the terminal reason

**Given** render or video evidence exists
**When** I inspect the run
**Then** the latest-revision media is available and traceable

**Given** preview artifacts exist
**When** I inspect the run
**Then** I can view the rendered CAD model and the simulation preview for the latest revision

**Given** the attempt failed
**When** I inspect the outcome
**Then** the failure classification is explicit and not implied

### Story 2.3: Revise and Retry Against the Same Benchmark

As a human engineer, I want to revise a failed solution and try again against the same benchmark so that I can converge on a passing design without redefining the problem.

**Acceptance Criteria:**

**Given** a failed solution
**When** I create a revision
**Then** the benchmark definition and environment version remain unchanged

**Given** a revised solution is submitted
**When** validation runs again
**Then** the new attempt is evaluated against the same benchmark contract

**Given** multiple solution revisions exist
**When** I inspect the episode
**Then** I can compare the outcomes of the revisions against the same benchmark package

### Story 2.4: Review Peer Solutions for Stability

As a human engineer, I want to review a colleague's solution under runtime jitter and inspect the CAD and simulation preview so that I can reject solutions that only work in a lucky run.

**Acceptance Criteria:**

**Given** a solution has jittered evaluation results
**When** I review it
**Then** the system exposes pass/fail across the required variations

**Given** the solution is flaky or unstable
**When** I review it
**Then** I can reject it with an explicit reason

**Given** the solution is robust across the required jitter cases
**When** I review it
**Then** I can approve it for the next workflow stage

**Given** a solution under review
**When** I inspect it
**Then** the rendered CAD model and simulation preview are available alongside the jittered pass/fail results

## Epic 4: Dataset Export & Replay

Researchers and companies can export completed runs as inspectable, reproducible dataset rows with traces, artifacts, lineage, continuous reward traces, live rollout signals for online GRPO, immutable run bundles, and replayable failures. Invalid or corrupted episodes are excluded at export time.

### Story 4.1: Persist Immutable Run and Release Bundles

As a human operator, I want validated benchmark artifacts, preview evidence, and immutable run or release manifests persisted so that downstream solution workflows can consume a stable, inspectable benchmark package and I have no questions about reproducibility of the experiment.

**Acceptance Criteria:**

**Given** a valid benchmark or official evaluation run
**When** it is persisted
**Then** the system stores the required manifest bundle, environment version, and revision identifiers for the latest revision only

**Given** the persisted bundle
**When** I inspect it later
**Then** I can trace the benchmark revision, solution revision, environment version, joinable session and episode identifiers, and preview evidence from the same bundle without relying on undocumented runtime state

**Given** render evidence exists
**When** the benchmark or run is archived
**Then** the latest-revision preview artifacts remain linked to the bundle and remain inspectable

### Story 4.2: Export Training-Ready Dataset Rows

As a dataset operator, I want completed benchmark and solution episodes exported as training-ready dataset rows so that I can use them for supervised training or RL.

**Acceptance Criteria:**

**Given** a completed episode that passes schema, completeness, and lineage checks
**When** export runs
**Then** the row includes the source episode ID, revision hash, artifact hash, seed metadata, and required media or manifest artifacts

**Given** a row missing required metadata or with invalid lineage
**When** export runs
**Then** the row is excluded

**Given** a completed benchmark or solution row
**When** I inspect it later
**Then** I can recover the source benchmark, the solution, the review artifacts, and the joinable session and episode identifiers from persisted metadata alone

### Story 4.3: Replay Failed Episodes and Surface Deterministic Failures

As a maintainer, I want failed episodes to remain replayable from persisted artifacts and traces so that I can reproduce and diagnose failures without rerunning the original solver.

**Acceptance Criteria:**

**Given** a failed episode
**When** replay mode loads it
**Then** the replay bundle reconstructs the failure state using persisted artifacts only

**Given** a terminal episode
**When** I inspect it
**Then** the terminal reason, failure classification, and explicit fallback or unsupported-feature mismatch are present

**Given** missing artifacts, stale manifests, unsupported mechanisms, or missing review evidence
**When** replay runs
**Then** it fails closed with a concrete reason rather than a success state

### Story 4.4: Curate Seed Coverage and Exclude Corrupted Data

As a dataset operator, I want to manage coverage by seed and problem family so that the exported dataset stays balanced, representative, and free of known-corrupted rows.

**Acceptance Criteria:**

**Given** repeated seed variants or underrepresented families
**When** export prioritization runs
**Then** seed coverage is tracked through `seed_id`, `seed_dataset`, `seed_match_method`, `generation_kind`, and `parent_seed_id`

**Given** integration-test runs or known-corrupted windows
**When** export runs
**Then** those rows are excluded

**Given** different seeds for the same benchmark family
**When** I inspect the export
**Then** the dataset retains the seed lineage needed to reproduce the variation

### Story 4.5: Support Live Online GRPO Rollouts and Reward Traces

As a researcher, I want role-specific episodes to expose dense numerical reward traces and live rollout signals so that I can train models with online GRPO or skill iteration.

**Acceptance Criteria:**

**Given** a running role-specific episode
**When** the agent advances through the environment
**Then** the system emits numeric reward values that vary with episode state rather than only a terminal pass/fail label
**And** the environment exposes streaming observations, actions, rewards, and terminal signals suitable for a live GRPO trainer

**Given** the same benchmark revision, solution revision, and seed
**When** the episode is replayed
**Then** the reward trace is reproduced deterministically from persisted artifacts

**Given** a completed episode
**When** training-ready export runs
**Then** the dataset row includes the reward trace or a durable reference to it alongside the other persisted artifacts

**Given** a researcher inspecting an episode
**When** they review reward output
**Then** they can read the per-step reward progression needed for reinforcement learning, online GRPO, or skill iteration

## Epic 6: Gravity: Benchmarks (Fixed Engineer Parts)

Benchmark generator agents can reliably produce valid simple rigid-body benchmarks with gravity enabled that human engineers can work against, and the benchmark family stays within rigid-body mechanics and gravity. In this rollout phase, engineer-created parts are fixed in the air during solution validation.

### Story 6.1: Generate Simple Rigid-Body Benchmarks

As a human operator, I want benchmark generator agents to produce simple rigid-body benchmark candidates so that the benchmark family stays within rigid-body mechanics with gravity enabled.

**Acceptance Criteria:**

**Given** a simple rigid-body benchmark seed or prompt
**When** generation runs
**Then** the candidate remains within the simple rigid-body, gravity-enabled scope and does not introduce actuators, FEM, or fluids

**Given** an unsupported mechanism or modality
**When** generation runs
**Then** the candidate is rejected rather than silently adapted

**Given** a generated benchmark candidate
**When** it is reviewed
**Then** its objective, zones, and motion assumptions are explicit enough for a human engineer to work against it

**Given** this rollout phase
**When** the benchmark is used for solution work
**Then** engineer-created parts are fixed in the air during validation

### Story 6.2: Produce a Representative Simple Rigid-Body Validation Set

As a human operator, I want a sufficiently broad simple rigid-body validation set so that engineers can work against meaningful variations rather than a single toy case.

**Acceptance Criteria:**

**Given** the simple rigid-body benchmark family
**When** seeds are generated
**Then** the set includes multiple variants across object shape, placement, size, and objective arrangement

**Given** the validation set
**When** I inspect it
**Then** it is broad enough to exercise the benchmark generator against repeatable simple rigid-body cases

**Given** a family member is duplicated too closely
**When** the set is curated
**Then** the duplicate is excluded or marked as redundant

### Story 6.3: Refine Simple Rigid-Body Benchmark Quality

As a human operator, I want benchmark generator output to improve based on reviewer feedback so that generated simple rigid-body benchmarks remain solvable, unambiguous, and suitable for engineering intake.

**Acceptance Criteria:**

**Given** reviewer feedback on a simple rigid-body benchmark
**When** the benchmark is regenerated
**Then** the next revision preserves the solvable contract and resolves the flagged issue

**Given** a technically valid but poor simple rigid-body benchmark
**When** review runs
**Then** it can be rejected as unsuitable for engineering intake

**Given** repeated simple rigid-body benchmark generations
**When** I inspect the run set
**Then** rejected examples are preserved for debugging and dataset analysis

### Story 6.4: Reliable Simple Rigid-Body Benchmark Output and Reviews

As a human operator, I want simple rigid-body benchmark output and benchmark reviews to be reliably good and explainable so that I can trust the AI without manually correcting most attempts.

**Acceptance Criteria:**

**Given** 10 simple rigid-body benchmark generation attempts
**When** I review the outputs
**Then** at least 8 of the benchmarks are usable by a human operator without me correcting the benchmark definition

**Given** an AI-generated simple rigid-body benchmark review
**When** I inspect it
**Then** the review explains the problem or acceptance reason clearly enough for a human to follow

**Given** a simple rigid-body benchmark review is unclear
**When** I read it
**Then** I can reject it as insufficiently explainable

## Epic 7: Gravity: Engineering (Fixed Engineer Parts)

Engineering agents can solve simple rigid-body benchmarks with verified solutions that behave correctly in rigid-body simulation with gravity enabled, and engineer-created parts remain fixed in the air during this rollout phase.

### Story 7.1: Solve Simple Rigid-Body Benchmarks

As a human operator, I want engineering agents to solve simple rigid-body benchmarks so that the system can produce a working solution for a rigid-body problem with gravity enabled.

**Acceptance Criteria:**

**Given** an approved simple rigid-body benchmark
**When** engineering runs
**Then** the agent produces a candidate solution against the same benchmark contract

**Given** a simple rigid-body solution attempt
**When** it is evaluated
**Then** the result is judged in physically correct simple rigid-body simulation with gravity enabled, and engineer-created parts remain fixed in the air

**Given** the candidate solution fails
**When** the run terminates
**Then** the failure reason is explicit and the agent can continue from the same benchmark

### Story 7.2: Verify Physics-Correct Simple Rigid-Body Solutions

As a human operator, I want simple rigid-body solutions to be verified against physical reality so that a passing solution is not only syntactically valid but physically plausible.

**Acceptance Criteria:**

**Given** a passing simple rigid-body solution
**When** the solution is reviewed
**Then** it respects rigid-body mechanics with gravity enabled, and the benchmark-defined zones and objectives

**Given** a solution that only works due to simulation artifacts or unstable behavior
**When** it is checked
**Then** it is rejected as flaky or physically implausible

**Given** a solution that passes under the required conditions
**When** validation completes
**Then** the solution is accepted as a verified simple rigid-body result

### Story 7.3: Persist Final Proof for Simple Rigid-Body Solutions

As a human operator, I want the final simple rigid-body solution proof and evidence persisted so that the solution can be inspected, exported, and reproduced later.

**Acceptance Criteria:**

**Given** an accepted simple rigid-body solution
**When** it is finalized
**Then** the final proof artifact is distinct from any preview artifact and is persisted with the episode

**Given** the solution evidence exists
**When** I inspect the episode later
**Then** I can review the exact render, simulation, and terminal metadata used to accept the run

**Given** the simple rigid-body solution is revisited later
**When** the bundle is reloaded
**Then** the persisted artifacts are sufficient to reproduce the accepted result without rerunning the solver

### Story 7.4: Reliable Simple Rigid-Body Solution Output and Reviews

As a human operator, I want simple rigid-body solution output and solution reviews to be reliably good and explainable so that I can trust the AI without manually correcting most attempts.

**Acceptance Criteria:**

**Given** 10 simple rigid-body solution attempts
**When** I review the outputs
**Then** at least 8 of the solutions are valid without me correcting the solution

**Given** an AI-generated simple rigid-body solution review
**When** I inspect it
**Then** the review explains the pass or fail decision clearly enough for a human to follow

**Given** a simple rigid-body solution review is unclear
**When** I read it
**Then** I can reject it as insufficiently explainable

## Epic 8: Actuators: Simulation (Fixed Engineer Parts)

Upgrade simulation fidelity for powered motion, actuators, and motion limits so that actuator-enabled benchmarks behave physically consistently, with engineer-created parts fixed in the air during this rollout phase.

### Story 8.1: Model Actuator-Driven Motion

As a human operator, I want to define actuator behavior and have it simulated accurately so that powered motion is evaluated against the motion I actually declared.

**Acceptance Criteria:**

**Given** an actuator definition with a declared controller function or motion profile
**When** simulation runs
**Then** the system applies that declared behavior to the motion model and records the resulting motion

**Given** a benchmark that uses powered movement
**When** it is simulated
**Then** the motion follows the declared actuator behavior rather than a hand-authored teleport or constraint shortcut, and engineer-created parts remain fixed in the air

**Given** a time-based or position-based actuator controller
**When** the benchmark is evaluated
**Then** the actuator command is interpreted from the declared control function rather than inferred from unrelated simulation state

**Given** an unsupported motion type
**When** simulation runs
**Then** the run fails closed rather than inventing motion behavior

### Story 8.2: Enforce Motion Limits and Overload Behavior

As a human operator, I want motion limits and overload behavior to be enforced so that benchmarks involving actuators remain physically believable.

**Acceptance Criteria:**

**Given** an actuator with defined torque, speed, or stroke limits
**When** the commanded motion exceeds those limits
**Then** the simulation records a deterministic overload or failure reason

**Given** a motion path that leaves the allowed envelope
**When** simulation runs
**Then** the system marks the run as failed rather than allowing unlimited motion

**Given** a powered benchmark that lacks required motion metadata
**When** it is validated
**Then** it is rejected instead of being approximated silently

### Story 8.3: Expose Actuator Evidence in Review

As a human operator, I want actuator motion and controller evidence to be visible so that I can inspect powered behavior and use it in benchmark validation.

**Acceptance Criteria:**

**Given** an actuator-enabled run
**When** I inspect the episode
**Then** I can see the actuator state, commanded control path, and resulting motion evidence

**Given** a review stage for a benchmark involving actuators
**When** evidence is available
**Then** the review surface can distinguish actuator motion from passive gravity motion

**Given** the simulation fails
**When** I inspect the run
**Then** the failure classification identifies the motion-limit or overload condition explicitly

## Epic 9: Gravity: Benchmarks (Movable Engineer Parts)

Benchmark generator agents can reliably produce valid simple rigid-body benchmarks with gravity enabled that human engineers can work against once engineer-created parts can move in simulation, and the benchmark family stays within rigid-body mechanics and gravity.

### Story 9.1: Generate Simple Rigid-Body Benchmarks

As a human operator, I want benchmark generator agents to produce simple rigid-body benchmark candidates so that the benchmark family stays within rigid-body mechanics with gravity enabled while engineer-created parts can move in simulation.

**Acceptance Criteria:**

**Given** a simple rigid-body benchmark seed or prompt
**When** generation runs
**Then** the candidate remains within the simple rigid-body, gravity-enabled scope and does not introduce actuators, FEM, or fluids

**Given** an engineer-part-movable rollout candidate
**When** the benchmark is used for solution work
**Then** engineer-created parts can move in simulation during validation

**Given** an unsupported mechanism or modality
**When** generation runs
**Then** the candidate is rejected rather than silently adapted

**Given** a generated benchmark candidate
**When** it is reviewed
**Then** its objective, zones, and motion assumptions are explicit enough for a human engineer to work against it

### Story 9.2: Produce a Representative Simple Rigid-Body Validation Set

As a human operator, I want a sufficiently broad simple rigid-body validation set so that engineers can work against meaningful variations rather than a single toy case.

**Acceptance Criteria:**

**Given** the simple rigid-body benchmark family
**When** seeds are generated
**Then** the set includes multiple variants across object shape, placement, size, and objective arrangement

**Given** the validation set
**When** I inspect it
**Then** it is broad enough to exercise the benchmark generator against repeatable simple rigid-body cases

**Given** a family member is duplicated too closely
**When** the set is curated
**Then** the duplicate is excluded or marked as redundant

### Story 9.3: Refine Simple Rigid-Body Benchmark Quality

As a human operator, I want benchmark generator output to improve based on reviewer feedback so that generated simple rigid-body benchmarks remain solvable, unambiguous, and suitable for engineering intake.

**Acceptance Criteria:**

**Given** reviewer feedback on a simple rigid-body benchmark
**When** the benchmark is regenerated
**Then** the next revision preserves the solvable contract and resolves the flagged issue

**Given** a technically valid but poor simple rigid-body benchmark
**When** review runs
**Then** it can be rejected as unsuitable for engineering intake

**Given** repeated simple rigid-body benchmark generations
**When** I inspect the run set
**Then** rejected examples are preserved for debugging and dataset analysis

### Story 9.4: Reliable Simple Rigid-Body Benchmark Output and Reviews

As a human operator, I want simple rigid-body benchmark output and benchmark reviews to be reliably good and explainable so that I can trust the AI without manually correcting most attempts.

**Acceptance Criteria:**

**Given** 10 simple rigid-body benchmark generation attempts
**When** I review the outputs
**Then** at least 8 of the benchmarks are usable by a human operator without me correcting the benchmark definition

**Given** an AI-generated simple rigid-body benchmark review
**When** I inspect it
**Then** the review explains the problem or acceptance reason clearly enough for a human to follow

**Given** a simple rigid-body benchmark review is unclear
**When** I read it
**Then** I can reject it as insufficiently explainable

## Epic 10: Gravity: Engineering (Movable Engineer Parts)

Engineering agents can solve simple rigid-body benchmarks with verified solutions that behave correctly in rigid-body simulation with gravity enabled, and engineer-created parts can move in simulation during this rollout phase.

### Story 10.1: Solve Simple Rigid-Body Benchmarks

As a human operator, I want engineering agents to solve simple rigid-body benchmarks so that the system can produce a working solution for a rigid-body problem with gravity enabled while engineer-created parts can move in simulation.

**Acceptance Criteria:**

**Given** an approved simple rigid-body benchmark
**When** engineering runs
**Then** the agent produces a candidate solution against the same benchmark contract

**Given** a simple rigid-body solution attempt
**When** it is evaluated
**Then** the result is judged in physically correct simple rigid-body simulation with gravity enabled, and engineer-created parts can move in simulation

**Given** the candidate solution fails
**When** the run terminates
**Then** the failure reason is explicit and the agent can continue from the same benchmark

### Story 10.2: Verify Physics-Correct Simple Rigid-Body Solutions

As a human operator, I want simple rigid-body solutions to be verified against physical reality so that a passing solution is not only syntactically valid but physically plausible.

**Acceptance Criteria:**

**Given** a passing simple rigid-body solution
**When** the solution is reviewed
**Then** it respects rigid-body mechanics with gravity enabled, and the benchmark-defined zones and objectives

**Given** a solution that only works due to simulation artifacts or unstable behavior
**When** it is checked
**Then** it is rejected as flaky or physically implausible

**Given** a solution that passes under the required conditions
**When** validation completes
**Then** the solution is accepted as a verified simple rigid-body result

### Story 10.3: Persist Final Proof for Simple Rigid-Body Solutions

As a human operator, I want the final simple rigid-body solution proof and evidence persisted so that the solution can be inspected, exported, and reproduced later.

**Acceptance Criteria:**

**Given** an accepted simple rigid-body solution
**When** it is finalized
**Then** the final proof artifact is distinct from any preview artifact and is persisted with the episode

**Given** the solution evidence exists
**When** I inspect the episode later
**Then** I can review the exact render, simulation, and terminal metadata used to accept the run

**Given** the simple rigid-body solution is revisited later
**When** the bundle is reloaded
**Then** the persisted artifacts are sufficient to reproduce the accepted result without rerunning the solver

### Story 10.4: Reliable Simple Rigid-Body Solution Output and Reviews

As a human operator, I want simple rigid-body solution output and solution reviews to be reliably good and explainable so that I can trust the AI without manually correcting most attempts.

**Acceptance Criteria:**

**Given** 10 simple rigid-body solution attempts
**When** I review the outputs
**Then** at least 8 of the solutions are valid without me correcting the solution

**Given** an AI-generated simple rigid-body solution review
**When** I inspect it
**Then** the review explains the pass or fail decision clearly enough for a human to follow

**Given** a simple rigid-body solution review is unclear
**When** I read it
**Then** I can reject it as insufficiently explainable

## Epic 11: Manufacturability: Simulation

Human operators can validate manufacturability using real manufacturing and catalog data so they can distinguish prototype answers from production-ready ones.

### Story 11.1: Configure Real Cost Inputs

As a human operator, I want to configure the prices used for costing from real manufacturing and catalog data so that the system evaluates designs with defensible price assumptions instead of invented numbers.

**Acceptance Criteria:**

**Given** a cost sheet or catalog source with known part pricing
**When** I configure the costing inputs
**Then** the system stores the selected price assumptions for later validation

**Given** a missing or invalid price source
**When** the costing inputs are validated
**Then** the system rejects the configuration with an explicit reason

### Story 11.2: Evaluate Manufacturability at the Requested Quantity

As a human operator, I want the system to evaluate whether a solution is manufacturable at the requested production volume so that I can distinguish a prototype answer from a small-batch or mass-production answer.

**Acceptance Criteria:**

**Given** a requested production quantity
**When** manufacturability is evaluated
**Then** the system separates setup cost from variable cost and chooses a manufacturing method that satisfies the requirements within the allowed envelope

**Given** a design that exceeds the allowed cost or weight envelope for the requested quantity
**When** validation runs
**Then** the solution is rejected with an explicit reason

**Given** multiple manufacturing methods are possible for the same part
**When** the system evaluates the design
**Then** the chosen method is the one that satisfies the requirements within the allowed envelope

### Story 11.3: Evaluate Weight, Size, Form Factor, and COTS

As a human operator, I want the system to evaluate weight, size, and form-factor constraints together, and include COTS parts in the cost and manufacturability result, so that the answer reflects what can actually be built.

**Acceptance Criteria:**

**Given** a design that includes COTS parts
**When** the solution is priced and weighed
**Then** the catalog parts are included in the total cost and weight

**Given** a design that violates size, weight, or form-factor limits
**When** validation runs
**Then** the system rejects it with an explicit reason

**Given** a candidate part without a valid catalog or manufacturing reference
**When** the design is reviewed
**Then** the system flags the missing reference instead of assuming a price or weight

## Epic 12: Manufacturability: Benchmarks

Human operators can represent allowed attachment and drilling points in benchmark setups so CAD and manufacturability review can validate how the design may be connected or modified.

### Story 12.1: Represent Allowed Attachment and Drilling Points

As a human operator, I want the system to represent allowed attachment and drilling points in the benchmark setup so that CAD and manufacturability review can validate how the design may be connected or modified.

**Acceptance Criteria:**

**Given** a benchmark with declared attachment or drilling points
**When** the benchmark package is reviewed
**Then** those points are persisted, visible, and tied to the latest revision

**Given** missing, conflicting, or unsupported attachment or drilling points
**When** validation runs
**Then** the system rejects or flags the benchmark with an explicit reason

**Given** a CAD revision changes attachment or drilling constraints
**When** the benchmark is reopened
**Then** the latest revision reflects the updated attachment and drilling rules in the review artifacts

## Epic 13: Manufacturability: Engineering

Human operators can identify unnecessary or unjustified degrees of freedom and prefer the simpler valid design during review.

### Story 13.1: Prefer the Simpler Valid Solution

As a human operator, I want the system to identify unnecessary or unjustified degrees of freedom and flag over-actuated solutions during review so that I can prefer the valid candidate with fewer unnecessary moving parts.

**Acceptance Criteria:**

**Given** two or more valid candidates for the same benchmark
**When** the system compares them
**Then** it prefers the candidate with fewer unnecessary degrees of freedom, actuators, and parts

**Given** a solution with unjustified extra movement
**When** I review it
**Then** I can reject it as over-actuated or unnecessarily complex

**Given** a solution whose movement is justified by the benchmark objective
**When** I review it
**Then** the system does not flag it as over-actuated merely because it moves

## Epic 14: Actuators: Simulation (Movable Engineer Parts)

Upgrade simulation fidelity for powered motion, actuators, and motion limits so that actuator-enabled benchmarks behave physically consistently once engineer-created parts can move in simulation.

### Story 14.1: Model Actuator-Driven Motion

As a human operator, I want to define actuator behavior and have it simulated accurately so that powered motion is evaluated against the motion I actually declared once engineer-created parts can move in simulation.

**Acceptance Criteria:**

**Given** an actuator definition with a declared controller function or motion profile
**When** simulation runs
**Then** the system applies that declared behavior to the motion model and records the resulting motion

**Given** a benchmark that uses powered movement
**When** it is simulated
**Then** the motion follows the declared actuator behavior rather than a hand-authored teleport or constraint shortcut

**Given** a time-based or position-based actuator controller
**When** the benchmark is evaluated
**Then** the actuator command is interpreted from the declared control function rather than inferred from unrelated simulation state

**Given** an unsupported motion type
**When** simulation runs
**Then** the run fails closed rather than inventing motion behavior

### Story 14.2: Enforce Motion Limits and Overload Behavior

As a human operator, I want motion limits and overload behavior to be enforced so that benchmarks involving actuators remain physically believable.

**Acceptance Criteria:**

**Given** an actuator with defined torque, speed, or stroke limits
**When** the commanded motion exceeds those limits
**Then** the simulation records a deterministic overload or failure reason

**Given** a motion path that leaves the allowed envelope
**When** simulation runs
**Then** the system marks the run as failed rather than allowing unlimited motion

**Given** a powered benchmark that lacks required motion metadata
**When** it is validated
**Then** it is rejected instead of being approximated silently

### Story 14.3: Expose Actuator Evidence in Review

As a human operator, I want actuator motion and controller evidence to be visible so that I can inspect powered behavior and use it in benchmark validation.

**Acceptance Criteria:**

**Given** an actuator-enabled run
**When** I inspect the episode
**Then** I can see the actuator state, commanded control path, and resulting motion evidence

**Given** a review stage for a benchmark involving actuators
**When** evidence is available
**Then** the review surface can distinguish actuator motion from passive gravity motion

**Given** the simulation fails
**When** I inspect the run
**Then** the failure classification identifies the motion-limit or overload condition explicitly

## Epic 15: Actuators: Benchmarks

Benchmark generator agents can ship actuator benchmark packages that a human operator can use without cleanup, and the packages describe powered motion explicitly enough for an engineering agent to solve them without modifying them.

### Story 15.1: Generate Benchmarks Involving Actuators

As a human operator, I want benchmark generator agents to produce actuator benchmark candidates so that the benchmark family includes solvable powered-motion problems instead of only simulation setups.

**Acceptance Criteria:**

**Given** a prompt or seed involving actuators
**When** generation runs
**Then** the candidate declares the actuator type, motion kind, axis or path, and operating envelope explicitly enough for an engineering agent to solve the benchmark package

**Given** an unsupported actuator or motion type
**When** generation runs
**Then** the candidate is rejected rather than silently adapted

**Given** a generated benchmark candidate
**When** it is reviewed
**Then** the powered motion is explicit enough for an engineering agent to solve the benchmark package

### Story 15.2: Produce a Representative Actuator Validation Set

As a human operator, I want a sufficiently broad actuator validation set so that engineers can work against meaningful powered-motion variations rather than a single toy case.

**Acceptance Criteria:**

**Given** the actuator benchmark family
**When** seeds are generated
**Then** the set includes multiple variants across actuator type, stroke, speed, load, and motion direction

**Given** the validation set
**When** I inspect it
**Then** it is broad enough to exercise the benchmark generator against repeatable powered-motion cases

**Given** two benchmark variants are materially identical
**When** the set is curated
**Then** the duplicate is excluded or marked as redundant

### Story 15.3: Refine Actuator Benchmark Quality

As a human operator, I want benchmark generator output to improve based on reviewer feedback so that generated benchmarks involving actuators remain solvable, unambiguous, and suitable for engineering intake.

**Acceptance Criteria:**

**Given** reviewer feedback on a benchmark involving actuators
**When** the benchmark is regenerated
**Then** the next revision preserves the powered-motion contract and resolves the flagged issue

**Given** a technically valid but poor actuator benchmark
**When** review runs
**Then** it can be rejected as unsuitable for engineering intake

**Given** repeated actuator benchmark generations
**When** I inspect the run set
**Then** rejected examples are preserved for debugging and dataset analysis

### Story 15.4: Reliable Actuator Benchmark Output and Reviews

As a human operator, I want actuator benchmark output and benchmark reviews to be reliably good and explainable so that I can trust the AI without manually correcting most attempts.

**Acceptance Criteria:**

**Given** 10 actuator benchmark generation attempts
**When** I review the outputs
**Then** at least 8 of the benchmarks are usable by a human operator without me correcting the benchmark definition

**Given** an AI-generated actuator benchmark review
**When** I inspect it
**Then** the review explains the problem or acceptance reason clearly enough for a human to follow

**Given** an actuator benchmark review is unclear
**When** I read it
**Then** I can reject it as insufficiently explainable

## Epic 16: Actuators: Engineering

Engineering agents can solve actuator benchmark packages without modifying the benchmark package, with verified solutions that respect powered motion limits and remain stable under review.

### Story 16.1: Solve Benchmarks Involving Actuators

As a human operator, I want engineering agents to solve actuator benchmarks so that the system can produce a working solution for a powered-motion problem from the package as provided.

**Acceptance Criteria:**

**Given** an approved benchmark involving actuators
**When** engineering runs
**Then** the agent produces a candidate solution against the same benchmark contract without modifying the benchmark package

**Given** an actuator-enabled solution attempt
**When** it is evaluated
**Then** the result is judged against the declared powered-motion behavior and physical envelope

**Given** the candidate solution fails
**When** the run terminates
**Then** the failure reason is explicit and the agent can continue from the same benchmark

### Story 16.2: Verify Actuator Solutions Under Load

As a human operator, I want actuator solutions to be verified under load and runtime jitter so that a passing solution is not just lucky or unstable.

**Acceptance Criteria:**

**Given** a passing actuator solution
**When** the solution is reviewed
**Then** it respects motion limits, load expectations, and the benchmark-defined objectives

**Given** a solution that only works because the actuator behavior is unstable or lucky
**When** it is checked
**Then** it is rejected as flaky or physically implausible

**Given** a solution that passes under the required conditions
**When** validation completes
**Then** the solution is accepted as a verified actuator-capable result

### Story 16.3: Persist Final Proof for Actuator Solutions

As a human operator, I want the final actuator solution proof and evidence persisted so that the solution can be inspected, exported, and reproduced later.

**Acceptance Criteria:**

**Given** an accepted actuator solution
**When** it is finalized
**Then** the final proof artifact is distinct from any preview artifact and is persisted with the episode

**Given** the solution evidence exists
**When** I inspect the episode later
**Then** I can review the exact render, simulation, and terminal metadata used to accept the run

**Given** the actuator solution is revisited later
**When** the bundle is reloaded
**Then** the persisted artifacts are sufficient to reproduce the accepted result without rerunning the solver

### Story 16.4: Reliable Actuator Solution Output and Reviews

As a human operator, I want actuator solution output and solution reviews to be reliably good and explainable so that I can trust the AI without manually correcting most attempts.

**Acceptance Criteria:**

**Given** 10 actuator solution attempts
**When** I review the outputs
**Then** at least 8 of the solutions are valid without me correcting the solution

**Given** an AI-generated actuator solution review
**When** I inspect it
**Then** the review explains the pass or fail decision clearly enough for a human to follow

**Given** an actuator solution review is unclear
**When** I read it
**Then** I can reject it as insufficiently explainable

## Epic 17: FEM: Simulation

Upgrade simulation fidelity for deformables, stress, and breakage so that FEM-backed benchmarks behave physically consistently.

### Story 17.1: Model Deformable and Stress-Aware Behavior

As a human operator, I want deformable and stress-aware simulation to be explicit so that tasks beyond rigid-body mechanics are evaluated correctly.

**Acceptance Criteria:**

**Given** a benchmark that requests FEM or soft-material behavior
**When** simulation runs
**Then** the backend uses the configured deformable or stress-aware path rather than a rigid-only approximation

**Given** a stress-aware run
**When** it completes
**Then** the system records structured stress summaries for the inspected parts

**Given** a rigid-only benchmark
**When** it is simulated
**Then** the FEM path is not activated accidentally

### Story 17.2: Enforce Stress Thresholds and Breakage

As a human operator, I want stress thresholds and breakage to be enforced so that failures are distinct and physically meaningful.

**Acceptance Criteria:**

**Given** a part whose stress exceeds its defined limit
**When** simulation runs
**Then** the run fails with the part identified explicitly

**Given** a breakage event
**When** it is recorded
**Then** the system persists the failure reason, peak stress, and location of the failure

**Given** a stress-aware benchmark that would otherwise appear to pass
**When** breakage or stress failure occurs
**Then** the run is not classified as successful

### Story 17.3: Expose FEM Review Artifacts

As a human operator, I want stress summaries and heatmaps visible in review so that I can inspect failure reasons without reading raw solver output.

**Acceptance Criteria:**

**Given** a FEM run with field data
**When** I inspect the episode
**Then** I can view the stress summaries and stress heatmaps associated with the latest revision

**Given** a stress-aware failure
**When** I inspect the run
**Then** the review surface makes the hotspot and failure mode understandable

**Given** a final FEM result
**When** it is archived
**Then** the durable artifacts include the structured stress result and review evidence

## Epic 18: FEM: Benchmarks

Benchmark generator agents can ship FEM benchmark packages that a human operator can use without cleanup, and the packages describe deformable behavior explicitly enough for an engineering agent to solve them without modifying them.

### Story 18.1: Generate FEM Benchmarks

As a human operator, I want benchmark generator agents to produce FEM benchmark candidates so that the benchmark family includes solvable deformable and stress-aware problems instead of only rigid-body cases.

**Acceptance Criteria:**

**Given** an FEM benchmark seed or prompt
**When** generation runs
**Then** the candidate declares `physics.fem_enabled`, the relevant material classes, and the stress objectives explicitly enough for an engineering agent to solve the benchmark package

**Given** an unsupported deformable or stress scenario
**When** generation runs
**Then** the candidate is rejected rather than silently adapted

**Given** a generated benchmark candidate
**When** it is reviewed
**Then** the deformable or stress-aware behavior is explicit enough for an engineering agent to solve the benchmark package

### Story 18.2: Produce a Representative FEM Validation Set

As a human operator, I want a sufficiently broad FEM validation set so that engineers can work against meaningful deformable variations rather than a single toy case.

**Acceptance Criteria:**

**Given** the FEM benchmark family
**When** seeds are generated
**Then** the set includes multiple variants across material class, load path, stress target, and part geometry

**Given** the validation set
**When** I inspect it
**Then** it is broad enough to exercise the benchmark generator against repeatable FEM cases

**Given** two benchmark variants are materially identical
**When** the set is curated
**Then** the duplicate is excluded or marked as redundant

### Story 18.3: Refine FEM Benchmark Quality

As a human operator, I want benchmark generator output to improve based on reviewer feedback so that generated FEM benchmarks remain solvable, unambiguous, and suitable for engineering intake.

**Acceptance Criteria:**

**Given** reviewer feedback on an FEM benchmark
**When** the benchmark is regenerated
**Then** the next revision preserves the stress-aware contract and resolves the flagged issue

**Given** a technically valid but poor FEM benchmark
**When** review runs
**Then** it can be rejected as unsuitable for engineering intake

**Given** repeated FEM benchmark generations
**When** I inspect the run set
**Then** rejected examples are preserved for debugging and dataset analysis

### Story 18.4: Reliable FEM Benchmark Output and Reviews

As a human operator, I want FEM benchmark output and benchmark reviews to be reliably good and explainable so that I can trust the AI without manually correcting most attempts.

**Acceptance Criteria:**

**Given** 10 FEM benchmark generation attempts
**When** I review the outputs
**Then** at least 8 of the benchmarks are usable by a human operator without me correcting the benchmark definition

**Given** an AI-generated FEM benchmark review
**When** I inspect it
**Then** the review explains the problem or acceptance reason clearly enough for a human to follow

**Given** an FEM benchmark review is unclear
**When** I read it
**Then** I can reject it as insufficiently explainable

## Epic 19: FEM: Engineering

Engineering agents can solve FEM benchmarks with verified, stress-aware solutions that remain stable under review and produce acceptable structural outcomes.

### Story 19.1: Solve FEM Benchmarks

As a human operator, I want engineering agents to solve FEM benchmarks so that the system can produce a working solution for a deformable or stress-aware problem from the package as provided.

**Acceptance Criteria:**

**Given** an approved FEM benchmark
**When** engineering runs
**Then** the agent produces a candidate solution against the same benchmark contract without modifying the benchmark package

**Given** a FEM-enabled solution attempt
**When** it is evaluated
**Then** the result is judged against the declared deformable behavior, stress objectives, and physical envelope

**Given** the candidate solution fails
**When** the run terminates
**Then** the failure reason is explicit and the agent can continue from the same benchmark

### Story 19.2: Verify FEM Solutions Under Load

As a human operator, I want FEM solutions to be verified under load and runtime jitter so that a passing solution is not just lucky or structurally unstable.

**Acceptance Criteria:**

**Given** a passing FEM solution
**When** the solution is reviewed
**Then** it respects the stress thresholds, material constraints, and benchmark-defined objectives

**Given** a solution that only works because the structural response is unstable or lucky
**When** it is checked
**Then** it is rejected as flaky or physically implausible

**Given** a solution that passes under the required conditions
**When** validation completes
**Then** the solution is accepted as a verified FEM-capable result

### Story 19.3: Persist Final Proof for FEM Solutions

As a human operator, I want the final FEM solution proof and evidence persisted so that the solution can be inspected, exported, and reproduced later.

**Acceptance Criteria:**

**Given** an accepted FEM solution
**When** it is finalized
**Then** the final proof artifact is distinct from any preview artifact and is persisted with the episode

**Given** the solution evidence exists
**When** I inspect the episode later
**Then** I can review the exact render, stress summary, and terminal metadata used to accept the run

**Given** the FEM solution is revisited later
**When** the bundle is reloaded
**Then** the persisted artifacts are sufficient to reproduce the accepted result without rerunning the solver

### Story 19.4: Reliable FEM Solution Output and Reviews

As a human operator, I want FEM solution output and solution reviews to be reliably good and explainable so that I can trust the AI without manually correcting most attempts.

**Acceptance Criteria:**

**Given** 10 FEM solution attempts
**When** I review the outputs
**Then** at least 8 of the solutions are valid without me correcting the solution

**Given** an AI-generated FEM solution review
**When** I inspect it
**Then** the review explains the pass or fail decision clearly enough for a human to follow

**Given** a FEM solution review is unclear
**When** I read it
**Then** I can reject it as insufficiently explainable

## Epic 20: Fluids: Simulation

Upgrade simulation fidelity for fluid containment, flow, and fluid-solid interaction so that fluid-enabled benchmarks behave physically consistently.

### Story 20.1: Model Fluid Containment and Flow

As a human operator, I want fluid containment and flow to be simulated explicitly so that liquid behavior is not treated as a hidden assumption.

**Acceptance Criteria:**

**Given** a benchmark that requests fluid behavior
**When** simulation runs
**Then** the backend uses the configured fluid-capable path rather than a rigid-only approximation

**Given** a fluid containment objective
**When** the run completes
**Then** the system records structured fluid metrics for the containment result

**Given** a fluid benchmark with flow objectives
**When** it is simulated
**Then** the flow rate or equivalent fluid objective is measured rather than inferred

### Story 20.2: Enforce Fluid-Solid Interaction and Failure

As a human operator, I want fluid-solid interaction and failure to be enforced so that fluid benchmarks remain physically meaningful.

**Acceptance Criteria:**

**Given** a fluid benchmark where containment is lost
**When** simulation runs
**Then** the run fails with an explicit containment or spill reason

**Given** fluid contact with a protected component
**When** simulation runs
**Then** the run records the appropriate hard failure instead of passing silently

**Given** a fluid or flow benchmark that would otherwise appear to pass
**When** instability or hard failure occurs
**Then** the run is not classified as successful

### Story 20.3: Expose Fluid Review Artifacts

As a human operator, I want fluid metrics and dynamic evidence visible in review so that I can inspect failure reasons without reading raw solver output.

**Acceptance Criteria:**

**Given** a fluid run with dynamic evidence
**When** I inspect the episode
**Then** I can view the fluid metrics, rendered evidence, and failure classification associated with the latest revision

**Given** a fluid benchmark review
**When** evidence is available
**Then** the review surface can distinguish containment loss, flow miss, and instability

**Given** a final fluid result
**When** it is archived
**Then** the durable artifacts include the structured fluid result and review evidence

## Epic 21: Fluids: Benchmarks

Benchmark generator agents can ship fluid benchmark packages that a human operator can use without cleanup, and the packages describe fluid behavior explicitly enough for an engineering agent to solve them without modifying them.

### Story 21.1: Generate Fluid Benchmarks

As a human operator, I want benchmark generator agents to produce fluid benchmark candidates so that the benchmark family includes solvable containment and flow problems instead of only rigid-body cases.

**Acceptance Criteria:**

**Given** a fluid benchmark seed or prompt
**When** generation runs
**Then** the candidate declares the fluid body, initial volume, containment objective, and flow objective explicitly enough for an engineering agent to solve the benchmark package

**Given** an unsupported fluid or containment scenario
**When** generation runs
**Then** the candidate is rejected rather than silently adapted

**Given** a generated benchmark candidate
**When** it is reviewed
**Then** the fluid behavior is explicit enough for an engineering agent to solve the benchmark package

### Story 21.2: Produce a Representative Fluid Validation Set

As a human operator, I want a sufficiently broad fluid validation set so that engineers can work against meaningful liquid variations rather than a single toy case.

**Acceptance Criteria:**

**Given** the fluid benchmark family
**When** seeds are generated
**Then** the set includes multiple variants across fluid volume, container geometry, flow target, and containment geometry

**Given** the validation set
**When** I inspect it
**Then** it is broad enough to exercise the benchmark generator against repeatable fluid cases

**Given** two benchmark variants are materially identical
**When** the set is curated
**Then** the duplicate is excluded or marked as redundant

### Story 21.3: Refine Fluid Benchmark Quality

As a human operator, I want benchmark generator output to improve based on reviewer feedback so that generated fluid benchmarks remain solvable, unambiguous, and suitable for engineering intake.

**Acceptance Criteria:**

**Given** reviewer feedback on a fluid benchmark
**When** the benchmark is regenerated
**Then** the next revision preserves the fluid contract and resolves the flagged issue

**Given** a technically valid but poor fluid benchmark
**When** review runs
**Then** it can be rejected as unsuitable for engineering intake

**Given** repeated fluid benchmark generations
**When** I inspect the run set
**Then** rejected examples are preserved for debugging and dataset analysis

### Story 21.4: Reliable Fluid Benchmark Output and Reviews

As a human operator, I want fluid benchmark output and benchmark reviews to be reliably good and explainable so that I can trust the AI without manually correcting most attempts.

**Acceptance Criteria:**

**Given** 10 fluid benchmark generation attempts
**When** I review the outputs
**Then** at least 8 of the benchmarks are usable by a human operator without me correcting the benchmark definition

**Given** an AI-generated fluid benchmark review
**When** I inspect it
**Then** the review explains the problem or acceptance reason clearly enough for a human to follow

**Given** a fluid benchmark review is unclear
**When** I read it
**Then** I can reject it as insufficiently explainable

## Epic 22: Fluids: Engineering

Engineering agents can solve fluid benchmarks with verified solutions that respect containment, flow, and stability requirements.

### Story 22.1: Solve Fluid Benchmarks

As a human operator, I want engineering agents to solve fluid benchmarks so that the system can produce a working solution for a containment or flow problem from the package as provided.

**Acceptance Criteria:**

**Given** an approved fluid benchmark
**When** engineering runs
**Then** the agent produces a candidate solution against the same benchmark contract without modifying the benchmark package

**Given** a fluid-enabled solution attempt
**When** it is evaluated
**Then** the result is judged against the declared containment, flow, and physical envelope

**Given** the candidate solution fails
**When** the run terminates
**Then** the failure reason is explicit and the agent can continue from the same benchmark

### Story 22.2: Verify Fluid Solutions Under Load

As a human operator, I want fluid solutions to be verified under load and runtime jitter so that a passing solution is not just lucky or unstable.

**Acceptance Criteria:**

**Given** a passing fluid solution
**When** the solution is reviewed
**Then** it respects containment, flow targets, and the benchmark-defined objectives

**Given** a solution that only works because the fluid behavior is unstable or lucky
**When** it is checked
**Then** it is rejected as flaky or physically implausible

**Given** a fluid benchmark that includes a protected component
**When** the solution is evaluated
**Then** fluid contact with the protected component is treated as a hard failure

### Story 22.3: Persist Final Proof for Fluid Solutions

As a human operator, I want the final fluid solution proof and evidence persisted so that the solution can be inspected, exported, and reproduced later.

**Acceptance Criteria:**

**Given** an accepted fluid solution
**When** it is finalized
**Then** the final proof artifact is distinct from any preview artifact and is persisted with the episode

**Given** the solution evidence exists
**When** I inspect the episode later
**Then** I can review the exact render, fluid metrics, and terminal metadata used to accept the run

**Given** the fluid solution is revisited later
**When** the bundle is reloaded
**Then** the persisted artifacts are sufficient to reproduce the accepted result without rerunning the solver

### Story 22.4: Reliable Fluid Solution Output and Reviews

As a human operator, I want fluid solution output and solution reviews to be reliably good and explainable so that I can trust the AI without manually correcting most attempts.

**Acceptance Criteria:**

**Given** 10 fluid solution attempts
**When** I review the outputs
**Then** at least 8 of the solutions are valid without me correcting the solution

**Given** an AI-generated fluid solution review
**When** I inspect it
**Then** the review explains the pass or fail decision clearly enough for a human to follow

**Given** a fluid solution review is unclear
**When** I read it
**Then** I can reject it as insufficiently explainable

## Epic 23: Electronics: Simulation

Upgrade simulation fidelity for circuit validity, wire routing, and power-gated actuation so that electromechanical benchmarks behave physically consistently.

### Story 23.1: Model Circuit-Valid Powered Behavior

As a human operator, I want circuit validity and powered behavior to be simulated explicitly so that motors do not move without a valid electrical design.

**Acceptance Criteria:**

**Given** a benchmark that depends on electrical power
**When** simulation runs
**Then** the system validates the circuit before allowing powered motion to proceed

**Given** a valid circuit and powered mechanism
**When** the run completes
**Then** the mechanical result is gated by electrical power availability rather than assumed implicitly

**Given** an invalid or missing circuit
**When** simulation runs
**Then** the run fails closed with a circuit-related reason

### Story 23.2: Enforce Wiring, Current, and Power Failure Modes

As a human operator, I want wiring and power failure modes to be enforced so that electromechanical benchmarks remain physically meaningful.

**Acceptance Criteria:**

**Given** a short circuit, open circuit, floating node, or overcurrent condition
**When** simulation runs
**Then** the run records a deterministic electrical failure reason

**Given** a wire route that violates the benchmark-defined physical path or gauge limits
**When** simulation runs
**Then** the run fails rather than allowing an invalid powered design

**Given** an electrical benchmark that would otherwise appear to pass
**When** the power state is invalid
**Then** the run is not classified as successful

### Story 23.3: Expose Schematic and Route Evidence

As a human operator, I want schematic and wire-route evidence visible in review so that I can inspect electrical failure reasons without reading raw solver output.

**Acceptance Criteria:**

**Given** an electromechanical run with electrical evidence
**When** I inspect the episode
**Then** I can view the schematic, routed wires, and failure classification associated with the latest revision

**Given** a powered benchmark review
**When** evidence is available
**Then** the review surface can distinguish circuit failure, routing failure, and power-gated motion failure

**Given** a final electromechanical result
**When** it is archived
**Then** the durable artifacts include the structured electrical result and review evidence

## Epic 24: Electronics: Benchmarks

Benchmark generator agents can ship electromechanical benchmark packages that a human operator can use without cleanup, and the packages describe powered behavior explicitly enough for an engineering agent to solve them without modifying them.

### Story 24.1: Generate Benchmarks Involving Electronics

As a human operator, I want benchmark generator agents to produce benchmark candidates involving electronics so that powered mechanisms have explicit circuit and wiring requirements rather than hidden assumptions.

**Acceptance Criteria:**

**Given** a prompt or seed involving electronics
**When** generation runs
**Then** the candidate declares the power supply, components, wire route, and powered motion contract explicitly enough for an engineering agent to solve the benchmark package

**Given** an unsupported circuit or wiring scenario
**When** generation runs
**Then** the candidate is rejected rather than silently adapted

**Given** a generated benchmark candidate
**When** it is reviewed
**Then** the electrical behavior is explicit enough for an engineering agent to solve the benchmark package

### Story 24.2: Produce a Representative Electronics Validation Set

As a human operator, I want a sufficiently broad electronics validation set so that engineers can work against meaningful electromechanical variations rather than a single toy case.

**Acceptance Criteria:**

**Given** the electronics benchmark family
**When** seeds are generated
**Then** the set includes multiple variants across power supply, component family, wiring path, and load conditions

**Given** the validation set
**When** I inspect it
**Then** it is broad enough to exercise the benchmark generator against repeatable electromechanical cases

**Given** two benchmark variants are materially identical
**When** the set is curated
**Then** the duplicate is excluded or marked as redundant

### Story 24.3: Refine Electronics Benchmark Quality

As a human operator, I want benchmark generator output to improve based on reviewer feedback so that generated benchmarks involving electronics remain solvable, unambiguous, and suitable for engineering intake.

**Acceptance Criteria:**

**Given** reviewer feedback on a benchmark involving electronics
**When** the benchmark is regenerated
**Then** the next revision preserves the circuit and wiring contract and resolves the flagged issue

**Given** a technically valid but poor electronics benchmark
**When** review runs
**Then** it can be rejected as unsuitable for engineering intake

**Given** repeated electronics benchmark generations
**When** I inspect the run set
**Then** rejected examples are preserved for debugging and dataset analysis

### Story 24.4: Reliable Electronics Benchmark Output and Reviews

As a human operator, I want electronics benchmark output and benchmark reviews to be reliably good and explainable so that I can trust the AI without manually correcting most attempts.

**Acceptance Criteria:**

**Given** 10 electronics benchmark generation attempts
**When** I review the outputs
**Then** at least 8 of the benchmarks are usable by a human operator without me correcting the benchmark definition

**Given** an AI-generated electronics benchmark review
**When** I inspect it
**Then** the review explains the problem or acceptance reason clearly enough for a human to follow

**Given** an electronics benchmark review is unclear
**When** I read it
**Then** I can reject it as insufficiently explainable

## Epic 25: Electronics: Engineering

Engineering agents can solve electromechanical benchmarks with verified solutions that respect circuit validity, wiring constraints, and power-gated actuation.

### Story 25.1: Solve Benchmarks Involving Electronics

As a human operator, I want engineering agents to solve benchmarks involving electronics so that the system can produce a working solution for a powered mechanism from the package as provided.

**Acceptance Criteria:**

**Given** an approved benchmark involving electronics
**When** engineering runs
**Then** the agent produces a candidate solution against the same benchmark contract without modifying the benchmark package

**Given** an electromechanical solution attempt
**When** it is evaluated
**Then** the result is judged against the declared circuit, wiring, power, and physical envelope

**Given** the candidate solution fails
**When** the run terminates
**Then** the failure reason is explicit and the agent can continue from the same benchmark

### Story 25.2: Verify Electromechanical Solutions Under Load

As a human operator, I want electromechanical solutions to be verified under load and runtime jitter so that a passing solution is not just lucky or electrically unsafe.

**Acceptance Criteria:**

**Given** a passing electromechanical solution
**When** the solution is reviewed
**Then** it respects circuit validity, power budget, wire routing, and benchmark-defined objectives

**Given** a solution that only works because the electrical behavior is unstable or lucky
**When** it is checked
**Then** it is rejected as flaky or physically implausible

**Given** a solution with a short circuit, open circuit, overcurrent, or invalid wire route
**When** the solution is evaluated
**Then** it is rejected as electrically unsafe or physically implausible

### Story 25.3: Persist Final Proof for Electromechanical Solutions

As a human operator, I want the final electromechanical solution proof and evidence persisted so that the solution can be inspected, exported, and reproduced later.

**Acceptance Criteria:**

**Given** an accepted electromechanical solution
**When** it is finalized
**Then** the final proof artifact is distinct from any preview artifact and is persisted with the episode

**Given** the solution evidence exists
**When** I inspect the episode later
**Then** I can review the exact schematic, wire-route, simulation, and terminal metadata used to accept the run

**Given** the electromechanical solution is revisited later
**When** the bundle is reloaded
**Then** the persisted artifacts are sufficient to reproduce the accepted result without rerunning the solver

### Story 25.4: Reliable Electromechanical Solution Output and Reviews

As a human operator, I want electromechanical solution output and solution reviews to be reliably good and explainable so that I can trust the AI without manually correcting most attempts.

**Acceptance Criteria:**

**Given** 10 electromechanical solution attempts
**When** I review the outputs
**Then** at least 8 of the solutions are valid without me correcting the solution

**Given** an AI-generated electromechanical solution review
**When** I inspect it
**Then** the review explains the pass or fail decision clearly enough for a human to follow

**Given** an electromechanical solution review is unclear
**When** I read it
**Then** I can reject it as insufficiently explainable

## Epic 26: UI, Visualization, and Demo

Human operators can inspect session history, review traces and artifacts, visualize CAD and simulation evidence, watch agent output in real time, interrupt active runs, and present completed runs through a browser UI. This work is deferred until after the electronics family and is not part of the early MVP path.

### Story 26.1: Inspect Session History and Run Timeline

As a human operator, I want a session history and run timeline so that I can inspect the progress and outcome of benchmark and solution runs in one place.

**Acceptance Criteria:**

**Given** a session
**When** I open it in the UI
**Then** I can see the episode history, status, terminal reason, and progress of the active or completed run

**Given** backend traces and tool calls exist
**When** I inspect the run
**Then** the UI renders those persisted records rather than fabricating placeholders

**Given** an interrupted run
**When** I reopen the session
**Then** I can resume from the last persisted state

**Given** context usage telemetry exists
**When** I inspect the run
**Then** the UI shows it

### Story 26.2: Visualize CAD and Simulation Evidence

As a human operator, I want to visualize CAD models, render evidence, and simulation playback so that I can verify the run visually rather than from text alone.

**Acceptance Criteria:**

**Given** a completed episode with CAD assets
**When** I open the viewer
**Then** I can inspect the model and hide or isolate parts

**Given** simulation renders or video exist
**When** I open the run
**Then** I can play, pause, and scrub the evidence over time

**Given** latest-revision media exists
**When** I inspect the run
**Then** the UI binds the view to the latest revision rather than stale prior media

### Story 26.3: View Code and Artifacts

As a human operator, I want to view code, plans, and other files in the browser so that I can inspect the actual artifacts that produced the run.

**Acceptance Criteria:**

**Given** a run has plan, TODO, code, or review files
**When** I open the artifact viewer
**Then** the file tree, line numbers, and syntax coloring are available

**Given** a markdown or code file is selected
**When** I inspect it
**Then** the UI shows the exact file contents from the persisted artifact set

**Given** a benchmark or solution run
**When** I inspect its artifacts
**Then** I can see the related manifests, logs, and review outputs in the same workspace

### Story 26.4: Collect Feedback and Present Demos

As a human operator, I want to submit feedback and present completed runs through the UI so that I can capture review input and demonstrate system capability without leaving the browser.

**Acceptance Criteria:**

**Given** a completed model output
**When** I submit feedback
**Then** I can provide thumbs up or down, a short explanation, and a common feedback topic

**Given** a completed run
**When** I present it in demo mode
**Then** the UI surfaces the relevant session, CAD, simulation, and artifact views in a stable layout

**Given** feedback is recorded
**When** I inspect the run later
**Then** the feedback is persisted alongside the episode record and can be reviewed later

### Story 26.5: Inspect Live Agent Output and Interrupt Execution

As a human operator, I want to see the agent's output and reasoning in real time, and interrupt execution when it goes off track, so that I can catch logical errors early.

**Acceptance Criteria:**

**Given** an active agent run
**When** I inspect the session
**Then** I can see tool-call activity and reasoning traces as they arrive from the backend

**Given** I need to stop a run
**When** I press the stop button
**Then** the controller interrupts the active agent execution

**Given** reasoning traces are required but unavailable
**When** I inspect the run
**Then** the UI shows an explicit missing-trace state instead of pretending success

### Story 26.6: Create Benchmarks and Review Simple Plans

As a human operator, I want to create benchmark drafts and accept or reject simple plan artifacts in the UI so that I can handle lightweight workflow steps without leaving the browser.

**Acceptance Criteria:**

**Given** a benchmark draft prompt or form input
**When** I submit it
**Then** a benchmark draft is created and persisted

**Given** a planner handoff artifact
**When** I review it
**Then** I can accept or reject it with an explicit reason

**Given** a simple workflow action
**When** I complete it in the UI
**Then** the result is recorded in the episode trace

## Epic 27: Steering & Control

Human operators can steer the active benchmark generator and engineering agents with selected CAD, code, file, or media context and targeted corrections, and the selected context is preserved in traces and prompt payloads. This is the advanced steerability surface, and it comes later because the agents have to be tuned to consume the richer context, not because the frontend interaction is fundamentally harder.

### Story 27.1: Attach Structured Context to Steering Prompts

As a human operator, I want to attach selected CAD parts, faces, subassemblies, code lines, file references, or media references to a steering prompt so that I can direct an agent with precise context.

**Acceptance Criteria:**

**Given** a selected CAD entity, code span, file reference, or media reference
**When** I attach it to a steering prompt
**Then** the selected context is preserved in the prompt payload and trace metadata

**Given** multiple selected items
**When** I submit the steering prompt
**Then** the selected items remain distinct rather than being collapsed into an ambiguous blob

**Given** an invalid or stale selection
**When** I submit the steering prompt
**Then** the system rejects it with an explicit failure reason

### Story 27.2: Switch CAD Selection Mode

As a human operator, I want to switch CAD selection mode between faces, parts/bodies, and subassemblies so that I can select the exact geometry needed for steering.

**Acceptance Criteria:**

**Given** a CAD model with selectable faces, parts/bodies, and subassemblies
**When** I switch selection mode
**Then** the UI lets me select that entity type distinctly

**Given** a selected CAD entity
**When** I attach it to a steering prompt
**Then** the selected entity and selection mode are preserved in the prompt payload and trace metadata

**Given** an unsupported or stale selection mode
**When** I switch modes
**Then** the system rejects it with an explicit failure reason

### Story 27.3: Apply Corrective Steering During Active Runs

As a human operator, I want to send corrective steering during an active run so that I can refine the agent's direction when I notice an incorrect assumption early.

**Acceptance Criteria:**

**Given** an active benchmark-generation or engineering run
**When** I submit a corrective steering prompt
**Then** the agent receives the selected context and the correction while the run is still active

**Given** a completed or terminal run
**When** I try to steer it
**Then** the system blocks the request rather than pretending that the run is still active

**Given** a steering correction changes the agent's direction
**When** the run continues
**Then** the resulting edits remain linked to the steering action in the trace

### Story 27.4: Preserve Steering Provenance

As a maintainer, I want steering context and resulting edits preserved so that I can debug the effect of steering and replay it later if needed.

**Acceptance Criteria:**

**Given** a steering action
**When** I inspect the episode later
**Then** I can see the original selection metadata, the steering prompt, and the resulting agent output

**Given** steering is used repeatedly in one episode
**When** I inspect the trace
**Then** each steering action remains attributable to the exact selected context and revision

**Given** no steering occurred
**When** I inspect the episode
**Then** the trace remains clean and does not synthesize fake steering events

## Epic 28: Market Fit & Hardening

Define the first target market and harden the product around that market so that the release has a clear customer profile, quality bar, and scope boundary.

### Story 28.1: Define the Target Market

As a product owner, I want to define the first target market and core use case so that product decisions are anchored to a concrete customer segment.

**Acceptance Criteria:**

**Given** the current product strategy
**When** market definition is completed
**Then** the target market, primary user type, and primary benchmark family are documented

**Given** competing market options
**When** a decision is made
**Then** the selected market is explicit and the unselected options are marked as out of scope

### Story 28.2: Translate Market Needs into Product Requirements

As a product owner, I want market-specific requirements to be translated into product constraints so that implementation work stays aligned to the chosen market.

**Acceptance Criteria:**

**Given** the selected market
**When** product requirements are updated
**Then** the release scope, benchmark scope, and UI surface reflect the chosen market

**Given** a requested feature that does not serve the chosen market
**When** it is reviewed
**Then** it is deferred or rejected with an explicit rationale

### Story 28.3: Harden for Release

As a product owner, I want the product hardened for the chosen market so that the release is reliable, supportable, and ready for external use.

**Acceptance Criteria:**

**Given** the target market and release scope
**When** hardening work is completed
**Then** the product has the required quality gates, observability, and operational constraints for that market

**Given** the release candidate
**When** it is reviewed
**Then** the system is judged against the market-specific quality bar rather than an abstract internal prototype bar

### Story 28.4: Inspect CAD Constraints and Joints

As a human operator, I want to inspect CAD constraints, mates, and joints so that I can understand how an imported assembly moves and where the solver should respect motion relationships.

**Acceptance Criteria:**

**Given** a CAD model with imported constraints or joints
**When** I open the visualization surface
**Then** I can toggle an overlay that shows the constraint graph for the model

**Given** the constraint overlay is enabled
**When** I inspect a connected part pair
**Then** I can see the constraint or mate type, the connected entities, and any available axis or limit metadata

**Given** a model without imported constraints
**When** I enable the constraint overlay
**Then** the UI shows an explicit empty state rather than inventing joints or mates

## Epic 29: Uploaded CAD Models

Users can upload CAD models as input objects or benchmark environments and validate imported motion and constraint metadata so that native CAD inputs can enter the product without first being manually rebuilt into a benchmark.

### Story 29.1: Upload CAD Input Objects

As a human operator, I want to upload CAD input objects so that I can start from an existing model instead of rebuilding the geometry manually.

**Acceptance Criteria:**

**Given** a supported CAD input model
**When** I upload it
**Then** the system stores the uploaded asset set and exposes it as the active episode input

**Given** an uploaded input model with explicit motion or constraint metadata
**When** the system imports it
**Then** the imported metadata is preserved as structured evidence instead of being flattened into a generic file blob

**Given** an unsupported file or a package that lacks the required motion metadata for the selected workflow
**When** I upload it
**Then** the system rejects it with an explicit failure reason

### Story 29.2: Upload CAD Benchmark Environments

As a human operator, I want to upload CAD benchmark environments so that I can reuse existing benchmark geometry without manually reconstructing the environment first.

**Acceptance Criteria:**

**Given** a supported CAD benchmark environment
**When** I upload it
**Then** the system stores the uploaded environment as benchmark-owned context

**Given** an uploaded benchmark environment with explicit motion, zones, or constraints
**When** the system imports it
**Then** the imported benchmark metadata is preserved as structured evidence and remains read-only in downstream workflows

**Given** an uploaded benchmark environment that is unsupported or incomplete
**When** I upload it
**Then** the system rejects it with an explicit failure reason

### Story 29.3: Flag Missing Constraints in Uploaded Models

As a human operator, I want the system to flag uploaded models that have no constraints, mates, or joints so that I can spot potentially ambiguous or underspecified assemblies before they are treated as usable benchmark or input objects.

**Acceptance Criteria:**

**Given** an uploaded CAD model without explicit constraints, mates, or joints
**When** it is imported
**Then** the system marks the model as unconstrained and surfaces that state in the episode artifacts and UI

**Given** an uploaded benchmark environment or input object with intended motion but no recoverable constraint metadata
**When** the model is reviewed
**Then** the system raises an explicit warning or rejection reason instead of silently assuming a valid motion contract

**Given** an uploaded model that is intentionally free or unconstrained
**When** it is accepted
**Then** the unconstrained state is still persisted explicitly rather than inferred later from simulation behavior
