---
stepsCompleted:
  - step-01-init
  - step-02-discovery
  - step-02b-vision
  - step-02c-executive-summary
  - step-03-success
  - step-04-journeys
  - step-05-domain
  - step-06-innovation
  - step-07-project-type
  - step-08-scoping
  - step-09-functional
  - step-10-nonfunctional
  - step-11-polish
inputDocuments:
  - specs/desired_architecture.md
  - specs/architecture/primary-system-objectives.md
  - specs/architecture/agents/overview.md
  - specs/architecture/agents/roles.md
  - specs/architecture/agents/handover-contracts.md
  - specs/architecture/agents/artifacts-and-filesystem.md
  - specs/architecture/agents/tools.md
  - specs/architecture/distributed-execution.md
  - specs/architecture/CAD-and-other-infra.md
  - specs/architecture/evals-architecture.md
  - specs/architecture/agent/reward-architecture.md
  - specs/architecture/simulation-and-dod.md
  - specs/architecture/observability.md
  - specs/architecture/fluids-and-deformables.md
  - specs/architecture/electronics-and-electromechanics.md
  - specs/architecture/workbenches.md
  - _bmad-output/project-context.md
  - _bmad-output/planning-artifacts/epics.md
  - docs/index.md
  - docs/project-overview.md
  - docs/architecture.md
  - docs/backend-reference.md
  - docs/api-contracts.md
  - docs/data-models.md
  - docs/development-guide.md
  - docs/deployment-guide.md
  - docs/component-inventory.md
  - docs/spec-coverage.md
  - docs/source-tree-analysis.md
  - docs/project-scan-report.json
  - docs/project-parts.json
  - specs/business-usecase.md
  - specs/dataset-generation.md
  - specs/frontend-specs.md
  - specs/integration-tests.md
  - specs/todos.md
documentCounts:
  briefCount: 0
  researchCount: 0
  brainstormingCount: 0
  projectDocsCount: 35
classification:
  projectType: backend-first agentic engineering platform with a secondary React inspection dashboard
  domain: AI-assisted mechanical/electromechanical engineering, CAD, physics simulation, benchmark generation, and dataset tooling
  complexity: very high
  projectContext: brownfield
workflowType: prd
---

# Product Requirements Document - Problemologist-AI

**Author:** Max
**Date:** 2026-03-20

## Executive Summary

Problemologist-AI is an open-source engineering platform for solving real engineering problems end to end. A human engineer defines the benchmark as the solution verification setup, and the system returns a verified design solution to that benchmark. Scope remains bounded by the human engineer. The platform starts with mechanical engineering, extends into electromechanical systems, and can optionally cover fluids. The primary users are hardware engineers, product teams, and builders who need verified designs; the secondary users are LLM researchers and companies that need high-signal engineering benchmarks, solution traces, and training data. The platform addresses two gaps at once: current LLMs are not yet reliable enough to solve engineering work without strict verification, and the field lacks open, high-quality datasets that reflect real design, validation, and review workflows. The workflow also preserves rendered CAD and simulation previews so humans can inspect what was actually built before accepting the result.

Problemologist-AI combines solution generation with an evidence-preserving dataset loop. The solution workflow takes a benchmark, generates candidate concepts, validates them against physics, manufacturability, cost, weight, and review constraints, and iterates until the artifact is acceptable. Benchmark-owned motion is authored explicitly by the benchmark designer and then validated against evidence; the system does not apply a minimum-DOF simplification rule to benchmark fixtures. In parallel, the system preserves the benchmarks, reasoning traces, solved examples, reviewer feedback, and optimization notes needed to train and evaluate future engineering-capable models. The result is both a practical engineering tool and a reusable research infrastructure.

### What Makes This Special

Problemologist-AI does not treat dataset generation as a side effect. It treats solving and data production as a single closed loop. The product is differentiated by the fact that every engineering attempt can become reusable training signal: the benchmark, the solution, the failure modes, the review comments, and the optimized but unused alternatives remain available as open-source artifacts.

The core insight is that reliable engineering assistance depends on strict feedback loops, not just bigger models. Real engineering output requires physics-backed validation, manufacturability checks, and reviewer-gated iteration. Those same gates create the dataset that makes future models better. That dual use is the moat: solve the task now, and turn the work into training material for the next system.

