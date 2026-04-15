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
- Hard entry bundle: `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`
- Reviewer gate: `.manifests/benchmark_plan_review_manifest.json`
- Current corpus extras: `benchmark_script.py`, `journal.md`

### `benchmark_coder`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_criteria`
- Hard entry bundle: `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_script.py`
- Current corpus extras: `journal.md`

### `benchmark_reviewer`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_decision`, `expected_criteria`
- Hard entry bundle: `benchmark_script.py`, `validation_results.json`, `simulation_result.json`, `.manifests/benchmark_review_manifest.json`
- Reviewer gate also reads: `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, and render evidence when present
- Current corpus extras: `benchmark.xml`, `journal.md`

### `engineer_planner`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_criteria`
- Hard entry bundle: `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_script.py`
- Current corpus extras: usually just the core bundle

### `engineer_plan_reviewer`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_decision`, `expected_criteria`
- Hard entry bundle: `benchmark_assembly_definition.yaml`, `benchmark_script.py`
- Reviewer gate also reads: `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`
- Reviewer-manifest gate: `.manifests/engineering_plan_review_manifest.json`
- Current corpus extras: `journal.md`

### `engineer_coder`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_criteria`
- Hard entry bundle: `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_script.py`, `solution_script.py`, `payload_trajectory_definition.yaml`
- `todo.md` for this role is one representative example of the general rule that seeded downstream rows should only list current-stage work items and should not keep prior planner/reviewer TODO history or completed bookkeeping items.
- Current corpus extras: `.manifests/engineering_plan_review_manifest.json`, `reviews/engineering-plan-review-round-1.md` or analogous review notes, `journal.md`, seed-specific run hints such as `ec001_run_hints.md`

### `engineer_execution_reviewer`

- Dataset row: `id`, `task`, `seed_artifact_dir`, `expected_criteria`, `expected_decision`
- Hard entry bundle: `solution_script.py`, `benchmark_script.py`, `benchmark_assembly_definition.yaml`, `validation_results.json`, `simulation_result.json`, `.manifests/engineering_execution_handoff_manifest.json`
- Reviewer gate also reads: `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, `.manifests/engineering_plan_review_manifest.json`, and render evidence when present
- Current corpus extras: `reviews/engineering-plan-review-round-1.md` or analogous review notes, `renders/render_index.jsonl`, `solution.xml`, `journal.md`

## Notes

- The prompt-only rows in this corpus are intentionally thin; they do not use `seed_artifact_dir`.
- The seeded rows above are the ones that matter for the seeded-entry validator and the role-specific review gates.
- If a new role gets added, put it here before adding a more specific acceptance-criteria reference.
