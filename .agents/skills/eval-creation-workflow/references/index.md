# Seed Artifact Reference Index

Use this index when creating or repairing seeded eval rows.
The same filename can appear in multiple stages, so always check the active role contract before editing.
The canonical file-specific acceptance criteria now live in `specs/architecture/agents/agent-artifacts/`; the files in this folder are workflow helpers, maps, and fallback notes.
When this index conflicts with the live validator, `config/prompts.yaml`, or the architecture docs, the live contract wins.
The acceptance-criteria files linked from this index should prefer `References` sections with markdown heading citations and code/function hooks. Treat integration tests as secondary checks only.

## File Map

| Artifact | Typical roles | Main gate |
| -- | -- | -- |
| `benchmark_plan.md` | benchmark planners, benchmark plan reviewers | Benchmark-stage heading schema, exact identifiers, cross-file consistency |
| `engineering_plan.md` | engineering planners, plan reviewers, downstream coders | Engineering-stage proof sections, exact identifiers, and cross-file consistency |
| `plan.md` | legacy compatibility alias only | Historical replay bundles; prefer the split filenames for new seeds |
| `todo.md` | planners, coders, reviewers | Checkbox integrity and stage-correct completion state |
| `journal.md` | planners, coders, reviewers | Concrete attempt logging with blockers, observations, and next steps |
| `benchmark_definition.yaml` | benchmark flow, downstream engineer intake | Strict objective geometry, randomization, benchmark-owned fixture metadata, and cap derivation agreement |
| `benchmark_assembly_definition.yaml` | benchmark planner/reviewer, engineer intake | Read-only benchmark fixture/motion contract, full `AssemblyDefinition` shape, and motion visibility agreement |
| `assembly_definition.yaml` | engineering planners/coders | Costing inputs, `final_assembly`, totals, motion metadata, and solution-source agreement |
| `benchmark_plan_evidence_script.py` | benchmark planner | Legible benchmark evidence scene that preserves inventory labels and quantities |
| `solution_plan_evidence_script.py` | engineering planner | Draft engineering evidence scene that matches the proposed assembly |
| `benchmark_script.py` | benchmark coder, benchmark reviewer, engineer intake | Approved benchmark geometry source and read-only downstream context |
| `solution_script.py` | engineering coder, execution reviewer | Implemented solution geometry and execution source of truth; must mirror `assembly_definition.yaml` inventory/motion contract |
| `validation_results.json` | coder/reviewer flows | Latest-revision deterministic validation evidence |
| `simulation_result.json` | coder/reviewer flows | Latest-revision deterministic simulation evidence |
| `plan_refusal.md` | refusal paths | Structured refusal proof with concrete evidence and role-specific reasons |
| `file-contract-template.md` | new artifact types / fallback | Structural template for writing a concrete per-file acceptance reference |
| `payload_trajectory_definition.yaml` | engineer coder / motion proof | Higher-resolution engineer-owned path and contact proof |
| `artifact_inventory.md` | all eval/file families | Inventory of file families observed in seeded evals and live workspace contracts |
| `reviews/benchmark-plan-review-*.yaml` | benchmark plan review | `benchmark_plan_review_yaml_acceptance_criteria.md` |
| `reviews/benchmark-execution-review-*.yaml` | benchmark execution review | `benchmark_execution_review_yaml_acceptance_criteria.md` |
| `reviews/engineering-plan-review-*.yaml` | engineering plan review | `engineering_plan_review_yaml_acceptance_criteria.md` |
| `reviews/engineering-execution-review-*.yaml` | engineering execution review | `engineering_execution_review_yaml_acceptance_criteria.md` |
| `renders/**` | any role with visual inspection | `renders_acceptance_criteria.md` and `inspect_media(...)` on the latest revision's actual media |
| `scene.json` | benchmark coder, selected downstream seed workflows | Serialized scene snapshot that must match the authored source and evidence |
| `workbench_report.md` | execution-review flows | Short outcome summary consistent with validation/simulation |
| `role_input_index.md` | all roles | Per-role input bundles and current corpus row shapes |

## Canonical Validation Path

- `scripts/validate_eval_seed.py` is the first gate for seeded rows.
- It seeds the workspace through `evals/logic/workspace.py::seed_eval_workspace` and then runs `evals/logic/workspace.py::preflight_seeded_entry_contract`.
- The preflight path splits into:
  - `controller/agent/node_entry_validation.py::evaluate_node_entry_contract` for required state fields, required artifacts, and custom checks
  - `controller/agent/node_entry_validation.py::validate_seeded_workspace_handoff_artifacts` for file-specific semantic checks
- Tighten any file-specific reference against those code paths when a doc feels too generic.

## Reading Order

1. Open the artifact-specific reference for the file you are fixing.
2. Check the active role prompt and role-specific schema or validator.
3. Compare the seed row against the live validator output.
4. Repair the smallest source-level mismatch first.

## Default Failure Pattern

If a seed fails before LLM evaluation, it is usually one of these:

- wrong file set for the role
- stale revision evidence
- placeholder text left in a seeded file
- schema drift between planner handoff files
- missing visual inspection or review manifest

## Troubleshooting Notes

- [common_seed_failure_patterns.md](common_seed_failure_patterns.md) - compact triage patterns for the repeated failure shapes above, with the source-level fix to apply first.