This is not a generic agent, not a benchmark-only project, and not a design sandbox. It is a strict engineering system with open-source outputs and a dataset engine attached to it.

## Project Classification

- Project Type: backend-first agentic engineering platform with a secondary React inspection dashboard
- Domain: AI-assisted mechanical/electromechanical engineering, CAD, physics simulation, benchmark generation, and dataset tooling
- Complexity: very high
- Project Context: brownfield

## Success Criteria

### User Success

- A human engineer can define a bounded mechanical or electromechanical problem, review the plan, preview the CAD model and simulation evidence, and receive a verified design package without manual artifact repair.
- The user can tell why a candidate solution passed or failed from the trace, review, rendered preview artifacts, and simulation evidence alone.
- The workflow reduces manual iteration needed to reach a reviewable solution.
- The user can create benchmark drafts, accept or reject plans, and stop a live run from the workspace without losing episode context.
- The user can watch an active agent's output and reasoning in real time, and can correct a live run by steering the agent with selected CAD or code context instead of restarting the episode.

### Business Success

- The platform reliably solves bounded engineering problems that are useful in real workflows, starting with mechanical tasks and extending to electromechanical tasks.
- Every completed run produces both a usable solution and a reusable benchmark/dataset artifact bundle.
- Researchers and companies can reuse traces, benchmarks, solved examples, and review outcomes without reconstruction.

### Technical Success

- Success is fail-closed: missing artifacts, invalid schemas, stale manifests, or missing review evidence never pass as clean success.
- Metrics are derived from persisted artifacts and traces, not synthetic fixtures or fallback states.
- When render evidence exists, reviewers inspect actual media and preview artifacts before approval.
- Runs remain reproducible across seeds and runtime jitter where robustness is expected.

### Measurable Outcomes

- Fast evals: markdown validity reaches 95% on the first prompt, code validity reaches 90% on average tool calls, build123d code validity reaches 95%, and output YAML validity reaches 95%.
- AI benchmark generation: on a 10-attempt sample for a benchmark family, at least 8 AI-generated benchmark attempts are usable without human correction.
- AI solution generation: on a 10-attempt sample for a solution family, at least 8 AI-generated solution attempts are usable without human correction.
- Review quality: AI-generated benchmark and solution reviews explain the acceptance or rejection reason clearly enough for a human to follow, and unclear reviews can be rejected as insufficiently explainable.
- Benchmark generation: benchmark planner passes reviewer scrutiny in 80% of cases; benchmark coder reaches 95% physical validity after 30 turns and three reviewer submissions.
- Engineering solving: the engineer reaches the goal within 30 tool calls and three simulation attempts, with first/second/third submission pass rates of 70%, 85%, and 95%.
- Scope gate: Phase 2 electromechanical work and Phase 3 fluids work do not begin until the core solver reaches at least 80% success on a mechanics-only eval dataset of at least 10 demo problems, with the suite weighted toward gravity-driven rigid-body problems, on repeated evaluation runs.
- Robustness: if one simulation passes, at least 70% of runtime-jitter variations also pass.
- Manufacturability: manufacturability checks pass in 70% of validation/pricing calls and 90% of expected simulation/submission calls, improving to 95% and 97% on second and third attempts.
- Review quality: reviewers reject inconsistent, infeasible, ambiguous, or over-actuated solutions at the architecture thresholds, and canonical checklist keys/values match seeded ground truth in at least 95% of cases.
- Dataset readiness: completed episodes include all mandatory artifacts, traces, validation markers, and review evidence required for training readiness.

## Product Scope

### MVP Strategy & Philosophy

Phase 1 should launch as a problem-solving MVP with debugging-first instrumentation. The first useful outcome is a verified episode that solves a bounded pure-mechanics task, produces a dataset row, and can be diagnosed when it fails. Phase 1 should optimize for correctness, replayability, and triage speed rather than platform breadth.

Benchmark difficulty is tiered by complexity level. Level 0 smoke tests exist only to verify baseline solve capability, and the Phase 1/MVP target is up to about 5 meaningful, manufacturable, realistic parts. The detailed ladder lives in `specs/architecture/evals-architecture.md`.

