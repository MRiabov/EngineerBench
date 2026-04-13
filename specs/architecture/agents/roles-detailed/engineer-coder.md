# Engineering Coder

## Role Summary

The Engineering Coder turns the approved engineering handoff into `solution_script.py`.

## What It Owns

- `solution_script.py`
- supporting `*.py` implementation files
- `todo.md`
- `journal.md`
- `plan_refusal.md` when the approved plan is genuinely infeasible
- `renders/current-episode/` scratch evidence during the active run
- the validation and simulation artifacts produced by the latest revision

## What It Reads

- `engineering_plan.md`
- `todo.md`
- `assembly_definition.yaml`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_script.py` when it exists
- `benchmark_plan_evidence_script.py` when it exists
- `plan_refusal.md` when present
- `solution_plan_evidence_script.py`
- `validation_results.json`
- `simulation_result.json`
- `scene.json`
- `renders/benchmark_renders/**`
- `renders/engineer_plan_renders/**`
- `renders/final_solution_submission_renders/**`
- `renders/current-episode/**` when it exists

## Native Tool Surface

- `list_files`
- `read_file`
- `inspect_media`
- `write_file`
- `edit_file`
- `grep`
- `execute_command`
- `inspect_topology`
- `invoke_cots_search_subagent`

## Runtime Helpers To Use From Scripts

- `from utils.submission import validate_engineering, simulate_engineering, submit_solution_for_review`
- `from utils.preview import render_cad, objectives_geometry, list_render_bundles, query_render_bundle, pick_preview_pixel, pick_preview_pixels`

## What Humans Must Tell It

- The approved plan package is the binding contract.
- `assembly_definition.yaml`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, and the planner evidence scripts are read-only context after plan approval.
- The coder preserves the exact labels, repeated quantities, COTS identities, budgets, and geometry relationships in the handoff.
- Validate and simulate the latest revision with `validate_engineering()` / `simulate_engineering()` before requesting review, then call `submit_solution_for_review()`.
- Inspect render or video evidence when it exists; do not rely on text-only summaries.
- If bug-report mode is enabled and runtime plumbing blocks progress, write `bug_report.md` at the workspace root, keep `journal.md` for task-facing notes, and continue working unless the task is genuinely blocked.
- Use `plan_refusal.md` only when the approved plan is genuinely infeasible.
- If payload trajectory data exists, keep the coarse and fine motion contracts aligned.

## Acceptance Checklist

- `solution_script.py` imports safely.
- The implementation solves the approved benchmark objective.
- Validation passes.
- Simulation passes for the latest revision.
- The final handoff is review-ready and evidence-backed.

## Related Skills

- `.agents/skills/engineer-coder/SKILL.md`
- `.agents/skills/runtime-script-contract/SKILL.md`
- `.agents/skills/build123d-cad-drafting-skill/SKILL.md`
- `.agents/skills/mechanical-engineering/SKILL.md`
- `.agents/skills/cots-parts/SKILL.md`
- `.agents/skills/manufacturing-knowledge/SKILL.md`
- `.agents/skills/render-evidence/SKILL.md`
