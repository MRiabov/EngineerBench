# Agent Roles

## Scope Summary

- This file is the quick cross-role map.
- Detailed role sheets live in `roles-detailed/`.
- The benchmark generator and engineering graphs are the two main workflows.
- Helper roles support those workflows and should be revised through the same sheet-driven process.

## Shared Contract

- Prompts stay thin. Skills and detailed role sheets carry the reusable procedures.
- Planner and reviewer handoff artifacts are stage-scoped and fail closed on mismatch.
- If the detailed sheet, prompt, and skill disagree, the stricter approved handoff wins.
- Human revisions should keep the detailed sheet, `config/prompts.yaml`, and the role skill aligned.
- Planners use `submit_benchmark_plan()` or `submit_engineering_plan()` as the completion gate, depending on graph.
- Reviewers write the stage YAML pair and then run `bash scripts/submit_review.sh`.
- Coder roles validate and simulate the latest revision before calling their role-scoped review helper (`submit_benchmark_for_review()` or `submit_solution_for_review()`).
- Coder roles may write `plan_refusal.md` only when the approved plan is genuinely infeasible.
- When bug-report mode is enabled, any prompt-bearing role may file `bug_report.md` at the workspace root for infrastructure or runtime blockers. The report is diagnostic, not terminal, and it does not replace `journal.md`, `plan_refusal.md`, or review artifacts.
- When a role has render, drawing, or simulation evidence, inspect it after any significant blocker or repeated failure on the same issue before the next attempt. If the same issue has failed more than three times in a row, inspect render evidence on every subsequent retry until the blocker changes. Use `.agents/skills/render-evidence/SKILL.md` as the visual-inspection playbook.

## Benchmark Generator

| Role | Responsibility | Detailed Sheet |
| -- | -- | -- |
| `Benchmark Planner` | Designs the benchmark handoff package and benchmark-owned fixture contract. | [benchmark-planner.md](./roles-detailed/benchmark-planner.md) |
| `Benchmark Plan Reviewer` | Checks the benchmark plan before implementation starts. | [benchmark-plan-reviewer.md](./roles-detailed/benchmark-plan-reviewer.md) |
| `Benchmark Coder` | Implements the approved benchmark in `benchmark_script.py`. | [benchmark-coder.md](./roles-detailed/benchmark-coder.md) |
| `Benchmark Reviewer` | Reviews the implemented benchmark after validation and simulation. | [benchmark-reviewer.md](./roles-detailed/benchmark-reviewer.md) |

## Engineering Workflow

| Role | Responsibility | Detailed Sheet |
| -- | -- | -- |
| `Engineering Planner` | Turns benchmark context into an implementation-ready engineering plan. | [engineer-planner.md](./roles-detailed/engineer-planner.md) |
| `Engineering Plan Reviewer` | Reviews the planner handoff before engineering implementation starts. | [engineer-plan-reviewer.md](./roles-detailed/engineer-plan-reviewer.md) |
| `Engineering Coder` | Implements the approved engineering plan in `solution_script.py`. | [engineer-coder.md](./roles-detailed/engineer-coder.md) |
| `Engineering Execution Reviewer` | Performs the final execution review after validation and simulation. | [engineer-execution-reviewer.md](./roles-detailed/engineer-execution-reviewer.md) |

## Helper Roles

| Role | Responsibility | Detailed Sheet |
| -- | -- | -- |
| `COTS Search` | Returns exact catalog-backed part candidates from a single request string. | [cots-search.md](./roles-detailed/cots-search.md) |
| `Journalling Agent` | Compresses the run into `journal.md`. | [journalling-agent.md](./roles-detailed/journalling-agent.md) |
| `Skill Agent` | Stages skill deltas into `suggested_skills/`. | [skill-agent.md](./roles-detailed/skill-agent.md) |
| `Git Agent` | Handles repository plumbing and is not a model-facing workflow role. | [git-agent.md](./roles-detailed/git-agent.md) |

## What Humans Need To Tell An Agent

- The files the role owns and the files it must treat as read-only.
- The exact skill file that should act as the operating manual.
- The current native tool surface from `config/agents_config.yaml`.
- The runtime helpers that belong in authored scripts or supporting probes.
- The evidence inspection rule for the current revision.
- The submission gate that closes the role.
- Any special contract, such as COTS identity, motion proof, or verification.

## Detailed Sheets

- [Role Sheets Index](./roles-detailed/README.md)