Phase 1 stays in rigid-body mechanics. Electromechanical and fluids capabilities are deferred until the mechanics eval gate is met and reproducible, so the team does not widen scope before the core solver is credible. The Phase 1 user interface is intentionally simple: it supports benchmark draft creation, plan accept/reject, preview inspection, and stop/interrupt controls, but not the later in-browser multiphysics visualization or advanced prompt steering.

### Resource Requirements

A lean core team is sufficient for Phase 1 if the team has one owner for the agentic/environment loop and one owner for infra/CAD/simulation. Explicit capacity must be reserved for observability, failure triage, and replayable debugging, because the environment is expensive to debug without those controls.

### MVP Feature Set (Phase 1)

**Core User Journeys Supported:**

- Mechanical engineer receives a verified design they can trust.
- Mechanical engineer inspects validation and simulation.
- Researcher or company exports solved episodes for training or evaluation.
- Dataset operator or curator keeps the corpus usable.
- Developer or maintainer can reproduce and diagnose failures quickly.

**Must-Have Capabilities:**

- Session and episode isolation with explicit lineage.
- Sequential role-specific agents with handoff artifacts.
- Bounded mechanical benchmark generation.
- Bounded mechanical solving end to end.
- Plan/review/validate/simulate loop.
- Render and media inspection for benchmark and solution preview artifacts.
- Basic workflow controls for benchmark draft creation, plan accept/reject, preview inspection, and stop/interrupt.
- Live agent output and reasoning traces: users can inspect the agent's output in real time so they can catch logical errors early.
- Manufacturability and cost checks.
- Fail-closed terminal states.
- Dataset persistence and export of complete episodes.
- Open-source artifact bundles.
- Batch seed variation for repeatable data generation.
- Structured traces, logs, and failure classification for every episode.
- Replayable failed runs with enough context to reproduce the issue.
- Deterministic terminal reasons and error codes.
- Debuggability aligned to documented, real application behavior, not hidden fallback paths.

### Debuggability Requirements (Phase 1)

- Runtime behavior must align with real application features and documentation.
- Feedback loops must surface actionable state and failure reasons early enough to support iterative debugging.
- Fallback paths must be explicit, logged, and visible in the failure reason.
- Logs and traces must make failures reproducible without reconstruction.
- Deterministic terminal reasons must distinguish success, refusal, invalid input, missing artifact, unsupported behavior, and simulation failure.
- Failed episodes must remain replayable from persisted artifacts and traces.

### Phase Boundary

Phase 1 is limited to pure rigid-body mechanics. Electromechanical and fluids work remain out of scope until the scope gate in Success Criteria is met and reproducible on repeated eval runs. Phase 2 and Phase 3 are the post-gate expansion path, not parallel tracks.

### Post-MVP Features

**Phase 2 Growth (post-gate only):**

- Electromechanical tasks with powered mechanisms and circuit validation.
- Robustness and jitter-heavy evaluation.
- Richer dataset packaging and consumer tooling.
- Advanced steerability for active runs: attach selected CAD faces, code spans, file references, and media to prompts, and tune the agent stack to consume that context.
- Optional collaboration features if they become necessary.

**Phase 3 Expansion (post-gate only):**

- Fluids, deformables, and broader multiphysics.
- Advanced visualization: in-browser FEM mesh, fluids, actuators, and electronics rendering with interactive inspection, pan/zoom, stress/strain field overlays, and in-scene steering.
- Broader benchmark families and more agent roles.
- Open-source framework polish.
- External integrations and ecosystem features.
- Platform hardening if multi-user needs emerge later.

### Non-Goals

- Auth and multitenancy are out of scope for Phase 1.
- Generic platform features that do not improve verified episode quality are out of scope.
- Broad collaboration workflows are out of scope until the environment loop is stable.

### Risk Mitigation Strategy

**Technical Risks:** keep the first release to a narrow mechanical task class, keep the agent chain short and sequential, fail closed on invalid artifacts, keep preview simulation separate from proof simulation, use debuggability as a first-order constraint, and do not widen scope into electromechanical or fluids work before the mechanics gate is satisfied.

**Market Risks:** make the MVP useful to a single human engineer first, ensure every solved episode becomes a dataset row, and prove training-data value with concrete exports and reproducibility.

**Resource Risks:** if bandwidth gets tight, cut collaboration and platform polish before cutting the environment loop, validation gates, dataset persistence, or debug tooling.

## User Journeys

