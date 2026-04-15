# Benchmark Reviewer

## Role Summary

The Benchmark Reviewer decides whether the implemented benchmark is ready to hand off to the engineering graph.

## What It Owns

- `reviews/benchmark-execution-review-decision-round-<n>.yaml`
- `reviews/benchmark-execution-review-comments-round-<n>.yaml`

## What It Reads

- `benchmark_script.py`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_plan.md`
- `todo.md`
- `plan_refusal.md` when present
- `validation_results.json`
- `simulation_result.json`
- `scene.json`
- `benchmark_plan_evidence_script.py`
- `renders/benchmark_renders/**`
- `renders/current-episode/**` when it exists
- `.manifests/benchmark_review_manifest.json`

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
- Inspect render images when they exist, and inspect simulation video when moving benchmark fixtures exist.
- If render images exist, inspect them with `inspect_media()` before approval.
- Treat `frames.jsonl` as timing metadata, not pose history; use the sampled `objects.parquet` sidecar for motion review.
- Verify exact inventory grounding, geometry validity, benchmark stability, randomization, and motion plausibility against the approved contract.
- If moving benchmark fixtures exist, inspect the latest simulation video and the sampled `objects.parquet` sidecar before approval.
- Interpret benchmark payload drift with the config-driven observation window in `config/agents_config.yaml` (`benchmark_payload_observation.window_s`); payload out-of-bounds before that window is a failure, while later drift is evidence rather than a benchmark-simulation failure.
- Do not require benchmark-side goal completion; benchmark review is about approving a valid, stable problem instance for the engineering graph.
- If bug-report mode is enabled and runtime plumbing blocks the review, write `bug_report.md` at the workspace root and continue unless the reviewer is actually blocked.
- Keep the review read-only.
- Write only the stage-owned decision/comments YAML pair, then finish with `bash scripts/submit_review.sh`.

## Acceptance Checklist

- The benchmark still matches the approved handoff.
- The benchmark is geometrically valid.
- The benchmark is a valid, stable problem instance for the engineering graph.
- Benchmark-side motion, if present, matches the declared contract and observed simulation evidence.
- The stage-scoped review YAML pair is the only output.

## Related Skills

- `.agents/skills/benchmark-reviewer/SKILL.md`
- `.agents/skills/render-evidence/SKILL.md`
- `.agents/skills/mechanical-engineering/SKILL.md`
- `.agents/skills/runtime-script-contract/SKILL.md`
