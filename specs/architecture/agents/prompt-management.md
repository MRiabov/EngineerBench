# Prompt Management

## Scope summary

This document defines the unified prompt source model for controller/API agents and CLI-provider agents. It covers role prompts, appendices, prompt-context templates, merge order, and the prompt-side boundary to skills. The skill-tree contract, authoring shape, and improvement loop live in [agent-skill.md](./agent-skill.md). Migration mechanics live in [prompt-management-unification.md](../../migrations/minor/prompt-management-unification.md).

## Purpose

The prompt layer is intentionally thin. It frames the agent, states workspace and submission rules, and only points the model at skills when the backend does not already load them from the workspace tree. Detailed business logic, procedures, and examples belong in skills.

The target state keeps prompt optimization unified. We do not maintain one base prompt source for API and another base prompt source for CLI-provider backends.

## Design goals

1. One PromptManager owns prompt assembly for every backend family.
2. The same prompt source model feeds controller/API and CLI-provider runtimes.
3. Base prompts remain short, role-focused, and operational.
4. Backend appendices describe backend-family runtime differences, not domain knowledge.
5. Skills own detailed procedures, reasoning patterns, and examples.
6. Prompt-context templates are first-class prompt inputs, not loose starter files.
7. Tool summaries should reflect actual runtime registration or central runtime config.
8. The unified source should be the place where future optimization works from.

## Canonical sources

The unified prompt manager treats these inputs as authoritative:

- `config/prompts.yaml`: structured role prompts and appendix fragments.
- `shared/agent_templates/`: prompt-context files, helper scripts, and boilerplate that belong in the workspace context.
- `shared/assets/template_repos/`: role-scoped starter workspace material copied into the run-local workspace.
- the checked-in `.agents/skills/` tree and its workspace materializations, as described in [agent-skill.md](./agent-skill.md), plus any compact generated index derived from the active skill tree when the backend needs one. When a skill-training run materializes a session-local `suggested_skills/` overlay/worktree, that overlay is the active skill tree for that run. Those runtime copies are inputs to the agent, not a separate prompt source.
- backends that know the session-local overlay root may surface it through `PROBLEMOLOGIST_SKILL_OVERLAY_ROOT` so catalog helpers can render overlay-first skill references without duplicating the resolution rule.
- `worker_light/agent_files/`: legacy compatibility mirror only.
- runtime-generated context: agent identity, task ID, workspace state, backend selection, and tool registration.

`common.code_template` is legacy once equivalent content lives in the managed prompt sources and prompt-context templates. It is not the canonical source for the unified model.

## Source order

Prompt blocks in `config/prompts.yaml` should follow the runtime call order.

For the core benchmark graph, the order is: `benchmark_planner` -> `benchmark_plan_reviewer` -> `benchmark_coder` -> `benchmark_reviewer`.

For the core engineering graph, the order is: `engineer_planner` -> `engineer_plan_reviewer` -> `engineer_coder` -> `engineer_execution_reviewer`.

Any other first-class role family follows the same runtime-order rule.

Helper agents should follow the same rule: place them where the runtime calls them, and keep them grouped after the core graphs when that does not conflict with execution order.

## PromptManager responsibilities

The PromptManager is the only component that merges prompt fragments into final prompt text. No logic outside `PromptManager` should build prompt text; runtime code such as `evals/logic/codex_workspace.py` may only provide context, template variables, or other non-prompt state to the manager.

It must:

1. read the shared source model,
2. choose the backend family,
3. render the active role prompt,
4. add the shared appendix,
5. add the bug-report appendix when the global bug-report mode is active,
6. add the backend appendix,
7. add the CLI-provider appendix when the backend family is `cli_based`,
8. append runtime-generated context,
9. append a compact generated skill index when the backend family needs one, preferably derived from the active skill tree for the current session.

The backend choice selects which appendix branch is used. It does not select a different prompt manager or a different prompt source model.

## Prompt layers

### Role prompts

Role prompts define the agent identity and the minimum operating contract for the role.

They should stay close to the current engineer_coder style: compact, direct, and workspace-aware.

Role prompts should name the authored source file, the read-only context files, and the submission path when that matters for the role. They should not restate the full workflow that already lives in skills or runtime contracts.

### Shared appendices

Shared appendices apply to every role and every backend family.

They should cover rules such as workspace-relative paths, system-owned metadata, submission hygiene, and common constraints that are universal across the agent runtime.

Bug-report appendices are also global, but they are conditional: PromptManager appends them only when the top-level bug-report mode is enabled in `config/agents_config.yaml`.

If a rule is universal but long, it probably belongs in the relevant runtime contract or skill instead of the shared appendix.

### Backend appendices

Backend appendices explain the differences between `cli_based` and `api_based` execution.

The appendix may include the tool surface that matters to that backend family, local submission helpers, native tool-loop reminders, and any other runtime-specific operational notes.

The appendix should stay short. It should help the model choose the right runtime behavior, not teach the domain.

### CLI-provider appendices

CLI-provider appendices are conditional additions that only appear when the backend family is `cli_based`.

They live in `config/prompts.yaml` under `appendices.cli` and can include a shared fragment plus provider-specific fragments keyed by provider name, such as `codex` or `qwen`.

These appendices carry provider-specific operational reminders. They do not replace the generic `cli_based` backend appendix, and they do not become a second prompt source model.

### Runtime-generated context

Runtime-generated context includes facts that only exist when the workspace is materialized.

