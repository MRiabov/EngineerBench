# Agent Artifact Contracts

## Purpose

This directory is the canonical library for file-level acceptance criteria in seeded eval workspaces.
Each document explains what the artifact is for, which hard checks it must satisfy, what makes it high quality, and what reviewers should look for when validating it.

Use this library when a role must seed or judge a concrete workspace file rather than a generic stage concept.

## How To Use

1. Open this index first to identify the artifact family.
2. Open the matching artifact contract before authoring or reviewing a seed.
3. Use `specs/architecture/agents/handover-contracts.md` and `specs/architecture/agents/artifacts-and-filesystem.md` for the surrounding stage and ownership rules.
4. Treat these documents as canonical; the eval-creation skill references should point here rather than duplicate the contract text.

## File Map

| Artifact | Main purpose | Reviewer focus |
| -- | -- | -- |
| [benchmark_plan.md](./benchmark_plan_md_acceptance_criteria.md) | Benchmark planner narrative for benchmark planners and benchmark plan reviewers | Benchmark objective, exact inventory, and stage scope |
| [engineering_plan.md](./engineering_plan_md_acceptance_criteria.md) | Engineering planner narrative for engineering planners and engineering plan reviewers | Solution intent, proof structure, and stage scope |
| [todo.md](./todo_md_acceptance_criteria.md) | Execution-order checklist for the current stage | Ordered, actionable, stage-correct items |
| [journal.md](./journal_md_acceptance_criteria.md) | Debugging and attempt log | Concrete blockers, probes, and next steps |
| [bug_report.md](./bug_report_md_acceptance_criteria.md) | Maintainer-facing runtime blocker report | Infra/runtime failure details and archive metadata |
| [benchmark_definition.yaml](./benchmark_definition_yaml_acceptance_criteria.md) | Benchmark task geometry and caps | Geometry validity, randomization, and benchmark-contract fidelity |
| [benchmark_assembly_definition.yaml](./benchmark_assembly_definition_yaml_acceptance_criteria.md) | Benchmark-owned fixture and motion contract | Read-only motion visibility and geometry fidelity |
| [assembly_definition.yaml](./assembly_definition_yaml_acceptance_criteria.md) | Engineer-owned solution contract | Cost, weight, final assembly, and motion consistency |
| [benchmark_plan_evidence_script.py](./benchmark_plan_evidence_script_py_acceptance_criteria.md) | Benchmark evidence scene source | Inventory preservation and readability |
| [solution_plan_evidence_script.py](./solution_plan_evidence_script_py_acceptance_criteria.md) | Engineering plan evidence scene source | Proposed assembly fidelity and readability |
| [benchmark_script.py](./benchmark_script_py_acceptance_criteria.md) | Approved benchmark geometry source | Exact benchmark inventory and read-only downstream context |
| [solution_script.py](./solution_script_py_acceptance_criteria.md) | Implemented solution source of truth | Assembly mirroring, runtime exposure, and grounded identifiers |
| [validation_results.json](./validation_results_json_acceptance_criteria.md) | Deterministic validation evidence | Revision accuracy and parseable failure reasons |
| [simulation_result.json](./simulation_result_json_acceptance_criteria.md) | Deterministic simulation evidence | Motion fidelity and latest-revision consistency |
| [plan_refusal.md](./plan_refusal_md_acceptance_criteria.md) | Structured infeasibility proof | Concrete evidence and role-specific refusal reasons |
| [current_role.json](./current_role_json_acceptance_criteria.md) | Active role marker for the current workspace node | Stage match, node-transition freshness, and fail-closed role lookup |
| [workbench_report.md](./workbench_report_md_acceptance_criteria.md) | Short outcome summary | Consistency with validation, simulation, and review |
| [scene.json](./scene_json_acceptance_criteria.md) | Serialized scene snapshot | Exact identities and revision fidelity |
| [payload_trajectory_definition.yaml](./payload_trajectory_definition_yaml_acceptance_criteria.md) | Required higher-resolution motion and contact proof | Spawn-position start, goal-center finish, and waypoint coherence |
| [reviewer manifest](./reviewer_manifest_acceptance_criteria.md) | Stage routing gate metadata for benchmark and engineering reviewers | Latest revision, stage match, and fail-closed routing |
| [benchmark plan review YAML](./benchmark_plan_review_yaml_acceptance_criteria.md) | Benchmark plan review decision/comments pair | Stage-canonical review output and evidence grounding |
| [benchmark execution review YAML](./benchmark_execution_review_yaml_acceptance_criteria.md) | Benchmark execution review decision/comments pair | Latest implementation evidence and stage-canonical routing |
| [engineering plan review YAML](./engineering_plan_review_yaml_acceptance_criteria.md) | Engineering plan review decision/comments pair | Plan-quality gate and evidence grounding |
| [engineering execution review YAML](./engineering_execution_review_yaml_acceptance_criteria.md) | Engineering execution review decision/comments pair | Final implementation evidence and routing |
| [renders](./renders_acceptance_criteria.md) | Persistent visual evidence family | Actual media inspection and revision attribution |

## Contract Rule

The artifact contracts in this directory are the source of truth for file-level seeded-eval acceptance.
If a workflow guide, seed helper, or role sheet disagrees with one of these documents, the document here wins until the higher-level architecture is deliberately revised.
