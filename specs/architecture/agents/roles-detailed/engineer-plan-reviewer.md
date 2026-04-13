# Engineering Plan Reviewer

## Role Summary

The Engineering Plan Reviewer checks the plan before engineering implementation starts. It is a read-only gate.

## What It Owns

- `reviews/engineering-plan-review-decision-round-<n>.yaml`
- `reviews/engineering-plan-review-comments-round-<n>.yaml`

## What It Reads

- `engineering_plan.md`
- `todo.md`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_script.py` when it exists
- `benchmark_plan_evidence_script.py` when it exists
- `assembly_definition.yaml`
- `solution_script.py` when it exists
- `solution_plan_evidence_script.py`
- `payload_trajectory_definition.yaml` when present
- `plan_refusal.md` when present
- `renders/benchmark_renders/**`
- `renders/engineer_plan_renders/**`
- `renders/current-episode/**` when it exists
- `validation_results.json`
- `simulation_result.json`
- `.manifests/engineering_plan_review_manifest.json`

## Native Tool Surface

- `list_files`
- `read_file`
- `inspect_media`
- `write_file`
- `grep`
- `execute_command`
- `inspect_topology`
- `verify`
- `invoke_cots_search_subagent`

## What Humans Must Tell It

- Review the latest planner revision only.
- Keep the review focused on contract completeness and plan quality before coding starts.
- Reject unsupported mechanisms, inconsistent budgets, and exact inventory drift.
- Treat motion claims as formula-backed facts, not prose.
- Use `verify` only when the workspace already contains a concrete candidate that needs runtime-randomization evidence.
- If render images exist, inspect them before approval.
- If a refusal artifact exists, confirm whether it is a valid plan refusal or a coder failure artifact.
- If bug-report mode is enabled and runtime plumbing blocks the review, write `bug_report.md` at the workspace root and continue unless the reviewer is actually blocked.
- Write only the stage-owned decision/comments YAML pair, then finish with `bash scripts/submit_review.sh`.

## Acceptance Checklist

- The plan is internally consistent.
- The plan can be implemented without re-planning.
- The motion forecast, if any, is explicit enough to be reconstructed.
- The budget and manufacturability claims are realistic.
- The stage-scoped review YAML pair is the only output.

## Related Skills

- `.agents/skills/engineer-plan-reviewer/SKILL.md`
- `.agents/skills/render-evidence/SKILL.md`
- `.agents/skills/mechanical-engineering/SKILL.md`
- `.agents/skills/cots-parts/SKILL.md`
- `.agents/skills/runtime-script-contract/SKILL.md`