### Journey 1: Mechanical Engineer Receives a Design They Can Trust

A human mechanical engineer has a bounded physical problem: a part, mechanism, fixture, or machine that needs to work in the real world. They define the problem in terms of load, size, cost, material limits, and expected behavior. The system returns a validated design package instead of a speculative sketch.

The engineer reviews the plan, rendered CAD preview, simulation preview, and manufacturability checks as a single engineering artifact. If the design passes, the engineer can move forward without manual cleanup. If it fails, the failure is specific enough to revise the brief and try again.

This journey reveals requirements for validated design output, traceable reasoning, manufacturability checks, and clear pass/fail explanation.

### Journey 2: Mechanical Engineer Inspects Validation and Simulation

The same engineer does not trust a pass blindly. They want to inspect the validation setup, see how the benchmark was defined, view the rendered CAD model and simulation preview, and understand how the simulation behaved in the modeled environment.

This is the trust-building moment. The engineer checks the objective zones, declared motion contract, constraints, randomization, and the actual simulation behavior to decide whether the product's answer is defensible. If the run exposes a flaw, they tighten the brief and rerun. If it holds up, they can sign off on the design with confidence.

This journey reveals requirements for inspectable validation setup, simulation preview or evidence, real-environment behavior, and a revision loop when the simulation exposes a problem.

### Journey 3: Researcher or Company Reuses the Dataset

A researcher or company building engineering-capable LLMs wants the data this software produces to be directly useful for training and evaluation. They are not looking for a one-off design result. They want complete, structured episodes with traces, decisions, solutions, and lineage metadata that can flow into a training or RL pipeline.

They export solved episodes, filter by benchmark family or seed coverage, and check that the schema is stable enough to automate ingestion. If any episode is missing artifacts or has invalid lineage, the data is not useful to them.

This journey reveals requirements for dataset export, schema stability, lineage metadata, reproducibility, and RL-ready packaging.

### Journey 4: Dataset Operator or Curator Keeps the Corpus Usable

A human dataset operator or curator watches the generated corpus over time. They review coverage across problem families, remove invalid or incomplete data, and prioritize underrepresented seeds so the dataset stays balanced and useful.

Their work is not about solving engineering tasks. It is about keeping the open-source corpus trustworthy and training-ready. They need lineaged evidence, quality checks, and cleanup controls strong enough to separate a genuinely useful episode from a superficially successful but unusable one.

This journey reveals requirements for dataset cleaning, coverage management, seed prioritization, failure classification, and operational observability.

### Journey 5: Human Engineer Steers a Live Run

A human engineer notices a wrong local choice in a live run. They select the relevant CAD entity, such as a face, a part/body, or a subassembly, or they select a code range, attach it to a corrective prompt, and the next agent turn uses that context to produce a more targeted edit without restarting the episode. While the agent is working, they can see its output and reasoning in real time and stop execution when it goes off track.

This journey reveals requirements for live steering, selection-mode switching, and auditable prompt context.

### Journey Requirements Summary

- The primary human user is a mechanical engineer, not a benchmark designer persona.
- Benchmark setup is part of validation evidence, not a separate human role, and any benchmark fixture motion must be explicitly documented and validated.
- The product must support trust through inspectable evidence, not just output generation.
- Dataset consumers need structured, reproducible, training-ready exports.
- Dataset operators need cleaning, coverage, and lineage controls.
- Internal agent roles are implementation details and should not be written as user journeys.

## Domain-Specific Requirements

### Compliance & Regulatory

- The product is not a certification, compliance, or sign-off system.
- Human engineer judgment remains the authority for real deployments.
- The system must preserve provenance and evidence so decisions can be audited, but it must not imply external certification-grade guarantees.

### Technical Constraints

