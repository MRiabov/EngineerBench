# Agents

## Scope summary

- Primary focus: top-level architecture map of the agent layer.
- Defines the two main workflows: benchmark generator and engineer.
- Use this file first when deciding which agent-specific spec to open next.

We have two agents (or agent graphs): the benchmark generator and the engineer.

Runtime conversations use four message roles: `system`, `user`, `assistant`, and `tool`.
`assistant` is the agent-authored/model role; `tool` is runtime-owned tool responses; `system` carries deterministic runtime control messages such as gates, reminders, and recovery instructions.

## Benchmark generator workflow

The benchmark generator flow is:

1. `Benchmark Planner`
2. `Benchmark Plan Reviewer`
3. `Benchmark Coder`
4. `Benchmark Reviewer`

The split between benchmark plan review and benchmark execution review is mandatory.

- `Benchmark Plan Reviewer` checks planner-hand-off quality before implementation starts and persists reviewer output to the benchmark-plan review YAML pair in `reviews/`.
- `Benchmark Reviewer` remains the post-validation/post-simulation review gate for the implemented benchmark environment and persists reviewer output to the benchmark-execution review YAML pair in `reviews/`.
- After plan approval, a single `Benchmark Coder` creates and owns benchmark geometry changes in `benchmark_script.py` and any helper implementation modules. The `Benchmark Planner` does not receive `benchmark_script.py` before plan approval.

## Engineering workflow

The engineering flow has two separate review stages:

1. `Engineering Planner`
2. `Engineering Plan Reviewer` (plan-quality gate before coding)
3. `Engineering Coder` (unified implementation)
4. `Engineering Execution Reviewer` (post-validation/post-simulation execution gate)

The split between plan and execution reviewers is mandatory.

Implementation ownership is intentionally unified.

- After plan approval, a single `Engineering Coder` owns implementation changes to `solution_script.py` and any helper implementation modules.

- Plan review checks planning quality and contract completeness before implementation starts, and persists reviewer output to an engineering-plan review YAML pair in `reviews/`.

- Execution review runs only after validation/simulation success artifacts are present for the latest revision, then checks robustness/non-flakiness and plan adherence, and persists reviewer output to an engineering-execution review YAML pair in `reviews/`.

- Visual-inspection policy for vision-using roles is config-driven via `config/agents_config.yaml`; required roles must inspect render images through `inspect_media(...)` before valid completion/approval when images are available for the current node/revision (`submit_review` for reviewer native loops, `finish` for non-reviewer native loops). After any significant blocker or repeated failure on the same issue, inspect the current render or video evidence before the next revision or approval decision. If the same issue has failed more than three times in a row, keep inspecting render evidence on every subsequent retry until the blocker changes. Use `.agents/skills/render-evidence/SKILL.md` as the visual-inspection playbook.
