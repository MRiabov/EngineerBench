# Eval Artifact Inventory

Use this document when you need the full filename surface that can appear in seeded evals or eval-adjacent workspaces.
This is an inventory, not an acceptance-criteria doc. For any row marked "needs criteria", create a dedicated per-file reference from the fallback template and specialize it to the active validator.
The canonical per-file acceptance criteria now live in `specs/architecture/agents/agent-artifacts/`; this table keeps the same basenames for compactness.

## Scope

- Includes files that appear in current seeded workspaces.
- Includes files that are required or validated by the live runtime contract even if no seed currently uses them.
- Groups scenario-specific render assets by family instead of listing every image variant.
- Excludes incidental runtime noise such as `__pycache__/` and `*.pyc` from criteria work, even though those files can appear in working directories.

## Core Handoff Files

| Family | Example filenames or glob | Current criteria reference | Status |
| -- | -- | -- | -- |
| Benchmark planner narrative | `benchmark_plan.md` | `benchmark_plan_md_acceptance_criteria.md` | covered |
| Engineering planner narrative | `engineering_plan.md` | `engineering_plan_md_acceptance_criteria.md` | covered |
| Planner narrative legacy alias | `plan.md` | `plan_md_acceptance_criteria.md` | legacy compatibility only |
| Planner todo | `todo.md` | `todo_md_acceptance_criteria.md` | covered |
| Planner journal | `journal.md` | `journal_md_acceptance_criteria.md` | covered |
| Benchmark definition | `benchmark_definition.yaml` | `benchmark_definition_yaml_acceptance_criteria.md` | covered |
| Benchmark assembly context | `benchmark_assembly_definition.yaml` | `benchmark_assembly_definition_yaml_acceptance_criteria.md` | covered |
| Engineer assembly context | `assembly_definition.yaml` | `assembly_definition_yaml_acceptance_criteria.md` | covered |
| Benchmark implementation source | `benchmark_script.py` | `benchmark_script_py_acceptance_criteria.md` | covered |
| Engineer implementation source | `solution_script.py` | `solution_script_py_acceptance_criteria.md` | covered |
| Benchmark evidence scene | `benchmark_plan_evidence_script.py` | `benchmark_plan_evidence_script_py_acceptance_criteria.md` | covered |
| Engineer evidence scene | `solution_plan_evidence_script.py` | `solution_plan_evidence_script_py_acceptance_criteria.md` | covered |
| Deterministic validation output | `validation_results.json` | `validation_results_json_acceptance_criteria.md` | covered |
| Deterministic simulation output | `simulation_result.json` | `simulation_result_json_acceptance_criteria.md` | covered |
| Benchmark XML summary | `benchmark.xml` | none yet | needs criteria |
| Solution XML export | `solution.xml` | none yet | needs criteria |
| Refusal proof | `plan_refusal.md` | `plan_refusal_md_acceptance_criteria.md` | covered |
| Execution summary | `workbench_report.md` | `workbench_report_md_acceptance_criteria.md` | covered |
| Serialized scene snapshot | `scene.json` | `scene_json_acceptance_criteria.md` | covered |
| Precise motion/path contract | `payload_trajectory_definition.yaml` | `payload_trajectory_definition_yaml_acceptance_criteria.md` | covered |

## Reviewer and Routing Files

| Family | Example filenames or glob | Current criteria reference | Status |
| -- | -- | -- | -- |
| Benchmark plan-review manifest | `.manifests/benchmark_plan_review_manifest.json` | `reviewer_manifest_acceptance_criteria.md` | covered |
| Benchmark execution-review manifest | `.manifests/benchmark_review_manifest.json` | `reviewer_manifest_acceptance_criteria.md` | covered |
| Engineering plan-review manifest | `.manifests/engineering_plan_review_manifest.json` | `reviewer_manifest_acceptance_criteria.md` | covered |
| Engineering execution handoff manifest | `.manifests/engineering_execution_handoff_manifest.json` | `reviewer_manifest_acceptance_criteria.md` | covered, but see note |
| Benchmark plan review decision | `reviews/benchmark-plan-review-decision-round-<n>.yaml` | `benchmark_plan_review_yaml_acceptance_criteria.md` | covered |
| Benchmark plan review comments | `reviews/benchmark-plan-review-comments-round-<n>.yaml` | `benchmark_plan_review_yaml_acceptance_criteria.md` | covered |
| Benchmark execution review decision | `reviews/benchmark-execution-review-decision-round-<n>.yaml` | `benchmark_execution_review_yaml_acceptance_criteria.md` | covered |
| Benchmark execution review comments | `reviews/benchmark-execution-review-comments-round-<n>.yaml` | `benchmark_execution_review_yaml_acceptance_criteria.md` | covered |
| Engineering plan review decision | `reviews/engineering-plan-review-decision-round-<n>.yaml` | `engineering_plan_review_yaml_acceptance_criteria.md` | covered |
| Engineering plan review comments | `reviews/engineering-plan-review-comments-round-<n>.yaml` | `engineering_plan_review_yaml_acceptance_criteria.md` | covered |
| Engineering execution review decision | `reviews/engineering-execution-review-decision-round-<n>.yaml` | `engineering_execution_review_yaml_acceptance_criteria.md` | covered |
| Engineering execution review comments | `reviews/engineering-execution-review-comments-round-<n>.yaml` | `engineering_execution_review_yaml_acceptance_criteria.md` | covered |

