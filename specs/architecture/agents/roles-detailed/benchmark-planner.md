# Benchmark Planner

## Role Summary

The Benchmark Planner turns a problem brief into a benchmark handoff package. It designs the task, not the solution.

## What It Owns

- `benchmark_plan.md`
- `todo.md`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_plan_evidence_script.py`
- `journal.md`
- `renders/benchmark_renders/` persistent render evidence
- `renders/current-episode/` scratch evidence during the active run
- `.manifests/benchmark_plan_review_manifest.json` via `submit_benchmark_plan()`

## What It Reads

- `.agents/skills/benchmark-planner/SKILL.md`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `manufacturing_config.yaml`
- `renders/benchmark_renders/**` when they exist
- `renders/current-episode/**` when it exists
- `specs/architecture/primary-system-objectives.md`
- `specs/architecture/rendering.md`
- `specs/architecture/simulation.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`

## Native Tool Surface

- `list_files`
- `read_file`
- `inspect_media`
- `write_file`
- `edit_file`
- `grep`
- `execute_command`
- `inspect_topology`
- `submit_benchmark_plan`

## Runtime Helpers To Use From Scripts

- `render_cad(...)` for a live benchmark scene with objective overlays
- `objectives_geometry()` for reconstructed objective bodies

## What Humans Must Tell It

- The benchmark objective geometry, build zone, forbid zones, and runtime jitter are authoritative.
- Benchmark-owned fixtures, input objects, and objective markers are read-only context, not engineer-owned deliverables.
- The benchmark handoff must stay exact across `benchmark_plan.md`, the YAML files, and both planner scripts.
- `payload.material_id` must resolve to a known material from `manufacturing_config.yaml`.
- Moving benchmark-owned fixtures need explicit, reviewer-visible motion facts.
- If bug-report mode is enabled and runtime plumbing blocks progress, write `bug_report.md` at the workspace root and keep working unless the task is genuinely blocked.
- If render images already exist for the current revision, inspect them with `inspect_media()` before submission.
- Do not expect `benchmark_script.py` in the workspace until after plan approval.
- `submit_benchmark_plan()` is the only completion gate; do not hand off before the package is internally consistent.

## Acceptance Checklist

- The benchmark is a valid problem instance for the engineering graph.
- The geometry is valid and the objective bodies do not overlap the forbidden or spawn regions.
- The planner scripts preserve the same labels and repeated quantities as the plan.
- The planner wrote realistic estimated cost and weight values before submission.

## Related Skills

- `.agents/skills/benchmark-planner/SKILL.md`
- `.agents/skills/build123d-cad-drafting-skill/SKILL.md`
- `.agents/skills/runtime-script-contract/SKILL.md`
- `.agents/skills/mechanical-engineering/SKILL.md`
- `.agents/skills/manufacturing-knowledge/SKILL.md`
- `.agents/skills/render-evidence/SKILL.md`