- The primary domain is bounded mechanical engineering; benchmark-owned fixtures belong to the validation setup, not engineer-owned solution hardware, and may be fixed, partially constrained, motorized, or fully free when the benchmark contract explicitly declares that behavior.
- Electromechanical support is required when power, wiring, motors, or circuits are part of the task.
- Fluids and deformables are optional extensions and must use the correct backend and evidence path when enabled.
- Supported workbenches are finite and explicit: `CNC`, `injection molding`, and `3D printing`.
- Supported mechanisms and capabilities must stay explicit and finite; unsupported behaviors should fail closed.
- The human engineer must be able to choose simulation fidelity per task: rigid-body simulation for fast iteration, or FEM when slower but more precise structural response is required.
- Final solutions must be manufacturable at the requested production volume, not just mechanically plausible in simulation.
- Cost validation must be volume-aware: setup cost and variable cost both matter, so the preferred manufacturing method can change with quantity.
- The system must enforce cost, weight, size, and form-factor constraints together rather than treating them independently.
- At low quantities, a method with higher per-part cost but lower setup cost may be correct; at high quantities, a higher-tooling method with lower variable cost may be correct.
- Example rule: a small batch can favor CNC, while large batches can favor injection molding if the geometry and requirements fit.
- Electromechanical tasks require circuit validity before expensive physics simulation proceeds.
- Benchmark-owned fixtures and benchmark-owned electronics are read-only context unless the benchmark explicitly declares engineer interaction through its verification setup.
- Moving benchmarks require dynamic evidence for approval; static validation preview is context, not proof of motion behavior.
- Benchmark-owned fixtures may be drilled when the benchmark verification setup explicitly allows it, and those drilling operations must be priced; this is the mechanism for attaching or constraining parts to an environment, such as fixing a machine to the floor or wall.
- Benchmark motion is validated against the declared motion contract, not minimized for convenience.
- Fluids, deformables, and stress-aware tasks require Genesis for final validation, while MuJoCo remains the preview path.
- Benchmark-owned fixtures, electronics, and motion context are read-only environment inputs, not engineer-owned outputs.

### Integration Requirements

- Workflow orchestration remains coherent across planning, validation, review, and retrieval.
- Heavy validation and simulation expose persisted status and results without losing episode context.
- Observability must preserve session, episode, simulation, review, and seed lineage.
- The UI must expose validation evidence, simulation preview playback, benchmark setup inspection, simple workflow controls, and live agent output and reasoning traces.
- The UI must expose removable context cards for selected faces, parts/bodies, subassemblies, and code ranges, and steering actions must be reflected in persisted traces.
- Dataset generation must support reproducible export, seed prioritization, and filtering of invalid or incomplete episodes.

### Risk Mitigations

- Fail closed on missing manifests, invalid schemas, stale evidence, unsupported components, or invalid circuits.
- Keep validation preview distinct from final simulation proof.
- Require visual evidence inspection whenever renders exist.
- Exclude integration-only runs and known-corrupted windows from training data.
- Do not use single-unit price as the only cost signal when target quantity changes the economics of the design.
- Do not accept a design that passes simulation but cannot be manufactured within the requested volume, weight, or size constraints.
- Avoid exporting to high-fidelity simulation paths unless they are needed to validate the physical phenomenon being tested; cheaper preview paths speed up iteration, lower business cost, and make debugging faster.
- If a behavior is not reflected in the application and its documentation, it is not stable enough to serve as a debugging target in Phase 1.
- Do not describe the product as a general-purpose engineering automation system; it is bounded, evidence-backed, and human-scoped.

## Innovation & Novel Patterns

Problemologist-AI is a human-bounded engineering copilot for mechanical engineering, with electromechanical support and later fluids, that works more like `Cursor` or `Claude Code` for physical engineering than like a traditional CAD or simulation tool. The novelty is the closed loop: it solves a bounded engineering task, strictly validates that the proposed solution actually works, and preserves the full episode as reusable benchmark and training data.

### What Is Novel

- It targets a large class of engineering work that current AI cannot reliably handle yet, but only within a human-defined scope.
- It couples mechanical validation, manufacturability, cost/volume economics, and evidence inspection into one workflow.
- It extends into electronics only when those constraints are part of the same problem, rather than treating electronics as a separate toolchain.
- It produces training-ready mechanical engineering data and benchmark episodes as a first-class output.
- It keeps preview and proof separate, so fast iteration is not confused with final validation.

### Market Context

- Existing AI coding tools help with software workflows, but they do not solve physical engineering tasks.
- Existing CAD and simulation tools validate designs, but they do not generate reusable ML training episodes from the validation process.
- Existing electronics datasets are limited and usually not coupled to mechanical behavior.
- The gap is not another generic assistant. It is a system that can solve bounded engineering tasks and generate high-signal data from the verified solution path.

### Validation Approach

