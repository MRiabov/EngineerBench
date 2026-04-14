# Benchmark Review Contracts

## Core checklist

- Review only the latest revision in the active workspace.
- Treat benchmark-owned artifacts as read-only.
- Fail closed on missing, stale, invalid, or cross-revision artifacts.
- Use `inspect_media(...)` for render, image, or video evidence. Do not rely on filenames or text summaries alone.
- Use `specs/architecture/agents/agent-artifacts/README.md` for the file-level acceptance criteria that sit underneath this review contract.
- Require validation and simulation success for the latest revision.
- If moving benchmark fixtures exist, require dynamic simulation evidence for the latest revision.
- Do not require benchmark-side goal completion; `goal_reached` is engineer-owned and should only be referenced if the reviewer schema or manifest already exposes it as a separate field.
- Keep the decision YAML as the routing source of truth. Keep the comments YAML factual and evidence-based.
- Treat `benchmark_plan_evidence_script.py` as the inspectable source of the approved benchmark contract.

## Required reviewer package

- `.manifests/benchmark_review_manifest.json`
- `benchmark_script.py`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_plan.md`
- `todo.md`
- `validation_results.json`
- `simulation_result.json`
- `scene.json`
- `benchmark_plan_evidence_script.py`
- `renders/benchmark_renders/**` when planner or coder preview assets already exist

## Review checklist

- Verify that the benchmark is a valid, stable problem instance or is correctly rejected for a concrete, evidence-backed reason.
- Verify geometric validity, solvability, runtime randomization, and exact inventory grounding.
- Verify validation and simulation success for the latest revision.
- Reject invalid geometry, out-of-bounds placement, unsolved tasks, or randomization failures.
- Reject benchmark-side motion that is hidden, contradictory, unstable, or not reflected in evidence.
- Reject benchmark-owned fixtures that are silently reinterpreted as engineer-owned deliverables.
- Reject validation or simulation evidence that is missing, stale, or inconsistent with the latest revision.

## Comments checklist fields

- `latest_revision_verified`
- `review_manifest_revision`
- `validation_success`
- `simulation_success`
- `solvability_summary`
- `attachment_policy_summary`
- `render_count`
- `inspected_render_count`
- `visual_inspection_min_images`
- `visual_inspection_satisfied`
- `visual_evidence_checked`
- `deterministic_error_count`
- `deterministic_refusal_reason`
- `dynamic_evidence_checked` when moving benchmark fixtures exist

## Output and submission

- Write only the stage-scoped benchmark-execution review decision YAML and comments YAML under `reviews/`.
- Keep comments factual, specific, and tied to evidence.
- Submit the review with `bash scripts/submit_review.sh` after the files are written.