### Note on the engineer execution manifest name

The live runtime contract currently uses `.manifests/engineering_execution_handoff_manifest.json`.
Some older references still say `engineering_execution_review_manifest.json`; treat that wording as legacy and update references to the handoff name when writing new criteria.

## Render and Simulation Evidence

| Family | Example filenames or glob | Current criteria reference | Status |
| -- | -- | -- | -- |
| Root render bundle alias | `renders/render_manifest.json` | `renders_acceptance_criteria.md` | covered as compatibility alias |
| Bundle-local render manifest | `renders/<bundle>/render_manifest.json` | `renders_acceptance_criteria.md` | covered |
| Render bundle history index | `renders/render_index.jsonl` | `renders_acceptance_criteria.md` | covered |
| Preview scene snapshot | `preview_scene.json` | `renders_acceptance_criteria.md` | covered |
| Video frame sidecar | `frames.jsonl` | `renders_acceptance_criteria.md` | covered |
| Object pose sidecar | `objects.parquet` | `renders_acceptance_criteria.md` | covered |
| Simulation video | `*.mp4` | `renders_acceptance_criteria.md` | covered by render family |
| Static render image | `*.png`, `*.jpg`, `*.jpeg` | `renders_acceptance_criteria.md` | covered by render family |
| Rendered vector image | `*.svg` | `renders_acceptance_criteria.md` | covered by render family |
| Vector export | `*.dxf` | `renders_acceptance_criteria.md` | covered by render family |
| Event log | `events.jsonl` | none yet | needs criteria |

## Geometry and Export Assets

| Family | Example filenames or glob | Current criteria reference | Status |
| -- | -- | -- | -- |
| Preview/export mesh | `*.glb` | none yet | needs criteria |
| Preview/export mesh | `*.obj` | none yet | needs criteria |
| Seed-specific geometry exports | asset names such as `base_plate.glb`, `goal_tray.obj`, `transfer_lane.glb` | none yet | needs criteria |

## Task-Specific Support Files

| Family | Example filenames or glob | Current criteria reference | Status |
| -- | -- | -- | -- |
| Prompt file | `prompt.md` | none yet | needs criteria |
| Git seed README | `README.md` | none yet | needs criteria |
| Git seed shared skill note | `shared_skill.md` | none yet | needs criteria |
| Git seed merge plan | `merge_plan.md` | none yet | needs criteria |
| Engineer coder run hints | `ec001_run_hints.md` | none yet | needs criteria |

## Runtime Noise and Exclusions

| Family | Example filenames or glob | Treatment |
| -- | -- | -- |
| Python bytecode cache | `*.pyc`, `__pycache__/` | Do not write criteria for these; treat them as incidental runtime noise. |
| Ad hoc local scratch files | `*.tmp`, editor swap files, manual notes not referenced by a role contract | Exclude from eval seeds. |

## Known Gaps

- Render history files (`render_index.jsonl`, `frames.jsonl`, `objects.parquet`, `preview_scene.json`) are covered by the broader render family doc, but they still deserve their own narrower docs if we want file-by-file coverage instead of one broad render reference.
- `benchmark.xml`, `solution.xml`, and `events.jsonl` still need dedicated criteria docs if we want every eval-visible file family to have its own reference.
- The git eval support files and prompt files are currently only covered by task prose, not per-file acceptance docs.
- The geometry export assets (`*.glb`, `*.obj`) need a criteria reference if you want explicit file-family coverage outside the render/rendering docs.