- Start with bounded mechanical tasks where success is explicit.
- Require simulation-backed evidence, manufacturability checks, and human review before acceptance.
- Extend to electromechanical tasks only when circuit validity and mechanical validation both hold.
- Measure solve rate, reproducibility, artifact completeness, and downstream dataset usefulness.

### Risks and Boundaries

- Avoid framing the product as general engineering autonomy.
- Keep human-scoped boundaries explicit.
- Fail closed on missing evidence, invalid schemas, unsupported mechanisms, or incomplete episodes.
- Treat dataset generation as a byproduct of verified work, not as a substitute for verified work.

## Project-Type Specific Requirements

### Project-Type Overview

Problemologist-AI is a simulation-backed RL environment for engineering tasks and benchmark generation. The core product is a family of sequential, role-specific environments where each agent observes its own handoff artifacts, takes CodeAct-style read/write/tool actions, receives role-specific rewards, and terminates through strict fail-closed gates. The environment exists to produce verified engineering solutions and reusable training data.

### Environment Contract

- Episodes are bounded units of work with explicit state and persisted lineage.
- Lineage means the reconstructable chain that links a run to its seed task, parent run, agent role, revision history, artifacts, reviews, and outputs, so the episode can be replayed and analyzed later.
- Each agent role has its own observation set, allowed CodeAct-style actions, and reward signal.
- In the current architecture, roles are executed sequentially and their outputs flow into the next role’s environment; the exact count of roles is implementation detail and may evolve.
- Terminal states are driven by validation and review gates, not free-form conversation outcomes.
- The top-level workflows are benchmark generation and engineering solving, but each workflow is decomposed into role-specific environments rather than treated as one monolithic loop.

### Technical Architecture Considerations

#### Observation and action space

- The environment must expose the same artifact surfaces the agents use in the workflow: plan docs, YAML handoffs, renders, simulation outputs, review manifests, journals, and code.
- Agent actions are restricted to CodeAct-style reading, writing, tool invocation, and handoff submission within the files and tools the role is allowed to touch.
- The tooling must be reproducible and inspectable so episodes can be replayed and analyzed later.

#### Reward and terminal gates

- Reward should align with the PRD’s own success criteria, especially the user, business, technical, and measurable outcomes already defined earlier in this document.
- Reward is role-specific, not one global scalar. Planners, coders, reviewers, and benchmark-generation roles each optimize different quality gates.
- Success means a verified, manufacturable, simulation-passing solution within benchmark constraints.
- Failure means invalid schema, missing artifacts, unsupported mechanisms, invalid circuits, or simulation failure.

#### State persistence and lineage

- Every episode must persist traces, seed lineage, artifacts, and review decisions.
- Lineage should include parent/child episode links, source seed, role outputs, revision numbers, and terminal reason.
- Dataset rows must be reconstructable from persisted artifacts, not only from prompts or transcripts.
- Integration-test runs and corrupted historical windows must be excluded from training data.

#### Simulation and validation interface

- Fast preview and heavy physics simulation are separate environment steps.
- Validation is part of the environment feedback loop, not a cosmetic UI check.
- Electromechanical and fluids-specific validation paths remain gated by the corresponding architecture contracts already established elsewhere in this document.

#### Workflow roles

- Planner, coder, and reviewer roles are policy layers acting inside the environment.
- The environment must preserve a clear distinction between benchmark-definition episodes and engineering solving episodes.
- The React UI is an inspection surface for environment state and evidence, not the source of truth for workflow state.

### Implementation Considerations

- Keep auth and multitenancy out of scope until the environment loop is stable.
- Optimize for episode fidelity, replayability, and training usefulness rather than generic platform features.
- Make the environment friendly to batch generation and seed variation so dataset coverage can grow.
- Keep terminalization, review gates, and artifact persistence fail-closed.
- The environment should support a small, role-decomposed agent chain rather than a single generic solver.

### Boundary Statement

- This is not a SaaS backend first and not a generic API product.
- It is a simulation-backed RL environment for engineering tasks and benchmark generation.
- The primary deliverable is a verified episode and its reusable dataset artifacts.

## Functional Requirements

A benchmark is the solution verification setup for a bounded engineering problem. The system uses the benchmark to verify whether a design solution works.

### Benchmark Definition and Verification

