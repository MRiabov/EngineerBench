# Engineering Execution Reviewer

## Role Summary

The Engineering Execution Reviewer decides whether the implemented solution is ready to hand off after validation and simulation.

## What It Owns

- `reviews/engineering-execution-review-decision-round-<n>.yaml`
- `reviews/engineering-execution-review-comments-round-<n>.yaml`

## What It Reads

- `solution_script.py`
- supporting `*.py` implementation files
- `engineering_plan.md`
- `todo.md`
- `assembly_definition.yaml`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_script.py` when it exists
- `benchmark_plan_evidence_script.py` when it exists
- `plan_refusal.md` when present
- `solution_plan_evidence_script.py` when it exists
- `validation_results.json`
- `simulation_result.json`
- `scene.json`
- `renders/current-episode/**` when it exists
- `renders/benchmark_renders/**`
- `renders/final_solution_submission_renders/**`
- `.manifests/engineering_execution_handoff_manifest.json`

## Native Tool Surface

- `list_files`
- `read_file`
- `inspect_media`
- `write_file`
- `grep`
- `execute_command`
- `inspect_topology`

## What Humans Must Tell It

- Review the latest revision only.
- Require validation and simulation success before approval.
- Inspect render images and simulation video when they exist.
- Inspect the sampled `objects.parquet` sidecar when motion evidence exists.
- Verify plan fidelity, robustness, manufacturability, cost/weight compliance, and motion plausibility.
- If bug-report mode is enabled and runtime plumbing blocks the review, write `bug_report.md` at the workspace root and continue unless the reviewer is actually blocked.
- Keep the review read-only and stage-scoped.
- Write only the stage-owned decision/comments YAML pair, then finish with `bash scripts/submit_review.sh`.

## Acceptance Checklist

- The solution still matches the approved plan.
- The solution is robust under runtime jitter.
- The budget and manufacturability claims still hold.
- The latest review artifacts are the only files written.

## Related Skills

- `.agents/skills/engineer-execution-reviewer/SKILL.md`
- `.agents/skills/render-evidence/SKILL.md`
- `.agents/skills/mechanical-engineering/SKILL.md`
- `.agents/skills/runtime-script-contract/SKILL.md`