Examples include the agent name, task ID, seed dataset name, workspace-relative file inventory, render availability, active backend selection, and the registered tool surface.

This context is injected by the runtime. It is not a manually maintained prompt template.

## Skills

Skills own the durable, reusable guidance that prompts should not have to carry: procedures, repair patterns, domain heuristics, and concrete examples.

The canonical skill-tree contract, authoring shape, loading model, and improvement loop live in [agent-skill.md](./agent-skill.md).

PromptManager may append a compact generated catalog for discoverability when a backend needs it, but it must not re-author skill bodies or turn skills into a second prompt system.
When skill training is active, the compact catalog should reflect the session-local overlay if one exists.

The rule of thumb is simple: prompts frame the work; skills explain the work.

## Backend families

The unified model distinguishes backend families, not separate prompt worlds.

The current backend families are:

- `cli_based`
- `api_based`

The backend family determines which appendix branch is used and which runtime reminders are shown. It does not change the canonical prompt source or the ownership of the prompt manager.
CLI-provider runs do not need the prompt to restate the full skill inventory when the workspace already exposes the relevant skill files.

## Assembly order

The final prompt should read in this order:

1. role prompt
2. shared appendix
3. bug-report appendix, when active
4. backend appendix
5. CLI-provider appendix, when active
6. runtime-generated context
7. compact generated skill index, when needed

That order keeps the base prompt stable while still allowing backend-specific and runtime-specific context to appear in a predictable place.

## Prompt-context templates

`shared/agent_templates/` is part of the prompt-context contract.

The files in that directory are intentional prompt inputs. They should be treated as context-bearing source artifacts, not as ad hoc runtime defaults.

`shared/assets/template_repos/` provides the role-scoped starter workspace material that is copied into the run-local workspace before the prompt is materialized. `worker_light/agent_files/` may still exist as a compatibility mirror, but it is not canonical.

The manager should treat these files the same way it treats prompt text: as inputs to the agent's starting context.

## Tool-surface summaries

Backend appendices may mention tool availability, but those summaries should be derived from the actual runtime registration or central runtime config whenever possible.

This matters because tool availability is a runtime fact, not a hand-edited promise. If the runtime exposes different tools, the prompt should reflect that change through the source of truth instead of by editing many role prompts.

CLI-based agents may rely on shell scripts and local workspace files. API-based agents may rely on controller-mediated tool loops and native runtime tools. The prompt should say enough for the agent to act correctly, but no more.

## Change boundaries

A change should go to the smallest source that owns it.

- Role identity changes go to the role prompt.
- Universal workspace rule changes go to the shared appendix or the runtime contract.
- Backend tool or submission changes go to the backend appendix, the CLI-provider appendix, or the runtime-generated summary source.
- Starter workspace or helper script changes go to `shared/agent_templates/`.
- Business procedure changes go to skills.

This boundary keeps the prompt surface short and pushes durable logic into the place that can own it best.

## Common failure modes

- Duplicating skill bodies in prompts.
- Hand-maintaining tool lists in more than one backend-specific location.
- Treating `worker_light/agent_files/` as a source of truth.
- Letting backend appendices absorb domain logic.
- Allowing role prompts to grow into mini playbooks.
- Building CLI-provider and API prompts from separate unshared source models.

## Validation expectations

Prompt changes should be validated against materialized workspaces and the actual runtime surfaces that render them.

The goal is to confirm that the unified source reads correctly in both CLI-based and API-based backends and that prompt fragments still match the files and helpers the workspace exposes.

## Example schema

```yaml
role_prompts:
  engineer_coder: |
    You are the Engineer Coder.
    Keep the implementation concise and work in solution_script.py.
  engineer_planner: |
    You are the Engineering Planner.
    Prepare the handoff artifacts and keep the plan internally consistent.
  benchmark_coder: |
    You are the Benchmark Coder.
    Implement the approved benchmark in benchmark_script.py.

appendices:
  shared: |
    Use workspace-relative paths only.
    Treat .manifests/ as system-owned.
  bug_reporting: |
    If infrastructure or runtime plumbing blocks progress, write `bug_report.md` at the workspace root and keep working unless the task is otherwise blocked.
  backend:
    cli_based: |
      Use the local workspace and shell helpers when they are available.
    api_based: |
      Use the controller-backed runtime and native tool loop.
  cli:
    shared: |
      Re-read the workspace prompt and local files after a resume or handoff boundary.
    providers:
      codex: |
        Codex-specific reminder: keep the local shell helper flow and resume syntax in mind.
      qwen: |
        Qwen-specific reminder: use `render_cad(...)` for CAD geometry, then inspect the generated render files with `read_file` even if you think you do not have a dedicated image tool. Reread the active workspace state before answering and do not rely on memory across turns.
```

The shape above is illustrative, not exhaustive. The concrete YAML layout must include any active role families and helper agents if they remain first-class, but the ownership model should remain the same.

## Prompt optimization

DSPy-optimized prompts are a later layer derived from the same unified source model.

They should not become a second prompt-authoring system. If optimization is added later, it should optimize the unified base and its appendices, not fork a separate backend-specific prompt canon.

## Boundaries

- This document defines prompt structure and prompt ownership.
- It does not define migration steps.
- It does not replace the agent harness or filesystem ownership specs.
- It does not move business logic out of skills.
- It does not make `shared/agent_templates/` an execution layer; it makes it part of the prompt-context contract.
