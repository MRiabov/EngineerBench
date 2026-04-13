# Benchmark Plan Reviewer

## Role Summary

The Benchmark Plan Reviewer checks the planner handoff before implementation starts. It is a read-only gate.

## What It Owns

- `reviews/benchmark-plan-review-decision-round-<n>.yaml`
- `reviews/benchmark-plan-review-comments-round-<n>.yaml`

## What It Reads

- `benchmark_plan.md`
- `todo.md`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_plan_evidence_script.py`
- `renders/benchmark_renders/**` when available
- `renders/current-episode/**` when it exists
- `.manifests/benchmark_plan_review_manifest.json`

## Native Tool Surface

- `list_files`
- `read_file`
- `inspect_media`
- `write_file`
- `grep`
- `execute_command`
- `inspect_topology`
- `invoke_cots_search_subagent`

## What Humans Must Tell It

- Review the latest planner revision only.
- Check exact inventory grounding across the markdown, YAML, and planner scripts.
- Reject unsupported geometry claims, hidden motion, and free-form XYZ placement as the primary layout mechanism.
- If render images exist, inspect at least one before approval.
- If the benchmark has moving fixtures, require motion-visible handoff facts, not just prose.
- If bug-report mode is enabled and runtime plumbing blocks the review, write `bug_report.md` at the workspace root and continue unless the reviewer is actually blocked.
- Keep the review output limited to the stage-owned YAML pair.
- Write the stage-owned YAML pair and finish with `bash scripts/submit_review.sh`.

## Acceptance Checklist

- The planner handoff is internally consistent.
- The benchmark geometry is feasible before coding starts.
- The inventory labels, repeated quantities, and COTS identities match exactly.
- The motion contract is explicit enough for the benchmark coder to reconstruct.
- The review decision is written only after media inspection when media exists.

## Related Skills

- `.agents/skills/benchmark-plan-reviewer/SKILL.md`
- `.agents/skills/render-evidence/SKILL.md`
- `.agents/skills/build123d-cad-drafting-skill/SKILL.md`
- `.agents/skills/runtime-script-contract/SKILL.md`
- `.agents/skills/mechanical-engineering/SKILL.md`
- `.agents/skills/cots-parts/SKILL.md` when benchmark-owned fixtures are catalog-backed
