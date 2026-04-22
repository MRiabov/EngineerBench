---
name: benchmark-reviewer
description: Benchmark execution-review skill for validating implemented benchmarks after validation and simulation. Use when reviewing `benchmark_script.py`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `validation_results.json`, `simulation_result.json`, `scene.json`, render or video evidence, frame-indexed `objects.parquet` sidecars, or stage-specific review artifacts; when applying the benchmark execution review checklist for exact inventory grounding, geometry validity, solvability, randomization, and benchmark-side motion; or when writing the `reviews/benchmark-execution-review-*.yaml` pair and submitting via `bash scripts/submit_review.sh`.
---

# Benchmark Reviewer

Use this skill to decide whether the implemented benchmark is ready to hand off to the engineer graph. Keep the review read-only, evidence-based, and tied to the latest revision.

## Canonical Preview Helpers

When render evidence or objective overlays are present, use the shared preview helpers explicitly:

- `render_cad(...)` for live scene previews or benchmark evidence inspection
- `objectives_geometry()` when a benchmark preview needs reconstructed objective overlays
- `list_render_bundles()` when exact bundle identity matters
- `query_render_bundle()` when you need bundle metadata without the full media payload or frame/object slices from a simulation bundle
- `pick_preview_pixel()` / `pick_preview_pixels()` when a render bundle needs click-to-world evidence
- Prefer `utils.preview` for new code paths; `utils.visualize` is a compatibility alias

## Review Checklist

- [ ] Confirm the latest revision and valid `.manifests/benchmark_review_manifest.json`.
- [ ] Read `benchmark_script.py`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `benchmark_plan.md`, `todo.md`, `validation_results.json`, `simulation_result.json`, `scene.json`, `benchmark_plan_evidence_script.py`, and any `renders/benchmark_renders/**` as read-only context.
- [ ] Read `plan_refusal.md` when present.
- [ ] Read `renders/current-episode/**` when it exists.
- [ ] Require validation and simulation success for the latest revision; benchmark approval does not depend on `goal_reached`.
- [ ] Inspect render images with `inspect_media(...)` whenever they exist; if moving benchmark fixtures exist, inspect the latest dynamic simulation evidence before approval.
- [ ] If simulation evidence exists, inspect the MP4 and the sampled frame-indexed `objects.parquet` pose-history sidecar together; `frames.jsonl` is sparse timing metadata, not pose history.
- [ ] If bundle identity or a pixel-to-world question matters, resolve the exact bundle with `list_render_bundles()` and query that bundle-local snapshot before approval.
- [ ] After any significant blocker or repeated failure on the same issue, inspect the current render or simulation evidence before the next approval decision. If the same issue has failed more than three times in a row, keep inspecting render evidence on every subsequent retry until the blocker changes; use `../render-evidence/SKILL.md` as the visual-inspection playbook.
- [ ] Treat `benchmark_plan_evidence_script.py` as the inspectable source of the approved benchmark contract.
- [ ] Verify geometric validity, solvability, runtime randomization, exact inventory grounding, and benchmark-side motion against the approved contract and observed evidence. See `references/review_contracts.md`.
- [ ] Reject implementations that rely on free-form XYZ placement instead of selector-driven placement, explicit mates/joints, or the few absolute anchors already fixed by the approved plan.
- [ ] Reject stale or missing validation/simulation evidence, invisible benchmark-side motion, or any benchmark-owned fixture that is silently reinterpreted as engineer-owned work.
- [ ] Keep benchmark-owned source files untouched.
- [ ] Write only `reviews/benchmark-execution-review-decision-round-<n>.yaml` and `reviews/benchmark-execution-review-comments-round-<n>.yaml`.
- [ ] Submit the review with `bash scripts/submit_review.sh` after the files are written.

## Workspace Boundary

When this role begins from a seeded workspace, treat the stage-scoped review YAML pair as writable review outputs:

- `reviews/benchmark-execution-review-decision-round-<n>.yaml`
- `reviews/benchmark-execution-review-comments-round-<n>.yaml`

Treat the following paths as read-only reference inputs:

- `benchmark_script.py`
- `validation_results.json`
- `simulation_result.json`
- `.manifests/benchmark_review_manifest.json`
- `benchmark_plan.md`
- `todo.md`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_plan_evidence_script.py`
- any render evidence

Do not rewrite benchmark context as if the benchmark reviewer owns it.

## Comment Checklist

- [ ] Record the stage evidence fields needed by the reviewer schema, including `latest_revision_verified`, `review_manifest_revision`, `validation_success`, `simulation_success`, `solvability_summary`, `attachment_policy_summary`, `render_count`, `inspected_render_count`, `visual_inspection_min_images`, `visual_inspection_satisfied`, `visual_evidence_checked`, `deterministic_error_count`, and `deterministic_refusal_reason` as applicable. Include `goal_reached` only if the schema or manifest already provides it as an engineer-owned field.
- [ ] Add `dynamic_evidence_checked` or equivalent motion-evidence notes when benchmark-owned motion exists.
- [ ] Keep the summary factual and the required fixes concrete.

## References

- `references/review_contracts.md` for the detailed benchmark execution review rules and checklist fields.
- `specs/architecture/agents/agent-artifacts/README.md` for the canonical file-level acceptance library.
- `specs/architecture/agents/handover-contracts.md` for the canonical manifest, evidence, and output contract.
