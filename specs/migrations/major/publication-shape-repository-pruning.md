---
title: Publication Shape Repository Pruning Migration
status: work in progress
agents_affected:
  - benchmark_planner
  - benchmark_plan_reviewer
  - benchmark_coder
  - benchmark_reviewer
  - engineer_planner
  - electronics_planner
  - engineer_plan_reviewer
  - engineer_coder
  - electronics_reviewer
  - engineer_execution_reviewer
  - skill_agent
  - cots_search
added_at: '2026-04-11T00:00:00Z'
---

# Publication Shape Repository Pruning Migration

<!-- Migration in progress. -->

## Purpose

This migration defines the conference-submission shape of Problemologist-AI.
The target is the smallest source bundle that still reproduces the paper's
benchmark-generation, engineer-solution, simulation, render-evidence, and
paper-figure claims from a clean checkout.

The source of truth for the full runtime remains
`specs/desired_architecture.md` and the architecture files beneath
`specs/architecture/`. This migration only answers what belongs in the
submission bundle, what is development-only bulk, and what is claim-driven
retained surface.

The rule is simple: if the final camera-ready paper does not cite a capability
as part of the evaluated result set, the capability does not belong in the
publication bundle. Future work, debugging convenience, maintenance helpers,
compatibility shims, and duplicate presentation surfaces are not publication
worthy.

The hard cutoff is Epic 7 in `_bmad-output/planning-artifacts/epics.md`.
Anything whose first meaningful claim appears in Epic 8 or later is
out-of-bundle for the conference submission, even if the repository currently
implements it, documents it, or tests it. That includes the technical-drawing
contract, the electromechanical stack, fluids/FEM/stress branches, steerability,
and advanced UI visualization.

The only retained drawing behavior is the ordinary full geometric-plan path
already needed to reproduce Epic 7. Off/minimal drafting variants and
preview-only companions are not publication surfaces.

This migration trims feature-specific branches and devops shells. It does not
trim useful rendering, CLI-provider, physics-backend, or handoff/validation
abstractions.

## What Is Not Worth Including

The conference bundle must not ship the following feature families unless the
final paper explicitly uses them as evaluated claims:

01. The secondary operator UI and its generated client bundle.
02. The standalone marketing website mirror.
03. Duplicate paper drafts, compiled exports, and document logs.
04. Experimental performance probes and syntax-check harnesses.
05. Legacy compatibility mirrors and generic wrapper scripts.
06. Skill-training autopilots, journalling compressors, and promotion loops.
07. Steerability, drafting, local SDK recreation, and other internal tuning
    services.
08. Long-tail observability events that only exist for debugging or training.
09. Generated dataset corpora and non-paper seed families.
10. Broad frontend, eval, and integration coverage that is not paper-critical,
    including Temporal/devops coverage and the majority of unsupported
    INT-001 through INT-180 cases.
11. Later-epic physics and product branches, including electronics,
    fluids/FEM, technical drawing, and advanced visualization.
12. Internal documentation that explains the development tree rather than the
    conference artifact.
13. The technical-drawing contract, drafting-mode gates, and display-only
    companion scripts.
14. Any agent, helper, or test family whose only real claim is Epic 8 or later
    in `_bmad-output/planning-artifacts/epics.md`.
15. Non-local devops stacks, Temporal orchestration helpers, and old-style
    ReAct-only tool wrappers that merely duplicate script-backed commands.

## Feature Removal Matrix

### Presentation surfaces

`frontend/` is operator-facing, not paper-facing. The paper claims the backend
runtime and the evidence it emits, not the dashboard.

Trim the entire tree:

- `frontend/components.json`
- `frontend/eslint.config.js`
- `frontend/vitest.config.ts`
- `frontend/vite.config.ts`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/tailwind.config.js`
- `frontend/postcss.config.js`
- `frontend/index.html`
- `frontend/openapi.json`
- `frontend/README.md`
- `frontend/public/favicon.svg`
- `frontend/src/App.tsx`
- `frontend/src/App.css`
- `frontend/src/index.css`
- `frontend/src/main.tsx`
- `frontend/src/context/**`
- `frontend/src/components/layout/**`
- `frontend/src/components/workspace/**`
- `frontend/src/components/visualization/**`
- `frontend/src/components/Chat/**`
- `frontend/src/components/ui/**`
- `frontend/src/pages/**`
- `frontend/src/api/**`
- `frontend/src/lib/**`
- `frontend/src/test/**`
- `frontend/src/assets/**`

The generated TypeScript client and UI-only pages are especially unworthy of
publication inclusion because they exist only to make the dashboard pleasant
to use.

`website/` is a static marketing mirror. It does not participate in the agent
workflow and must be excluded wholesale:

- `website/**`

### Paper artifact duplicates

The academic-submission tree should collapse to one canonical paper source and
the minimal reproducibility inputs that the final paper actually cites.

Keep:

- `docs/academic-submission/final-project-report.tex`
- `docs/academic-submission/paper_benchmark/benchmark_definition.yaml`
- `docs/academic-submission/paper_benchmark/render_figure.py`
- `docs/academic-submission/paper_benchmark/scene_spec.py`
- `docs/academic-submission/paper_benchmark/script.py`

Remove or archive:

- `docs/academic-submission/Foundations of AI - Final Project Report.md`
- `docs/academic-submission/final_project_report.md`
- `docs/academic-submission/final_project_report.pdf`
- `docs/academic-submission/final_project_report.log`
- `docs/academic-submission/Problemologist_AI_Research_Matrix.md`
- `docs/academic-submission/Problemologist_AI_Research_Matrix.odt`
- `docs/academic-submission/export_report.sh`
- `docs/academic-submission/render_sources/README.md`
- `docs/academic-submission/IEEEtranBST2.zip`

If the matrix or render-source notes are still useful internally, they stay in
development history, not in the publication bundle.

### Experimental and probe surfaces

`scripts/experiments/**` is measurement and investigation bulk. It is useful
for maintaining the project, but it is not part of the paper artifact.

Trim the entire tree, including the named probes and their result archives:

- `scripts/experiments/performance/integration-cache-path-stability/**`
- `scripts/experiments/performance/no-compile-experiment/**`
- `scripts/experiments/performance/genesis-scene-reuse/**`
- `scripts/experiments/performance/mujoco-vs-genesis-prerender/**`
- `scripts/experiments/performance/renderer-parallel-modalities/**`
- `scripts/experiments/performance/payload-rotation-envelope-pruning/**`
- `scripts/experiments/performance/simulate-subprocess-reuse/**`
- `scripts/experiments/syntax/**`

The probe entrypoints are not publication-worthy:

- `benchmark_integration_cache_path_stability.py`
- `benchmark_compile_kernels.py`
- `benchmark_same_vs_different_scenes.py`
- `benchmark_randomized_intersection_boxes.py`
- `benchmark_validate_prerender_backends.py`
- `benchmark_parallel_modalities.py`
- `benchmark_fresh_vs_warm_simulate_subprocess.py`
- `probe_dspy_tool_syntax.py`
- `compare_dspy_react_vs_native_tools.py`
- `probe_eval_display_env.py`
- `probe_build123d_construction_signature.py`
- `probe_renderer_launchability.py`

### Legacy compatibility and mirror layers

The publication bundle should not ship compatibility mirrors that exist only
to paper over earlier layouts.

Remove or collapse the following surfaces:

- `worker_light/agent_files/**`
- `controller/agent/mock_llm.py`
- `controller/agent/mock_scenarios.py`
- `controller/agent/provider_tool_call_adapters/minimax_adapter.py`
- `controller/agent/benchmark/render_seed.py`
- `controller/graph/steerability_node.py`
- `controller/api/routes/steerability.py`
- `controller/services/steerability/**`
- `controller/persistence/steering_memory.py`

The generic shell wrappers are also legacy-only and should be trimmed in favor
of the stage-specific launchers:

- `shared/agent_templates/codex/scripts/submit_plan.sh`
- `shared/agent_templates/codex/scripts/submit_for_review.sh`

The stage-specific helpers stay canonical; the generic wrappers are the bulk.

### Local devops and orchestration shells

The publication bundle does not need the non-local orchestration stack or the
Temporal-backed devops shell around it. Preserve the local CLI-provider
workflow and the paper-critical handoff logic, but remove the services and
helper branches that only exist to stand up remote workflow orchestration.

Remove or collapse the following surfaces:

- `controller/temporal_worker.py`
- `worker_heavy/temporal_worker.py`
- `controller/workflows/execution.py`
- `controller/workflows/heavy.py`
- `controller/workflows/simulation.py`
- `controller/workflows/preview.py`
- `controller/activities/execution.py`
- `controller/activities/simulation.py`
- `controller/activities/preview.py`
- `controller/api/ops.py`
- `controller/api/main.py`
  - the `temporal_client` startup/connect/retry path if it exists only for the
    removed orchestration stack
- `controller/middleware/remote_fs.py`
  - `_require_temporal_for_heavy_operation()`
  - `_execute_or_use_existing_workflow()`
  - `_bundle_workflow_id()`
  - `_preview_workflow_id()`
  - the workflow-backed `validate`, `simulate`, `preview`, `verify`, and
    `submit` branches
- `controller/config/settings.py`
  - `temporal_url`
  - any Temporal-only startup wiring
- `worker_light/app.py`
  - the `heavy_temporal_worker_main()` unified-mode bootstrap if it only
    exists for devops convenience
- `evals/logic/stack_profiles.py`
  - the Temporal host/port profile fields and env injection
- `specs/architecture/distributed-execution.md`
- `specs/integration-test-list.md`
- `specs/integration-test-rules.md`

If any of these files still need to exist for a retained local path, only keep
the local-only path. The Temporal-specific retry, workflow-registration, and
backup orchestration code is publication bulk.

### Agent SDK and tool-surface simplification

The publication bundle should not carry a bespoke local agent SDK recreation
or a direct-ReAct tool mirror when checked-in scripts and the existing
CLI-provider harness already define the command surface. Keep the runtime
harness and the script-backed submission helpers; trim the old-style tool
wrappers and provider-specific adapter clones.

Remove or collapse:

- `controller/agent/mock_llm.py`
- `controller/agent/mock_scenarios.py`
- `controller/agent/provider_tool_call_adapters/minimax_adapter.py`
- `controller/agent/tools.py`
  - any direct ReAct-only tool that merely forwards to an existing shell
    script or local helper
  - any `filter_tools_for_agent` branch that exists only to emulate older SDK
    behavior
- `controller/agent/prompt_manager.py`
  - prompt text that teaches removed ReAct tool or old SDK flows
- `config/prompts.yaml`
  - prompt text that teaches removed ReAct-only tools or old SDK flows
- `config/agents_config.yaml`
  - role wiring that only exists to expose removed tools
- `.agents/skills/**`
  - skill prose that teaches the removed tool surface instead of the
    script-backed workflow

### Technical-drawing contract plumbing

The technical-drawing contract is not publication-worthy for this submission
and should be removed end-to-end rather than left dormant behind `off` mode.
The publication bundle keeps the ordinary full geometric-plan path already
used by Epic 7 as the default geometry contract; it does not keep the
off/minimal drafting matrix or the preview-only companion scripts. The trim
needs to hit the runtime helpers, the config gates, the prompt text, the seed
materializers, and the preview renderer together.
In this bundle, "drawing" means the planner must produce a valid geometric
plan that will work; it is not a separate drafting product.

Remove the drafting-mode surface and its helper functions:

- `shared/agents/config.py`
  - `DraftingMode`
  - `technical_drawing_mode`
  - `get_technical_drawing_mode()`
  - `get_drafting_mode()`
- `shared/script_contracts.py`
  - `BENCHMARK_PLAN_TECHNICAL_DRAWING_SCRIPT_PATH`
  - `SOLUTION_PLAN_TECHNICAL_DRAWING_SCRIPT_PATH`
  - `technical_drawing_script_path_for_agent()`
  - `drafting_script_paths_for_agent()`
  - `drafting_render_manifest_path_for_agent()`
  - `planner_role_for_drafting_script_path()`
- `shared/assets/template_repos/benchmark_generator/benchmark_plan_technical_drawing_script.py`
- `shared/assets/template_repos/benchmark_generator/drafting/**`
- `shared/assets/template_repos/engineer/drafting/**`
- `shared/utils/agent/__init__.py`
  - `render_technical_drawing()`
  - `preview_drawing()`
- `worker_heavy/utils/preview.py`
  - `render_technical_drawing()`
- `worker_heavy/utils/handover.py`
  - `_drafting_mode_for_reviewer_stage()`
  - the drafting manifest validation branch inside `submit_for_review()`
- `worker_heavy/utils/file_validation.py`
  - `_technical_drawing_mode_for_node()`
  - `_technical_drawing_script_imports_and_calls_technical_drawing()`
  - `validate_drafting_preview_manifest()`
- `worker_renderer/api/routes.py`
  - the drafting preview route binding for `render_technical_drawing_preview`
- `worker_renderer/utils/technical_drawing.py`
  - `_drafting_preview_views()`
  - `render_technical_drawing_preview()`
  - `technical_drawing_preview_rendered`
  - `technical_drawing_preview_object_store_upload_failed`
- `shared/eval_artifacts.py`
  - `_technical_drawing_mode_active()`
  - `_agent_technical_drawing_modes()`
- `dataset/evals/materialize_seed_workspace.py`
  - `_filter_rows_by_technical_drawing_mode()`
- `dataset/evals/run_e2e_seed.py`
  - the `technical_drawing_mode` seed injection path
- `config/agents_config.yaml`
  - `technical_drawing_mode` entries
  - `render_technical_drawing` tool exposure
- `config/prompts.yaml`
  - all drafting-mode prompt appendices
  - all `render_technical_drawing()` instructions
- `shared/agent_templates/__init__.py`
  - benchmark and engineering template entries that point at drafting scripts
- `shared/agent_templates/codex/scripts/submit_plan.py`
  - drafting-mode role detection and submission gating

Remove the drafting fixture families and any seed rows that only exist to
materialize or validate technical drawing mode:

- `dataset/data/seed/artifacts/**/benchmark_plan_technical_drawing_script.py`
- `dataset/data/seed/artifacts/**/solution_plan_technical_drawing_script.py`
- any `dataset/data/seed/role_based/*.json` row with `technical_drawing_mode`
  other than `off`
- any `todo.md`, `journal.md`, or manifest entry that only exists because the
  drawing companion script exists

### Training, journalling, and skill-loop surfaces

The paper may claim skills as a concept, but it does not need the standalone
training machinery that manufactures skills or compresses runs after the fact.

Trim the following helper nodes and CLIs unless the final paper explicitly
reports them as a result:

- `controller/agent/nodes/summarizer.py`
- `controller/agent/nodes/skills.py`
- `dataset/evals/train_skills.py`
- `dataset/evals/eval_seed_update_autopilot.py`
- `dataset/evals/run_e2e_seed.py`

If the reward table is not cited in the final submission, the reward config
and loader should also be treated as internal-only:

- `controller/agent/reward.py`
- `config/reward_config.yaml`

The publication bundle should keep the skill source and prompt source only,
not the recursive self-improvement loop that edits them.

### Observability long tail

The paper needs observability for traces, review decisions, and reproducible
debugging. It does not need every low-level telemetry family ever added to the
project.

Keep the core event families that support the paper claims, and drop the long
tail of maintenance-only telemetry models from `shared/observability/schemas.py`
and the matching controller-side emitters.

Examples of event classes that should be removed unless the final paper
explicitly reports them:

- `LsFilesToolEvent`
- `GrepToolEvent`
- `ReadFileToolEvent`
- `WriteFileToolEvent`
- `EditFileToolEvent`
- `RunCommandToolEvent`
- `GitInitToolEvent`
- `GitCommitToolEvent`
- `SkillEditEvent`
- `SkillReadEvent`
- `SkillSelfReflectionEvent`
- `SkillUpdateEvent`
- `SkillPromotionEvent`
- `LibraryUsageEvent`
- `SimulationInstabilityEvent`
- `LintFailureCodeEvent`
- `LintFailureDocsEvent`
- `LogicFailureEvent`

The publication bundle should preserve the paper-relevant events such as
tool invocation, manufacturability checks, simulation request/result, review
decision, render request/inspection, conversation-length compaction, and the
paper-critical event families that prove the published claims.

### Dataset and eval bulk

The dataset should not mirror every historical row. It should keep only the
curated publication slice that matches the claim matrix.

Remove the generated corpora:

- `dataset/data/generated/**`

Trim the seed families that only exist for non-paper helper roles or old
compatibility names:

- `dataset/data/seed/role_based/git_agent.json`
- `dataset/data/seed/role_based/skill_agent.json`
- `dataset/data/seed/role_based/engineer_reviewer.json`
- `dataset/data/seed/artifacts/git_agent/**`
- `dataset/data/seed/artifacts/skill_agent/**`

If the final paper does not cite a role family, its seed rows do not belong in
the release bundle.

The evaluation and materialization helpers should be reduced to the minimum
paper-critical path:

- keep one canonical eval runner only if the paper needs it for reproduction
- drop the standalone autopilot, replay, and skill-training CLIs
- do not ship generated training artifacts as source

### Test and fixture bulk

The publication bundle should retain only the integration slices that prove
the paper's claims. Broad frontend, eval, and auxiliary integration coverage
is not worthy of inclusion unless the paper cites it directly.

Remove:

- `tests/integration/frontend/**`
- `tests/electronics/test_integration_electronics.py`
- `tests/integration/evals_p2/**`
- the non-paper subset of `tests/integration/architecture_p1/**`
- the non-paper subset of `tests/integration/mock_responses/**`
- `tests/README.md`

The `drawing-*` benchmark and engineer fixture families are also out of
bundle, because they only exist to exercise the technical-drawing contract that
this migration removes.

Retain only the paper-critical integration coverage, such as the benchmark
workflow, engineering loop, handover validation, render validation, COTS
geometry import, observability, infrastructure, and manufacturing slices.

### Late-epic branches to cut

The publication bundle stops at Epic 7. Any branch whose first meaningful
claim appears in Epic 8 or later is removed wholesale. Do not keep partial
branches, dormant config flags, or compatibility aliases for those families.

The technical-drawing contract is already trimmed in the section above. The
remaining late-epic families that must disappear are electromechanics, fluids
and FEM, steerability, and advanced visualization.

#### Electronics and electromechanics

Remove the entire electromechanical stack rather than trying to preserve a
minimal EDA subset:

- `controller/agent/nodes/electronics_planner.py`
  - `ElectronicsPlannerSignature`
  - `ElectronicsPlannerNode`
  - `electronics_planner_node()`
- `controller/agent/nodes/electronics_reviewer.py`
  - `electronics_reviewer_node()`
- `controller/agent/graph.py`
  - `route_after_electronics_planner()`
  - `route_after_electronics_reviewer()`
  - `electronics_planner_graph`
  - `electronics_reviewer_graph`
- `controller/agent/prompt_manager.py`
  - electronics role prompt entries and prompt-selection branches
- `controller/agent/handover_constants.py`
  - `ELECTRONICS_REVIEWER_HANDOVER_CHECK`
- `controller/api/routes/episodes.py`
  - `get_episode_schematic()`
- `controller/api/main.py`
  - the electronics/steerability router wiring if it exists only for late-epic behavior
- `worker_heavy/utils/electronics.py`
  - `calculate_power_budget()`
  - `create_circuit()`
  - `route_wire()`
  - `simulate_circuit_transient()`
  - `validate_circuit()`
- `worker_heavy/simulation/electronics.py`
- `worker_heavy/simulation/loop.py`
  - the electronics manager, power-gating, switch-state, and `is_powered_map` branches
- `worker_heavy/simulation/genesis_backend.py`
  - the electronics setup and electronics-fluid-damage branches
- `shared/circuit_builder.py`
- `shared/schematic_utils.py`
- `shared/wire_utils.py`
- `shared/models/schemas.py`
  - electronics and routing fields, including circuit-validation and wiring models
- `shared/enums.py`
  - `AgentName.ELECTRONICS_PLANNER`
  - `AgentName.ELECTRONICS_ENGINEER`
  - `AgentName.ELECTRONICS_REVIEWER`
- `shared/agent_templates/__init__.py`
  - the electronics planner template mapping
- `shared/agent_templates/codex/scripts/submit_engineering_plan.sh`
  - the electronics role gate
- `dataset/data/seed/role_based/electronics_planner.json`
- `dataset/data/seed/role_based/electronics_reviewer.json`
- `dataset/data/seed/artifacts/electronics_planner/**`
- `dataset/data/seed/artifacts/electronics_reviewer/**`
- `tests/electronics/test_integration_electronics.py`
- `tests/integration/architecture_p1/test_electronics_full.py`

#### Seeded eval prune checklist

The current seed tree has no populated fluids/FEM or steerability rows, so the
prune list below only names electromechanical seeds.

- [ ] Benchmark coder: prune `bc-012-raised-shelf-motor`.
- [ ] Benchmark plan reviewer: prune `bpr-001-raised-shelf`,
  `bpr-004-timed-gate`, `bpr-009-fast-transfer`,
  `bpr-011-raised-shelf-goal-obstruction`,
  `bpr-014-timed-gate-clearance-budget`, and
  `bpr-019-fast-transfer-hidden-brake-axis`.
- [ ] Benchmark reviewer: prune `br-014-timed-gate-cots-review` and
  `br-015-fast-transfer-hidden-brake-axis-review`.
- [ ] Engineer planner: prune `ep-001-raised-shelf`, `ep-004-timed-gate`,
  and `ep-009-fast-transfer`.
- [ ] Engineer plan reviewer: prune `epr-001-sideways-transfer`,
  `epr-003-timed-gate-chute`, `epr-004-raised-shelf-lift`,
  `epr-010-diverter-gate-wiring`,
  `epr-011-sideways-transfer-budget-overrun`, and
  `epr-012-sideways-transfer-fake-cots`.
- [ ] Engineer coder: prune `ec-001`, `ec-003`, `ec-004`, `ec-011`,
  `ec-012`, `ec-013`, and `ec-014`.
- [ ] Engineer execution reviewer: prune `eer-001-sideways-transfer`,
  `eer-003-timed-gate-chute`, `eer-004-raised-shelf-lift`,
  `eer-010-diverter-gate-wiring`,
  `eer-011-sideways-transfer-budget-overrun`, and
  `eer-012-sideways-transfer-fake-cots`.
- [ ] Benchmark coder orphan workspace: prune
  `dataset/data/seed/artifacts/benchmark_coder/bc-014-raised-shelf-lift/` if
  it is still present in the seed tree.

Do not preserve `shared/circuit_builder.py` or `shared/wire_utils.py` as
standalone EDA helpers if the electromechanical branch is gone. Those files are
not paper-worthy on their own.

#### Fluids, FEM, and stress

Remove the fluid and deformable-material support surface:

- `worker_heavy/utils/validation.py`
  - `define_fluid()`
  - `get_stress_report()`
  - `preview_stress()`
  - `set_soft_mesh()`
  - `validate_fem_manufacturability()`
- `shared/rendering/stress_heatmap.py`
- `worker_heavy/simulation/objectives.py`
  - the fluid-objective and stress-objective evaluation branches
- `worker_heavy/simulation/genesis_backend.py`
  - the fluid particle, stress-field, and fluid-contact branches
- `worker_heavy/simulation/loop.py`
  - `stress_summaries`
  - `fluid_metrics`
  - the fluid and stress failure upgrade paths
- `shared/models/schemas.py`
  - `fluid_objectives`
  - `stress_objectives`
  - any fluid/stress helper models
- `shared/observability/schemas.py`
  - `FLUID_CONTAINMENT_CHECK`
  - `FLOW_RATE_CHECK`
  - `STRESS_SUMMARY`
  - `MESHING_FAILURE`
  - `PHYSICS_INSTABILITY`
  - `GPU_OOM_RETRY`
- `tests/integration/architecture_p1/test_physics_fluids_full.py`
- `tests/integration/architecture_p1/test_physics_fluids_extended.py`
- `tests/integration/evals_p2/**` if the only reason they exist is to cover the late-epic fluid/FEM path

#### Steerability and live prompt injection

Remove the steering stack as a whole. It is late-stage interaction plumbing,
not a publication requirement for an Epic 7 bundle:

- `controller/graph/steerability_node.py`
  - `steerability_node()`
  - `check_steering()`
- `controller/services/steerability/service.py`
  - `SteerabilityService`
  - `steerability_service`
- `controller/persistence/steering_memory.py`
- `controller/api/routes/steerability.py`
  - `steer_agent()`
  - `get_steering_queue()`
- `controller/agent/graph.py`
  - the `AgentName.STEER` node and all steering conditional edges
- `controller/agent/benchmark/graph.py`
  - the benchmark-side steering edges
- `controller/agent/nodes/base.py`
  - `_get_steer_context()`
- `controller/agent/nodes/planner.py`
  - the `steer_context` input field and extraction path
- `controller/agent/nodes/coder.py`
  - the `steer_context` input field and extraction path
- `controller/api/tasks.py`
  - steerability metadata injection into message payloads
- `controller/api/schemas.py`
  - steerability queue request/response models
- `shared/models/steerability.py`
- `shared/enums.py`
  - `AgentName.STEER`
- `specs/integration-test-list.md`
  - the steering-only `INT-067`, `INT-068`, `INT-179`, `INT-182`, `INT-183`, and related coverage rows

#### Advanced visualization

Keep the basic evidence surface if the paper cites it, but remove advanced UI
visualization for later epics:

- `tests/integration/frontend/**`
- `controller/api/routes/episodes.py`
  - the electronics schematic route if the publication bundle does not retain
    electromechanics
- any frontend or renderer path that exists only to display FEM, fluids, or
  electronics artifacts in-browser

### Internal docs and scans

The following documentation is development support, not conference artifact
material:

- `specs/architecture/distributed-execution.md`
- `specs/architecture/agents/agent-harness.md`
- `specs/architecture/agents/tools.md`
- `specs/architecture/agents/prompt-management.md`
- `specs/architecture/agents/engineering-planner-technical-drawings.md`
- `specs/architecture/electronics-and-electromechanics.md`
- `specs/architecture/fluids-and-deformables.md`
- `specs/integration-test-list.md`
- `specs/integration-test-rules.md`
- `specs/devtools.md`
- `docs/project-overview.md`
- `docs/source-tree-analysis.md`
- `docs/backend-reference.md`
- `docs/index.md`
- `docs/component-inventory.md`
- `docs/data-models.md`
- `docs/architecture.md`
- `docs/development-guide.md`
- `docs/deployment-guide.md`
- `docs/spec-coverage.md`
- `docs/project-scan-report.json`
- `docs/project-parts.json`
- `docs/qwen-performance.log.md`
- `docs/nightly-work-plans/**`
- `docs/agent-workflow/**`

## Module-Level Trim Notes

The following modules need symbol-level cleanup even if the module itself is
kept for the publication bundle:

| Module | Symbols to trim or collapse |
| -- | -- |
| `controller/agent/mock_llm.py` | `MockDSPyLM`, `_cached_integration_mock_scenarios` |
| `controller/agent/mock_scenarios.py` | `TranscriptStepSpec`, `TranscriptNodeSpec`, `TranscriptScenarioSpec`, `_expand_content_file_refs`, `_validate_scenarios`, `_load_from_directory`, `load_integration_mock_scenarios` |
| `controller/agent/provider_tool_call_adapters/minimax_adapter.py` | `_coerce_minimax_parameter_value`, `MiniMaxToolCallAdapter` |
| `controller/temporal_worker.py` | `main()`, Temporal worker registration, connect/retry loop |
| `worker_heavy/temporal_worker.py` | `main()`, heavy-task queue worker registration, connect/retry loop |
| `controller/workflows/execution.py` | `ScriptExecutionWorkflow` and any Temporal-only retry policy wrapper |
| `controller/workflows/heavy.py` | heavy orchestration workflows and any Temporal-only workflow wrapper |
| `controller/workflows/simulation.py` | simulation workflow entrypoints and retry wrappers |
| `controller/workflows/preview.py` | preview workflow entrypoints and retry wrappers |
| `controller/activities/execution.py` | Temporal activity entrypoints for execution-only orchestration |
| `controller/activities/simulation.py` | Temporal activity entrypoints for simulation-only orchestration |
| `controller/activities/preview.py` | Temporal activity entrypoints for preview-only orchestration |
| `controller/api/ops.py` | backup-workflow endpoint and its Temporal client dependency |
| `controller/middleware/remote_fs.py` | `_require_temporal_for_heavy_operation()`, `_execute_or_use_existing_workflow()`, Temporal workflow-id helpers, and the Temporal-backed `validate`/`simulate`/`preview`/`verify`/`submit` branches |
| `controller/config/settings.py` | `temporal_url` and any Temporal-only client configuration |
| `worker_light/app.py` | the `heavy_temporal_worker_main()` unified-mode bootstrap |
| `evals/logic/stack_profiles.py` | Temporal host/port fields, env injection, and devops stack profiles |
| `shared/agents/config.py` | `DraftingMode`, `technical_drawing_mode`, `get_technical_drawing_mode()`, `get_drafting_mode()` |
| `shared/script_contracts.py` | drafting-path constants and helper functions for benchmark and solution drafting scripts |
| `shared/utils/agent/__init__.py` | `render_technical_drawing()`, `preview_drawing()` |
| `worker_heavy/utils/preview.py` | `render_technical_drawing()` |
| `worker_heavy/utils/handover.py` | `_drafting_mode_for_reviewer_stage()`, the drafting manifest validation branch in `submit_for_review()` |
| `worker_heavy/utils/file_validation.py` | `_technical_drawing_mode_for_node()`, `_technical_drawing_script_imports_and_calls_technical_drawing()`, `validate_drafting_preview_manifest()` |
| `worker_renderer/api/routes.py` | `render_technical_drawing_preview` route binding |
| `worker_renderer/utils/technical_drawing.py` | `_drafting_preview_views()`, `render_technical_drawing_preview()`, drafting preview telemetry |
| `shared/eval_artifacts.py` | `_technical_drawing_mode_active()`, `_agent_technical_drawing_modes()` |
| `dataset/evals/materialize_seed_workspace.py` | `_filter_rows_by_technical_drawing_mode()` |
| `dataset/evals/run_e2e_seed.py` | `technical_drawing_mode` seed injection |
| `controller/agent/nodes/summarizer.py` | `SummarizerSignature`, `SummarizerNode` |
| `controller/agent/nodes/skills.py` | `SkillsSignature`, `SkillsNode` |
| `controller/agent/benchmark/render_seed.py` | `_normalize_render_path` |
| `controller/agent/benchmark/graph.py` | benchmark-side steering edges and `AgentName.STEER` routing branches |
| `controller/graph/steerability_node.py` | `get_session_id` and the steerability dispatch path |
| `controller/api/routes/steerability.py` | the whole route surface |
| `controller/services/steerability/**` | the whole service surface |
| `controller/persistence/steering_memory.py` | the whole steerability-memory surface |
| `controller/agent/render_validation.py` | `_normalize_render_root` and any render-path compatibility aliasing that is only there for older bundle layouts |
| `controller/agent/tools.py` | `_rewrite_render_bundle_path`, `_rewrite_render_siblings`, direct ReAct-only wrappers that duplicate script-backed commands, and any `filter_tools_for_agent` branch that exposes removed compatibility or debug-only tools |
| `controller/api/routes/episodes.py` | replay-only helpers such as `_normalize_plan_markdown`, `_select_latest_replay_assets`, `_asset_looks_like_review_manifest`, `_artifact_kind_from_path`, `_artifact_path_matches`, `_review_decision_events_from_episode`, `_manifest_expected_revision`, `_validate_manifest_session`, plus `get_episode_schematic()` if electromechanics is not part of the published artifact |
| `controller/api/routes/datasets.py` | archive-only helpers such as `_select_latest_assets`, `_archive_members`, and any dataset-export helper that exists only for maintainer workflows |
| `controller/api/routes/script_tools.py` | `_script_log_context` and any script-proxy route that only exists to support ad hoc debugging |
| `controller/api/main.py` | router includes for steerability, electronics, drafting-only routes, or Temporal client startup that are not part of the Epic 7 bundle |
| `controller/agent/graph.py` | `route_after_electronics_planner()`, `route_after_electronics_reviewer()`, `electronics_planner_graph`, `electronics_reviewer_graph`, and any steering edge still wired into the core graph |
| `worker_heavy/simulation/loop.py` | electronics manager, power-gating, `is_powered_map`, `stress_summaries`, `fluid_metrics`, and any drafting gate branches |
| `worker_heavy/simulation/genesis_backend.py` | electronics setup, electronics-fluid-damage checks, stress-field helpers, and fluid particle branches |
| `worker_heavy/simulation/objectives.py` | the fluid-objective and stress-objective evaluation branches |
| `controller/agent/prompt_manager.py` | electronics role prompt entries, drafting appendices, old SDK/tool-flow prose, and any prompt-selection branch that references late-epic surfaces |
| `controller/agent/handover_constants.py` | `ELECTRONICS_REVIEWER_HANDOVER_CHECK` and any other late-epic handover discriminator |
| `config/agents_config.yaml` | `technical_drawing_mode` branches, role-specific drafting tool exposure, old SDK tool exposure, and any electronics-only role wiring |
| `config/prompts.yaml` | drafting appendices, `render_technical_drawing()` instructions, old ReAct-only tool prose, and electronics-only prompt branches |
| `shared/agent_templates/__init__.py` | role template entries that point at drafting scripts or electronics-only starter files |
| `shared/agent_templates/codex/scripts/submit_plan.py` | drafting-mode role detection and submission gating |
| `shared/agent_templates/codex/scripts/submit_for_review.py` | drafting-mode reviewer gating and electronics-review manifest selection |
| `shared/models/schemas.py` | `TechnicalDrawing`, drafting submodels, electronics fields, fluid/stress fields, and any schema models that only exist for late-epic branches |
| `shared/enums.py` | `AgentName.ELECTRONICS_PLANNER`, `AgentName.ELECTRONICS_ENGINEER`, `AgentName.ELECTRONICS_REVIEWER`, `AgentName.STEER` |
| `shared/models/steerability.py` | steerability payload models |
| `controller/api/schemas.py` | steerability queue request/response models |
| `controller/api/tasks.py` | steerability metadata injection into message payloads |
| `worker_heavy/simulation/frame_stream.py` | `_http_to_ws_url`, `_encode_png_base64`, `SimulationFrameStreamPublisher` |
| `worker_heavy/utils/validation.py` | the fluid and deformable helpers listed above, `preview_stress()`, `_drafting_preview_role()`, `_validate_drafting_preview_gate()`, and any debug-only stress preview path that is not part of the paper claim matrix |
| `shared/observability/schemas.py` | the long-tail event classes listed above, including drafting-preview, electronics, fluid/stress, and steerability events; the file should keep only the event families needed to prove the paper claims |

## Proposed Target State

1. The publication bundle is backend-first and claim-driven.
2. The bundle contains one canonical paper source, one canonical reproducible
   figure path, one canonical prompt source, one canonical skill source, and a
   minimal paper-critical verification surface.
3. The operator UI, website mirror, and experimental probe tree are absent.
4. Generated outputs, logs, compiled exports, caches, and result archives are
   not tracked as source for the submission.
5. Skill training, journalling compression, steerability experiments, mock
   providers, and legacy compatibility wrappers are not part of the conference
   artifact.
6. The only retained drawing behavior is the default full geometric-plan path;
   the off/minimal drafting matrix and technical-drawing companion are gone.
7. Technical drawing, electromechanical, fluids/FEM, steerability, and
   non-local devops branches are removed completely because they only become
   justified after Epic 7.
8. The release manifest is fail-closed: anything not explicitly included is
   excluded, and no dormant late-epic compatibility paths remain.

## Completed So Far

- [x] Remove `worker_renderer/utils/technical_drawing.py` and the
  `render_technical_drawing_preview` route binding from
  `worker_renderer/api/routes.py`.
- [x] Remove the technical-drawing template artifacts from
  `shared/assets/template_repos/benchmark_generator/**` and
  `shared/assets/template_repos/engineer/drafting/**`.
- [x] Remove the deleted technical-drawing filename constants from
  `shared/script_contracts.py` and update
  `controller/agent/node_entry_validation.py` to reference only the surviving
  evidence-script names.
- [x] Remove the electronics role prompt entries from
  `controller/agent/prompt_manager.py`.
- [x] Remove `worker_light/agent_files/.admin/clear_env.py`.
- [x] Remove `controller/agent/nodes/{electronics_planner.py,electronics_reviewer.py,skills.py,summarizer.py}` and prune the corresponding engineer, benchmark, and top-level graph resolver routes that reached those sidecars.
- [x] Remove the benchmark-side skill and journalling node implementations from `controller/agent/benchmark/nodes.py` so the deleted loop is no longer present as dead code.
- [x] Audit `specs/architecture/` for out-of-bundle references and stage the remaining prune work as a checklist because the affected doc surface is too broad for a safe one-pass edit.
- [x] Remove the steerability runtime plumbing from the controller API, agent node inputs, persistence model, and generated OpenAPI snapshots.
- [x] Remove the Genesis particle-system / deformable rendering branches so the backend no longer carries soft-body-specific code paths.

## Retained Roots

The publication bundle keeps the minimal runnable and deployment roots:

- `pyproject.toml`
- `uv.lock`
- `Makefile`
- `main.py`
- `docker-compose*.yml`
- `Podmanfile.sandbox`
- `config/manufacturing_config.yaml`
- `config/prompts.yaml`
- `config/agents_config.yaml`
- `config/skills_config.yaml`
- `shared/assets/template_repos/**`
- `shared/skills/**`
- `build123d-cad-drafting-skill`
- `.agents/skills/**`

The Python venv and minimal deployment path stay in place; this migration only
prunes publication bulk that is not needed to bootstrap or run the release
shape.

## Required Work

### 1. Freeze the claim matrix

- Derive the publication claim matrix from
  `docs/academic-submission/final-project-report.tex`.
- Mark each major repository surface as core, retained, or out-of-bundle.
- Use the final camera-ready text, not draft notes, to decide whether a branch
  stays.

### 2. Prune the docs and spec tree

- Remove or archive architecture and integration docs whose only purpose is to
  explain removed Temporal, drafting, electronics, fluids, steerability, or
  local-SDK surfaces.
- Update prompt and role docs so they no longer teach removed tool surfaces or
  removed mode matrices.
- Treat the docs that describe removed capability families as publication bulk,
  not as part of the conference artifact.

#### Architecture-doc cleanup checklist

This pass is too broad to finish safely in one sweep. Track the remaining
`specs/architecture/` pruning here and close it out in smaller edits. This
includes the corresponding `specs/architecture/agents/agent-artifacts/` files
whenever they still mention one of these families.

- [ ] Technical drawing references:
  `specs/architecture/agents/engineering-planner-technical-drawings.md`,
  `specs/architecture/agents/agent-harness.md`,
  `specs/architecture/agents/prompt-management.md`,
  `specs/architecture/agents/tools.md`,
  `specs/architecture/agents/handover-contracts.md`,
  `specs/architecture/agents/artifacts-and-filesystem.md`,
  `specs/architecture/agents/roles.md`,
  `specs/architecture/agents/roles-detailed/*.md`, and
  `specs/architecture/agents/agent-artifacts/*technical_drawing*`.
- [ ] Electronics and electromechanics references:
  `specs/architecture/electronics-and-electromechanics.md`,
  `specs/architecture/agents/overview.md`,
  `specs/architecture/agents/roles.md`,
  `specs/architecture/agents/roles-detailed/electronics-*.md`,
  `specs/architecture/agents/handover-contracts.md`,
  `specs/architecture/agents/artifacts-and-filesystem.md`,
  `specs/architecture/agents/tools.md`,
  `specs/architecture/agents/auxiliary-agent-tools.md`,
  `specs/architecture/CAD-and-other-infra.md`,
  `specs/architecture/simulation-and-rendering.md`,
  `specs/architecture/fluids-and-deformables.md`,
  `specs/architecture/observability.md`,
  `specs/architecture/cots-geometry-import.md`, and
  `specs/architecture/auxillary/simulation-optimization-attempts.md`.
- [ ] Fluids, FEM, and stress references:
  `specs/architecture/fluids-and-deformables.md`,
  `specs/architecture/simulation-and-rendering.md`,
  `specs/architecture/CAD-and-other-infra.md`,
  `specs/architecture/agents/auxiliary-agent-tools.md`,
  `specs/architecture/agents/handover-contracts.md`,
  `specs/architecture/observability.md`, and
  `specs/architecture/auxillary/simulation-optimization-attempts.md`.
- [ ] Temporal and devops references:
  `specs/architecture/distributed-execution.md`,
  `specs/architecture/agents/agent-harness.md`,
  `specs/architecture/agents/tools.md`,
  `specs/architecture/agents/prompt-management.md`,
  `specs/architecture/agents/handover-contracts.md`,
  `specs/architecture/agents/artifacts-and-filesystem.md`,
  `specs/architecture/evals-architecture.md`, and
  `specs/architecture/application-acceptance-criteria.md`.
- [ ] Steerability references:
  `specs/architecture/agents/handover-contracts.md`,
  `specs/architecture/agents/overview.md`,
  `specs/architecture/agents/roles.md`,
  `specs/architecture/agents/roles-detailed/README.md`,
  `specs/architecture/distributed-execution.md`, and
  `specs/architecture/observability.md`.
- [ ] Advanced visualization references:
  `specs/architecture/simulation-and-rendering.md`,
  `specs/architecture/agents/overview.md`, and
  `specs/architecture/observability.md`.

### 3. Collapse the academic-submission tree

- Keep one canonical LaTeX source for the paper.
- Keep only the reproducibility inputs that the paper actually cites.
- Remove duplicate drafts, exported PDFs, log files, and alternate formats.
- Convert anything not cited by the paper into archive-only material.

### 4. Remove presentation, website, and probe surfaces

- Remove `frontend/` from the publication bundle.
- Remove `website/` from the publication bundle.
- Remove `scripts/experiments/` from the publication bundle.
- Remove any generated render, log, or benchmark result file that is not cited
  as a reproducibility input.

### 5. Remove compatibility, training-only, and orchestration machinery

- Remove legacy mirror trees such as `worker_light/agent_files/`.
- Remove generic wrapper scripts that only exist for older launch paths.
- Remove mock LLMs, mock scenarios, drafting helpers, steerability services,
  and other maintenance-only control paths.
- Remove the standalone training/autopilot CLIs that are not required to
  reproduce the final paper's claims.
- Remove the Temporal orchestration shell, the devops-only worker/backup
  workflows, and any local agent-SDK clone layer that only recreates older
  provider behavior.

### 6. Prune observability to the paper-critical subset

- Keep the events needed to explain the published workflows.
- Remove generic file/tool telemetry, technical-drawing preview telemetry,
  late-epic electromechanical telemetry, and skill-loop telemetry that only
  exists for internal debugging or training.
- Remove any event family whose only real claim is outside Epic 7, including
  the drafting-preview events, electronics events, fluid/stress events, and
  steerability events.

### 7. Curate the data and tests

- Keep only the seed rows and generated artifacts that reproduce the published
  benchmark families.
- Remove generated corpora and helper-role seed families that are not part of
  the paper.
- Remove seed rows that only exist to toggle `technical_drawing_mode`,
  electronics, steerability, or late-epic multiphysics fixtures.
- Reduce integration coverage to the paper-critical slice and drop the rest.

### 8. Collapse late-epic branches

- Remove the technical-drawing contract, drafting mode, and preview plumbing.
- Remove the electronics/electromechanical branch end-to-end.
- Remove the fluids, FEM, and stress branch end-to-end.
- Remove steerability end-to-end.
- Do not leave behind a partial branch, compatibility alias, or dormant config
  switch for any Epic 8+ surface.

### 9. Publish a fail-closed package boundary

- Define the publication bundle as an explicit include list in this migration
  spec.
- Make packaging consume that include list rather than the whole repository
  tree.
- Anything omitted stays out.

## Non-Goals

- No redesign of the controller, worker, or shared-contract architecture.
- No new benchmark family or new scientific claim beyond the paper.
- No rewrite of the paper narrative to justify keeping extra code.
- No attempt to erase development history from git; only the publication bundle
  is being pruned.
- No frontend redesign and no website redesign.
- No removal of the render/evidence pipeline, the CLI-provider backend, or the
  physics-backend abstraction beyond the feature-specific branches named in
  this migration.
- No removal of the strong handoff and validation scaffolding that supports the
  published workflows; only the unnecessary feature families and compatibility
  shells are trimmed.
- No replacement of the checked-in shell-script command surface with a bespoke
  local agent SDK clone or a new direct ReAct tool mirror.

## Sequencing

The safe order is:

1. Freeze the claim matrix from the final paper.
2. Prune the docs and spec tree that describes removed surfaces.
3. Define the fail-closed package boundary.
4. Collapse the academic-submission tree to one canonical paper source and one
   reproducibility path.
5. Remove the presentation, website, experimental, legacy-compatibility,
   orchestration, and late-epic feature surfaces.
6. Prune the training-only, observability-long-tail, dataset, and test bulk.
7. Collapse late-epic branches to nothing rather than leaving dormant
   compatibility paths.
8. Record the final bundle contents and the rationale for every exclusion.

## Acceptance Criteria

1. The publication bundle has a documented manifest that names the minimal
   files and directories required to rebuild the conference artifact.
2. A clean publication checkout does not require `frontend/`, `website/`, or
   `scripts/experiments/` to reproduce the paper.
3. The bundle contains one canonical paper source and no tracked generated
   PDF, log, or duplicate draft artifacts.
4. Generated outputs, caches, logs, and render bundles are excluded from the
   source release.
5. The curated test set covers the benchmark generator, engineer solver,
   render evidence, simulation, and handover contract paths that the paper
   claims.
6. The publication bundle still satisfies the core architecture contracts for
   the published workflows, and nothing else.
7. The bundle contains no technical-drawing, electronics, fluids/FEM,
   steerability, or non-local devops runtime branch in code, config, prompts,
   seed data, or tests.
8. The only retained drawing behavior is the default full geometric-plan path;
   the off/minimal drafting matrix is absent.

## Migration Checklist

### Claim matrix

<!-- Frozen reminder: the claim matrix above is derived from
  `docs/academic-submission/final-project-report.tex`. -->
- [x] Mark every major repo surface as core, retained, or out-of-bundle.
- [x] Remove every feature family whose first meaningful claim appears in
  Epic 8 or later, including drafting, electronics, fluids/FEM, and
  steering.

### Paper artifacts

- [ ] Collapse `docs/academic-submission/` to one canonical paper source and
  the minimal reproducibility inputs it needs.
- [ ] Remove duplicate drafts, exported PDFs, logs, and alternate formats.
- [ ] Archive any unused alternate paper notes or matrix files.

### Runtime bundle trim

- [x] Remove `frontend/` from the default publication bundle.
- [x] Remove `website/` from the default publication bundle.
- [x] Remove `scripts/experiments/` from the default publication bundle.
- [x] Remove `worker_light/agent_files/` from the default publication bundle.
- [x] Remove mock-provider, steerability, and legacy-wrapper surfaces.
- [x] Remove Temporal orchestration shells, non-local devops helpers, and any
  bespoke local-agent-SDK clone surface from the default bundle.
- [x] Remove technical-drawing plumbing, electronics planner/reviewer
  surfaces, and late-epic simulation helpers from the default bundle,
  including the script-contract helpers, preview/render wrappers, and
  drafting handoff validators.
- [x] Remove the remaining eval-seed technical-drawing mode plumbing from
  `evals/logic/{models,dataset_selection,runner,workspace}.py`,
  `scripts/internal/{eval_run_lock,eval_seed_selection,eval_seed_renders}.py`,
  `scripts/{validate_eval_seed,update_eval_seed_renders}.py`, and the matching
  integration-test helper and mock-response references.
- [x] Remove the remaining motors/electronics/fluid/deformable schema and
  scene-builder/evaluator plumbing from `shared/models/schemas.py`,
  `shared/models/simulation.py`, `shared/simulation/scene_builder.py`,
  `shared/observability/schemas.py`, `worker_heavy/simulation/{builder,genesis_backend,loop}.py`,
  and the supporting validation helpers.
- [x] Remove the standalone objective-evaluator and electronics-metric stub
  surfaces from `worker_heavy/simulation/objectives.py` and
  `shared/utils/evaluation.py`.
- [x] Collapse the drawing-mode matrix to the retained full geometric-plan
  path and delete the off/minimal technical-drawing variants.
- [x] Remove the drafting gate and `preview_stress` helper path from
  `worker_heavy/utils/validation.py`, and drop the `preview_stress` export
  from `worker_heavy.utils`.
- [x] Remove the FEM manufacturability gate and its internal callsites from
  `worker_heavy/utils/validation.py`.
- [x] Remove the mechanical-engineering skill prose that still taught the
  removed stress-preview and fluid helper hooks.
- [x] Remove the dead technical-drawing-mode helper/import from
  `tests/integration/architecture_p0/test_node_entry_validation.py`.
- [x] Drop the unused steerability re-export from `shared/models/__init__.py`.
- [x] Correct the canonical INT-131 integration-test row to match the live
  COTS inventory exactness test and keep the architecture_p1 mapping in sync.

### Frontend API boundary cleanup

- [ ] Remove the now-unused frontend-only FastAPI boundary from
  `controller/api/main.py`.
- [ ] Collapse any router includes, startup wiring, or OpenAPI generation
  paths that existed only to serve `frontend/`.
- [ ] Remove frontend-consumed API artifacts such as `frontend/openapi.json`
  and `frontend/src/api/**` from the publication bundle.
- [ ] Ensure no retained controller API surface exists solely to support the
  operator UI.

### Training, observability, and data

- [x] Remove the standalone skill-training/autopilot CLIs.
- [x] Trim `shared/observability/schemas.py` to the paper-critical event set,
  excluding drafting, electronics, fluids, and steering events.
- [x] Remove `dataset/data/generated/` from the source release path.
- [x] Curate the seed rows to the paper-critical role families only and remove
  any `technical_drawing_mode` or late-epic seed variants.
- [x] Remove prompt and skill prose that teaches removed ReAct-only tools or
  removed local-SDK clone behavior.

### Verification and docs

- [x] Curate the dataset and integration-test surface down to the paper-
  critical subset.
- [x] Remove the technical-drawing fixture families and late-epic branch
  tests from the release candidate.
- [x] Prune the architecture and integration docs that only explain removed
  Temporal, drafting, electronics, fluids, steerability, or local-SDK
  surfaces.
- [x] Update the repository overview docs to distinguish the publication
  bundle from the development tree, or exclude them entirely if the release
  manifest no longer ships docs.
- [x] Record the final publication bundle contents and the rationale for each
  excluded surface.

#### Integration test prune manifest

- [x] `tests/integration/frontend/**`: remove `INT-157`..`INT-179`, `INT-189`,
  and `INT-205`; delete the matching
  `tests/integration/mock_responses/INT-xxx.yaml` fixtures and scenario trees
  for those IDs.
- [x] `tests/integration/agent/p1/test_int_181_to_183.py`: remove
  `INT-181`..`INT-186`; delete the matching
  `tests/integration/mock_responses/INT-181.yaml`..`INT-186.yaml` fixtures and
  scenario trees.
- [x] `tests/integration/architecture_p0/test_int_102_111.py`: remove
  `INT-102`..`INT-111`; delete the matching mock-response fixtures and
  scenario trees.
- [x] `tests/integration/architecture_p0/test_int_120_electronics.py`: remove
  `INT-120`..`INT-128`; delete the matching mock-response fixtures and
  scenario trees.
- [x] `tests/integration/architecture_p0/test_int_188_validation_preview.py`
  and `tests/integration/architecture_p0/test_architecture_p0.py`: remove
  `INT-188`, `INT-208`, and `INT-209`; delete the matching mock-response
  fixtures and scenario trees.
- [x] `tests/integration/architecture_p0/test_codex_runner_mode.py`: remove
  `INT-207`; delete the matching mock-response fixture and scenario tree.
- [x] `tests/integration/architecture_p0/test_planner_gates.py` and
  `tests/integration/architecture_p1/test_reviewer_evidence.py`: remove
  `INT-204`; delete the matching mock-response fixture and scenario tree.
- [x] `tests/integration/architecture_p0/test_node_entry_validation.py`:
  remove `INT-184` and `INT-190`; delete the matching mock-response fixtures
  and scenario trees.
- [x] `tests/integration/architecture_p1/test_render_validation.py`: remove
  `INT-190`..`INT-195`; delete the matching mock-response fixtures and
  scenario trees.
- [x] `tests/integration/architecture_p1/test_script_tools_proxy.py`: remove
  `INT-192` and `INT-212`..`INT-217`; delete the matching mock-response
  fixtures and scenario trees.
- [x] `tests/integration/architecture_p1/test_int_064_to_069.py`: remove
  `INT-065`..`INT-069`; delete the matching mock-response fixtures and
  scenario trees.
- [x] `tests/integration/architecture_p1/test_physics_fluids_full.py`: remove
  `INT-131`..`INT-135`; delete the matching mock-response fixtures and
  scenario trees.
- [x] `tests/integration/architecture_p1/test_physics_fluids_extended.py`:
  remove `INT-138` and `INT-139`; delete the matching mock-response fixtures
  and scenario trees.
- [x] `tests/integration/architecture_p1/test_electronics_full.py`: remove
  `INT-132`, `INT-136`, `INT-137`, `INT-140`, `INT-141`, and `INT-217`;
  delete the matching mock-response fixtures and scenario trees.
- [x] `tests/integration/architecture_p1/test_benchmark_workflow.py`: remove
  `INT-200`, `INT-201`, `INT-202`, and `INT-203`; delete the matching
  mock-response fixtures and scenario trees.
- [x] `tests/integration/architecture_p1/test_engineering_loop.py`: remove
  `INT-205`; delete the matching mock-response fixture and scenario tree.
- [x] `tests/integration/architecture_p1/test_batch_execution.py`: remove
  `INT-043`; delete the matching mock-response fixture and scenario tree.
- [x] `tests/integration/architecture_p1/test_api_fuzzing.py`: remove
  `INT-044`; delete the matching mock-response fixture and scenario tree.
- [x] `tests/integration/architecture_p1/test_skills_sync.py`: remove
  `INT-045`; delete the matching mock-response fixture and scenario tree.
- [x] `tests/integration/architecture_p1/test_episode_replay.py`: remove
  `INT-206`; delete the matching mock-response fixture and scenario tree.
- [x] `tests/integration/architecture_p1/test_skill_overlay_promotion.py`:
  remove `INT-218`..`INT-223`; delete the matching mock-response fixtures and
  scenario trees.
- [x] `tests/integration/architecture_p1/test_infrastructure.py`: remove
  `INT-041` and `INT-042`; delete the matching mock-response fixtures and
  scenario trees.
- [x] Remove the orphaned motor/fluid/electronics fixture modules and
  scenario-tree content not already named above, including
  `tests/worker_heavy/simulation/test_builder_cots.py`,
  `tests/integration/architecture_p1/test_cots_geometry_import.py`,
  `tests/integration/architecture_p0/test_int_018_multipart_dfm_gate.py`,
  `tests/integration/architecture_p0/scripts/verify_overload.py`, and the
  `INT-005`, `INT-014`, `INT-034`, `INT-114`, `INT-129`, and `INT-142`
  mock-response entries.

### Final publication bundle

The publication bundle keeps the backend core that supports the paper claims:

- `controller/`
- `worker_light/`
- `worker_heavy/`
- `worker_renderer/`
- `shared/`
- `config/`
- `tests/`
- `docs/` for the retained backend/reference material

The following surfaces are excluded from the bundle because they either only
support development-time inspection or correspond to later-epic claims that are
outside the paper scope:

- `frontend/`, `website/`, and `scripts/experiments/` are operator or
  experimental surfaces, not part of the paper-critical backend path.
- Temporal worker shells and non-local orchestration helpers are
  development-tree support code for durable execution and do not add paper
  claims beyond the direct worker APIs already retained.
- The long-tail observability event families removed above only supported
  drafting, electronics, fluids, or steerability branches, so keeping them
  would overstate the publication bundle's scope.

## File-Level Change Set

The implementation phase should expect to touch these paths. The retained roots
listed above stay in the publication bundle and are not part of the prune list:

- `docs/academic-submission/final-project-report.tex`
- `docs/academic-submission/Problemologist_AI_Research_Matrix.md`
- `docs/academic-submission/Foundations of AI - Final Project Report.md`
- `docs/academic-submission/final_project_report.md`
- `docs/academic-submission/final_project_report.pdf`
- `docs/academic-submission/final_project_report.log`
- `docs/academic-submission/Problemologist_AI_Research_Matrix.odt`
- `docs/academic-submission/IEEEtranBST2.zip`
- `docs/academic-submission/export_report.sh`
- `docs/academic-submission/render_sources/README.md`
- `docs/academic-submission/paper_benchmark/`
- `docs/project-overview.md`
- `docs/source-tree-analysis.md`
- `docs/backend-reference.md`
- `docs/index.md`
- `docs/component-inventory.md`
- `docs/data-models.md`
- `docs/architecture.md`
- `docs/development-guide.md`
- `docs/deployment-guide.md`
- `docs/spec-coverage.md`
- `docs/project-scan-report.json`
- `docs/project-parts.json`
- `docs/qwen-performance.log.md`
- `docs/nightly-work-plans/`
- `docs/agent-workflow/`
- `specs/architecture/distributed-execution.md`
- `specs/architecture/agents/agent-harness.md`
- `specs/architecture/agents/tools.md`
- `specs/architecture/agents/prompt-management.md`
- `specs/architecture/agents/engineering-planner-technical-drawings.md`
- `specs/architecture/electronics-and-electromechanics.md`
- `specs/architecture/fluids-and-deformables.md`
- `specs/integration-test-list.md`
- `specs/integration-test-rules.md`
- `specs/devtools.md`
- `frontend/`
- `website/`
- `scripts/experiments/`
- `worker_light/agent_files/`
- `worker_heavy/workbenches/manufacturing_config.yaml`
- `worker_renderer/utils/manufacturing_config.yaml`
- `controller/agent/mock_llm.py`
- `controller/agent/mock_scenarios.py`
- `controller/agent/provider_tool_call_adapters/minimax_adapter.py`
- `controller/temporal_worker.py`
- `worker_heavy/temporal_worker.py`
- `controller/workflows/execution.py`
- `controller/workflows/heavy.py`
- `controller/workflows/simulation.py`
- `controller/workflows/preview.py`
- `controller/activities/execution.py`
- `controller/activities/simulation.py`
- `controller/activities/preview.py`
- `controller/api/ops.py`
- `controller/middleware/remote_fs.py`
- `controller/config/settings.py`
- `worker_light/app.py`
- `evals/logic/stack_profiles.py`
- `controller/agent/nodes/summarizer.py`
- `controller/agent/nodes/skills.py`
- `controller/agent/reward.py`
- `controller/agent/benchmark/render_seed.py`
- `controller/agent/benchmark/graph.py`
- `controller/graph/steerability_node.py`
- `controller/api/routes/steerability.py`
- `controller/services/steerability/`
- `controller/persistence/steering_memory.py`
- `controller/agent/render_validation.py`
- `controller/agent/tools.py`
- `controller/agent/prompt_manager.py`
- `controller/agent/handover_constants.py`
- `controller/agent/nodes/electronics_planner.py`
- `controller/agent/nodes/electronics_reviewer.py`
- `controller/api/routes/episodes.py`
- `controller/api/routes/datasets.py`
- `controller/api/routes/script_tools.py`
- `controller/api/main.py`
- `controller/agent/graph.py`
- `worker_heavy/simulation/frame_stream.py`
- `worker_heavy/simulation/loop.py`
- `worker_heavy/simulation/genesis_backend.py`
- `worker_heavy/simulation/objectives.py`
- `worker_heavy/utils/validation.py`
- `worker_heavy/utils/electronics.py`
- `worker_heavy/simulation/electronics.py`
- `shared/circuit_builder.py`
- `shared/wire_utils.py`
- `shared/rendering/stress_heatmap.py`
- `shared/observability/schemas.py`
- `shared/agents/config.py`
- `shared/script_contracts.py`
- `shared/utils/agent/__init__.py`
- `worker_heavy/utils/preview.py`
- `worker_heavy/utils/handover.py`
- `worker_heavy/utils/file_validation.py`
- `worker_renderer/api/routes.py`
- `worker_renderer/utils/technical_drawing.py`
- `shared/eval_artifacts.py`
- `shared/agent_templates/__init__.py`
- `shared/agent_templates/codex/scripts/submit_plan.py`
- `shared/agent_templates/codex/scripts/submit_for_review.py`
- `config/agents_config.yaml`
- `config/prompts.yaml`
- `shared/models/schemas.py`
- `shared/enums.py`
- `shared/models/steerability.py`
- `controller/api/schemas.py`
- `controller/api/tasks.py`
- `controller/api/main.py`
- `controller/agent/nodes/electronics_planner.py`
- `controller/agent/nodes/electronics_reviewer.py`
- `controller/agent/graph.py`
- `controller/agent/prompt_manager.py`
- `controller/agent/handover_constants.py`
- `controller/api/routes/steerability.py`
- `controller/api/routes/episodes.py`
- `controller/graph/steerability_node.py`
- `controller/services/steerability/`
- `controller/persistence/steering_memory.py`
- `controller/agent/nodes/base.py`
- `controller/agent/nodes/planner.py`
- `controller/agent/nodes/coder.py`
- `worker_heavy/simulation/loop.py`
- `worker_heavy/simulation/genesis_backend.py`
- `worker_heavy/simulation/objectives.py`
- `shared/agent_templates/codex/scripts/submit_plan.sh`
- `shared/agent_templates/codex/scripts/submit_engineering_plan.sh`
- `shared/agent_templates/codex/scripts/submit_for_review.sh`
- `dataset/evals/train_skills.py`
- `dataset/evals/eval_seed_update_autopilot.py`
- `dataset/evals/run_e2e_seed.py`
- `dataset/evals/materialize_seed_workspace.py`
- `dataset/data/seed/role_based/*.json`
- `dataset/data/seed/artifacts/**/benchmark_plan_technical_drawing_script.py`
- `dataset/data/seed/artifacts/**/solution_plan_technical_drawing_script.py`
- `dataset/data/seed/role_based/electronics_planner.json`
- `dataset/data/seed/role_based/electronics_reviewer.json`
- `dataset/data/seed/artifacts/electronics_planner/**`
- `dataset/data/seed/artifacts/electronics_reviewer/**`
- `dataset/data/generated/`
- `dataset/data/seed/role_based/git_agent.json`
- `dataset/data/seed/role_based/skill_agent.json`
- `dataset/data/seed/role_based/engineer_reviewer.json`
- `dataset/data/seed/artifacts/git_agent/`
- `dataset/data/seed/artifacts/skill_agent/`
- `tests/integration/frontend/`
- `tests/electronics/test_integration_electronics.py`
- `tests/integration/evals_p2/`
- `tests/integration/architecture_p1/`
- `tests/integration/mock_responses/`
- `tests/README.md`
- `config/lint_config.yaml`
- `config/clickhouse/zookeeper.xml`
- `config/skills_repo.lock.json`
- `config/reward_config.yaml` if the final paper does not cite the reward table
- `config/generator_config.yaml` if the final paper does not cite dataset-generation configuration

This list is intentionally conservative. If a path is only there for developer
comfort, compatibility, or experiment throughput, it should not survive the
publication bundle.