- FR1: Human engineers can define a benchmark as a solution verification setup for a bounded engineering problem.
- FR2: Human engineers can set the benchmark goals, forbidden zones, build zone, allowed interactions, and randomization.
- FR3: The system can represent benchmark-owned fixtures and benchmark-owned electronics as read-only context unless interaction is explicitly allowed.
- FR4: The system can represent allowed attachment and drilling points, plus explicit benchmark fixture motion contracts, in the benchmark setup.
- Benchmark-owned fixtures, moving parts, and electronics are read-only validation context; they may be fixed, partially constrained, motorized, or fully free when the benchmark contract declares that behavior, and they are not counted in engineer manufacturability or cost validation.
- FR5: The system can validate that a benchmark is solvable and reject ambiguous, impossible, or incomplete setups.
- FR6: The system can pass benchmark setup artifacts into the solution workflow.

### Solution Delivery

- FR7: Human engineers can receive verified design solutions to a benchmark.
- FR8: Human engineers can revise a failed solution and try again against the same benchmark.
- FR9: The system can support benchmark-definition and solution workflows as separate but connected episode types.
- FR10: The system can preserve handoff artifacts between benchmark setup and solution work.
- FR11: The system can support reasoned accept/reject decisions for benchmark and solution outputs.

### Simulation and Physics

- FR12: Human engineers can choose rigid-body preview simulation or higher-fidelity FEM when needed.
- FR13: The system can require circuit validity before electromechanical simulation.
- FR14: The system can support fluids, deformables, and stress-aware validation when selected.
- FR15: The system can preserve simulation and render evidence, including preview-ready image and video artifacts, for later inspection.

### Manufacturability and Costing

- FR16: Users can configure the prices used for costing.
- FR17: The system can evaluate whether a solution is manufacturable at the requested production volume.
- FR18: The system can evaluate setup cost and variable cost separately.
- FR19: The system can evaluate weight, size, and form-factor constraints together.
- FR20: The system can compare manufacturing options across quantities and choose the appropriate one.
- FR21: The system can include COTS parts in cost and manufacturability evaluation.

### Solution Quality

- FR22: The system can identify unnecessary or unjustified degrees of freedom in a solution.
- FR23: The system can prefer the valid candidate with fewer unnecessary degrees of freedom, actuators, and parts when multiple solutions satisfy the benchmark.
- FR24: The system can flag over-actuated solutions and solutions with unnecessary degrees of freedom during review.

### Data, Replay, and Debugging

- FR25: The system can persist complete episode traces, artifacts, and lineage.
- FR26: The system can export solved episodes and benchmarks as training-ready dataset rows.
- FR27: Researchers and companies can use completed episodes for training or RL.
- FR28: Dataset operators can exclude episodes that fail schema validity, completeness, or lineage integrity checks.
- FR29: Dataset operators can manage coverage by seed and problem family.
- FR30: The system can generate repeatable episode variants from different seeds.
- FR31: The system can expose logs, traces, and terminal reasons for each episode.
- FR32: Maintainers can reproduce and diagnose failed episodes from persisted artifacts and traces.
- FR33: The system can surface explicit fallback behavior and failure classification.
- FR34: The system can compare executed runtime paths against the documented supported feature set and flag mismatches as validation failures.
- FR35: The system can keep failed episodes replayable from persisted artifacts and traces.

### Steerability and Prompt Control

- FR36: The system can accept corrective steering prompts during an active run with attached structured CAD or code context.
- FR37: The system can let users switch CAD selection mode between faces, parts/bodies, and subassemblies, and preserve the selected entity in the prompt payload.
- FR38: The system can preserve steering context, selection metadata, and resulting edits in traces and replay artifacts.
- FR39: The system can generate preview-ready image, video, netlist, and schematic artifacts for simulation-family runs and expose them to authorized viewers.
- FR40: The system can render advanced simulation artifacts in-browser with interactive inspection and in-scene selections for steering.

## Non-Functional Requirements

Security, accessibility, and broad scalability remain out of scope for Phase 1 because auth/multitenancy is out of scope and the product is a controlled engineering environment.

### Performance and Compute Efficiency

