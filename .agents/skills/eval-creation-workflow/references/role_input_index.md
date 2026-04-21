# Role Input Index

This is the per-role input map for the current seeded-eval corpus.
Use `references/index.md` for the file map, then use this document when you need the exact input bundle for a specific role.

## Rules

- Prompt-only rows use `id`, `task`, and `expected_criteria` unless the row is a reviewer row, in which case `expected_decision` is also present.
- Seeded rows use `id`, `task`, `seed_artifact_dir`, and `expected_criteria`; reviewer rows also carry `expected_decision`.
- Files under `reviews/`, `.manifests/`, `renders/`, `journal.md`, `solution.xml`, `benchmark.xml`, `events.jsonl`, `__pycache__/`, or ad hoc run-hint notes are seed-specific extras unless a role section below says they are part of the hard entry bundle.
- If a row is a refusal or retry case, seed the refusal evidence or review evidence that explains the failure instead of describing it only in prose.

## Prompt-Only Rows

### `benchmark_planner`

- Dataset row: `id`, `task`, `expected_criteria`
- Workspace at entry: none; this corpus currently uses prompt-only rows for benchmark planning.

## Seeded Rows

### `benchmark_plan_reviewer`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_decision`, `expected_criteria`
- Editable starter files: `reviews/benchmark-plan-review-decision-round-<n>.yaml`, `reviews/benchmark-plan-review-comments-round-<n>.yaml`
- Read-only reference inputs: `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `payload_trajectory_definition.yaml` when present, `benchmark_plan_evidence_script.py`, and `.manifests/benchmark_plan_review_manifest.json`
- Reviewer gate: `.manifests/benchmark_plan_review_manifest.json`
- Current corpus extras: `benchmark_script.py`, `journal.md`

### `benchmark_coder`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_criteria`
- Editable starter files: `benchmark_script.py`, `todo.md`, `journal.md`, and any benchmark-side helper modules this role is expected to write
- Read-only reference inputs: `benchmark_plan.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_plan_evidence_script.py`, `validation_results.json`, `simulation_result.json`, render evidence, and reviewer artifacts
- Current corpus extras: `journal.md`

### `benchmark_reviewer`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_decision`, `expected_criteria`
- Editable starter files: `reviews/benchmark-execution-review-decision-round-<n>.yaml`, `reviews/benchmark-execution-review-comments-round-<n>.yaml`
- Read-only reference inputs: `benchmark_script.py`, `validation_results.json`, `simulation_result.json`, `.manifests/benchmark_review_manifest.json`, `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_plan_evidence_script.py`, and render evidence when present
- Current corpus extras: `benchmark.xml`, `journal.md`

### `engineer_planner`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_criteria`
- Editable starter files: `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, `solution_plan_evidence_script.py`, and `journal.md` when the corpus includes it
- Read-only reference inputs: `benchmark_assembly_definition.yaml`, `benchmark_script.py`, render evidence, and downstream review artifacts
- Current corpus extras: usually just the core bundle

### `engineer_plan_reviewer`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_decision`, `expected_criteria`
- Editable starter files: `reviews/engineering-plan-review-decision-round-<n>.yaml`, `reviews/engineering-plan-review-comments-round-<n>.yaml`
- Read-only reference inputs: `benchmark_assembly_definition.yaml`, `benchmark_script.py`, `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, `solution_plan_evidence_script.py`, and the plan-review manifest
- Reviewer-manifest gate: `.manifests/engineering_plan_review_manifest.json`
- Current corpus extras: `journal.md`

### `engineer_coder`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_criteria`
- Editable starter files: `solution_script.py`, `payload_trajectory_definition.yaml`, `todo.md`, `journal.md`, `plan_refusal.md`, and any helper modules this role is expected to write
- Read-only reference inputs: `engineering_plan.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_script.py`, `solution_plan_evidence_script.py`, validation/simulation artifacts, render evidence, and review artifacts
- `todo.md` for this role is one representative example of the general rule that seeded downstream rows should only list current-stage work items and should not keep prior planner/reviewer TODO history or completed bookkeeping items.
- Current corpus extras: `.manifests/engineering_plan_review_manifest.json`, `reviews/engineering-plan-review-round-1.md` or analogous review notes, `journal.md`, seed-specific run hints such as `ec001_run_hints.md`

### `engineer_execution_reviewer`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_criteria`, `expected_decision`
- Editable starter files: `reviews/engineering-execution-review-decision-round-<n>.yaml`, `reviews/engineering-execution-review-comments-round-<n>.yaml`
- Read-only reference inputs: `solution_script.py`, `benchmark_script.py`, `benchmark_assembly_definition.yaml`, `validation_results.json`, `simulation_result.json`, `.manifests/engineering_execution_handoff_manifest.json`, `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, `.manifests/engineering_plan_review_manifest.json`, and render evidence when present
- Current corpus extras: `reviews/engineering-plan-review-round-1.md` or analogous review notes, `renders/render_index.jsonl`, `solution.xml`, `journal.md`

## Notes

- The prompt-only rows in this corpus are intentionally thin; they do not use `seed_artifact_dir`.
- The seeded rows above are the ones that matter for the seeded-entry validator and the role-specific review gates.
- If a new role gets added, put it here before adding a more specific acceptance-criteria reference.
