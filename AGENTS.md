# Mandatory rules for agents

## Important context and specs

To save refactors and speed up debugging, read `@specs/desired_architecture.md` first on any request. It is the architecture entrypoint and source of truth for the split docs below.

### System goals

- `@specs/architecture/primary-system-objectives.md` - end goals, expected outputs, and product-level purpose of the benchmark and engineer system.

### Agents

- `@specs/architecture/agents/overview.md` - high-level map of the two main agent graphs (benchmark generator and engineer).
- `@specs/architecture/agents/roles.md` - role behavior and outputs for planner/implementer/reviewer flows, including sample handoff artifacts.
- `@specs/architecture/agents/roles-detailed/README.md` - detailed role sheets for prompt and skill revisions.
- `@specs/architecture/agents/handover-contracts.md` - strict contracts for files and decision flow between planner, implementer, and reviewer stages.
- `@specs/architecture/agents/agent-harness.md` - runtime framework choices, debug Codex backend, trace requirements, and workspace/prompt/skill-loading contracts.
- `@specs/architecture/agents/prompt-management.md` - unified prompt-source model, backend appendices, shared template context, and the skills-versus-prompts boundary.
- `@specs/architecture/agents/engineering-planner-technical-drawings.md` - planner drafting contract, technical drawing review rules, and `render_technical_drawing()` expectations.
- `@specs/architecture/agents/agent-skill.md` - canonical skill-tree source, authoring contract, workspace materialization, and skill-improvement loop.
- `@specs/architecture/agents/artifacts-and-filesystem.md` - filesystem/path-permission contracts and artifact ownership.
- `@specs/architecture/agents/agent-artifacts/README.md` - file-level acceptance criteria for seeded workspace artifacts.
- `@specs/architecture/agents/tools.md` - ReAct-callable tool surface, Python utility functions, and planner/reviewer submission gates.
- `@specs/architecture/agents/auxiliary-agent-tools.md` - secondary wrappers, diagnostics, and experimental helper surfaces that do not belong in the main tool contract.
- `@specs/architecture/agents/reward-architecture.md` - reward shaping used for downstream training and optimization.
- `@specs/architecture/agents/definitions-of-success-and-failure.md` - objective AABB rules, runtime randomization, benchmark-side motion exception, and failure taxonomy.

### Runtime and quality gates

- `@specs/architecture/distributed-execution.md` - controller/light/heavy worker topology, routing, persistence, and Temporal boundaries.
- `@specs/architecture/CAD-and-other-infra.md` - CAD metadata, rendering direction, schema contracts, and supporting infra assumptions.
- `@specs/architecture/cots-geometry-import.md` - class-first COTS resolution contract, typed class registry, interface-faithful proxy policy, and verification expectations for COTS parts.
- `@specs/architecture/evals-architecture.md` - fast/medium/slow eval tiers, quality gates, terminal states, and fail-closed requirements.
- `@specs/architecture/simulation-and-rendering.md` - physics assumptions, backend split, constraints, and rendering/preview ownership.
- `@specs/architecture/fluids-and-deformables.md` - Genesis-backed fluid simulation, deformable-material contracts, stress objectives, smoke-test policy, and WP2-specific artifacts.
- `@specs/architecture/electronics-and-electromechanics.md` - electrical schema, circuit-validation gate, 3D wire routing, power-gated actuation, and WP3-specific artifacts.
- `@specs/architecture/observability.md` - telemetry schema, event catalog, metrics, lineage IDs, and debugging/backups/review tracking.
- `@specs/devtools.md` - local bootstrap, integration orchestration, eval runners, workspace materialization, and contract validators.

If this file and `@specs/desired_architecture.md` ever disagree, treat `@specs/desired_architecture.md` as the source of truth.

## Rules

In this repo, the convention is to not use unit tests because they are flaky, but to use only real integration tests. They are faster to debug against.

When you need to verify, reproduce, or debug behavior at the system boundary, use `./scripts/run_integration_tests.sh` as the only integration test entrypoint. Do not run plain `pytest` for integration verification.

When implementing new logic, verify it against the narrowest relevant integration slice first, then widen only if needed. The integration-test rules live at @specs/integration-test-rules.md and the canonical test catalog lives at @specs/integration-test-list.md

When asked to edit, fix, or add evaluation seeds, use `.agents/skills/eval-creation-workflow` for writing and debugging the seeds, and validate them with `scripts/validate_eval_seed.py`.

______________________________________________________________________

This is all for the critical rules.

@RTK.md