- The benchmark-verification and solution-revision loop shall complete in under 15 minutes at the 95th percentile for the standard Phase 1 benchmark suite.
- Static preview artifacts shall be available for 100% of benchmarks that produce render evidence before final proof artifacts are accepted.
- Benchmarks that do not declare a physics mode shall not trigger heavy physics, FEM, or fluid evaluation.
- Planning and review requests shall return an initial response within 2 seconds at the 95th percentile while heavy evaluation is pending.
- Repeated validation of the same unchanged revision shall produce 0 new heavy evaluations and shall return the previously persisted result or a no-op status.

### Local CLI Agent Flexibility

- The system shall support an optional local, headless CLI agent path for development and eval-debug runs, so benchmark work can be executed from the workspace through a command-line agent instead of the default controller-backed path, and the CLI agent's outputs shall be accepted as authoritative benchmark or engineering decisions when they satisfy the same workspace, prompt, and artifact-validation contracts as the controller-backed runtime.
- The supported local agent implementations shall be pluggable and may include Codex CLI, Claude Code CLI, Gemini CLI, OpenHands, or equivalent CLI coding agents, provided they can operate within the workspace contract and produce the required artifacts.
- The local CLI launcher shall be role-agnostic at process start: it shall not require the runtime to inject `AGENT_NAME`, and any role-specific helper that needs a planner variant shall infer it from the materialized workspace files rather than from the launcher contract.
- The local CLI path shall be optional and non-exclusive: it shall coexist with the default controller-backed runtime and external provider-based execution, and it shall not require an additional model-provider hop from the Problemologist runtime for every debugging loop, even if the selected CLI agent proxies to upstream model APIs internally.
- The system shall fail closed when the selected CLI agent is unavailable, misconfigured, or cannot satisfy the workspace, prompt, or artifact-validation contracts, rather than silently switching to another agent or provider.

### Reliability and Fail-Closed Behavior

- Any request with missing artifacts, invalid schemas, stale manifests, unsupported mechanisms, invalid circuits, or missing review evidence shall end in terminal failure with no success state.
- Partial output, inferred success, and silent fallback shall never be classified as success.
- Configuration mismatches, capacity limits, and retry exhaustion shall return deterministic terminal reasons and a retriable/non-retriable classification.
- 100% of terminal episodes shall include a concrete terminal reason and failure classification.

### Observability, Replayability, and Debuggability

- 100% of completed episodes shall be reconstructable from persisted traces, logs, artifacts, and lineage IDs without rerunning the solver.
- Every user session, episode, simulation run, review, COTS query, and seed record shall have joinable identifiers in persisted records and exports.
- Every tool call, review decision, media inspection action, and error event shall emit a machine-readable record and remain available for the debugging retention window.
- Every failed episode shall include a replay bundle that reproduces the failure state in replay mode.
- Reasoning and tool-call traces shall be retained for the full episode lifetime and remain accessible in replay views.
- When render evidence exists, the review record shall identify the exact latest-revision media artifact that was inspected.

### Data Integrity and Reproducibility

- Episode lineage and seed lineage shall persist across benchmark generation and engineering execution for 100% of exported episodes.
- Every dataset export shall include the source episode ID, revision hash, and artifact hash.
- Training dataset exports shall exclude integration-test runs and known-corrupted episodes.
- Handoff artifacts shall validate against the same schema at creation, storage, review, and export time; any schema drift shall reject the episode.
- Backups shall restore persisted run metadata and artifact references with 100% integrity in periodic restore tests.

### Explainability and UI Responsiveness

- While a run is active, the UI shall stream the agent's output and reasoning traces in real time when available, and any interrupt or stop action shall be persisted as an explicit episode event.
- AI-generated benchmark and solution reviews shall include a human-readable rationale and explicit accept/reject reason code; if the rationale is missing or unclear, the review shall be marked insufficiently explainable rather than accepted.

### Integration and Boundary Integrity

- Untrusted generated code shall not mutate persistent workflow state directly; all state changes shall be mediated by validated artifacts and recorded actions.
- Concurrent heavy evaluation requests for the same episode shall either start, return a deterministic busy status, or fail with a terminal reason within the request timeout.
- Benchmark-owned artifacts shall remain read-only during engineering runs, and engineer-owned outputs shall remain separate from benchmark context.
- 100% of accepted solutions shall include a final proof artifact that is distinct from any preview artifact.
- Validation, review, and export artifacts shall round-trip through storage and retrieval without loss of required fields or schema drift.
