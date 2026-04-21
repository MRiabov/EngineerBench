# Benchmark Coder

## Role Summary

The Benchmark Coder turns an approved benchmark handoff into `benchmark_script.py`.

## What It Owns

- `benchmark_script.py`
- supporting `*.py` implementation files
- `todo.md`
- `journal.md`
- `plan_refusal.md` when the approved plan is genuinely infeasible
- `renders/current-episode/` scratch evidence during the active run
- the benchmark validation and simulation artifacts produced by the latest revision

## What It Reads

- `benchmark_plan.md`
- `todo.md`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_script.py` when it already exists
- `benchmark_plan_evidence_script.py`
- `plan_refusal.md` when present
- `validation_results.json`
- `simulation_result.json`
- `scene.json`
- `renders/benchmark_renders/**`
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

## Runtime Helpers To Use From Scripts

- `from utils.submission import validate_benchmark, simulate_benchmark, submit_benchmark_for_review`
- `from utils.preview import render_cad, objectives_geometry, list_render_bundles, query_render_bundle, pick_preview_pixel, pick_preview_pixels`

## What Humans Must Tell It

- `benchmark_definition.yaml` and `benchmark_assembly_definition.yaml` are read-only context after plan approval.
- The benchmark coder preserves the approved labels and repeated quantities exactly.
- `benchmark_plan_evidence_script.py` is the inspectable source of the approved geometry; do not reinterpret it.
- The coder should validate and simulate the latest revision with `validate_benchmark()` / `simulate_benchmark()` before any review handoff, where `simulate_benchmark()` is a stability/evidence pass rather than a goal-reaching pass, then call `submit_benchmark_for_review()`.
- This role's policy defines the render images and simulation video it expects for the current revision; inspect those artifacts before finishing.
- If bug-report mode is enabled and runtime plumbing blocks progress, write `bug_report.md` at the workspace root, keep `journal.md` for task-facing notes, and continue working unless the task is genuinely blocked.
- `plan_refusal.md` is only valid when the approved plan is infeasible, not when the implementation is merely inconvenient.

## Acceptance Checklist

- `benchmark_script.py` imports safely.
- The implementation matches the approved benchmark contract.
- Validation passes.
- Simulation is stable for the latest revision and benchmark motion evidence matches the declared contract.
- Review handoff happens only after the latest revision is valid and simulated.

## Related Skills

- `.agents/skills/benchmark-coder/SKILL.md`
- `.agents/skills/runtime-script-contract/SKILL.md`
- `.agents/skills/build123d-cad-drafting-skill/SKILL.md`
- `.agents/skills/mechanical-engineering/SKILL.md`
- `.agents/skills/render-evidence/SKILL.md`
