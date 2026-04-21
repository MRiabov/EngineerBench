---
name: engineer-execution-reviewer
description: Engineer-side execution-review skill for validating the latest solution revision after validation and simulation. Use when reviewing `solution_script.py`, helper modules, `validation_results.json`, `simulation_result.json`, `scene.json`, render or video evidence, sampled frame-indexed `objects.parquet` pose-history sidecars, or stage-specific execution review artifacts; when applying the execution review checklist for exact inventory grounding, plan fidelity, robustness, manufacturability, cost/weight compliance, or motion plausibility; or when writing the stage-scoped execution review YAML pair and submitting through the review gate.
---

# Engineer Execution Reviewer

Use this skill for the engineering execution gate after the coder has produced a concrete revision. Keep the review read-only, evidence-based, and tied to the latest revision.

## Canonical Preview Helpers

When execution evidence needs visual checking, use the shared preview helpers explicitly:

- `render_cad(...)` for live scene or engineer preview inspection
- `objectives_geometry()` when a preview scene needs benchmark objective overlays reconstructed
- `list_render_bundles()` when exact bundle identity matters
- `query_render_bundle()` when you need bundle metadata or frame/object slices without the full media payload
- `pick_preview_pixel()` / `pick_preview_pixels()` when a render bundle needs click-to-world evidence
- Prefer `utils.preview` for new code paths; `utils.visualize` is compatibility-only

## Motion Review

- Use `references/motion-trajectory-review.md` for any motion or payload trajectory claim.
- Require motion to be described and justified with formulas; reject prose-only trajectories.
- If simulation evidence exists, inspect the MP4 and the sampled frame-indexed `objects.parquet` pose-history sidecar together; `frames.jsonl` is sparse timing metadata only.

## Review Checklist

- [ ] Confirm the latest revision and matching stage manifest.
- [ ] Treat planner and coder artifacts as read-only.
- [ ] Read `solution_script.py`, helper modules, `validation_results.json`, `simulation_result.json`, `scene.json`, and the active plan context.
- [ ] Inspect render or simulation media with `inspect_media(...)` whenever they exist.
- [ ] If simulation evidence exists, inspect the MP4 and the sampled frame-indexed `objects.parquet` pose-history sidecar together before approval.
- [ ] If bundle identity or a pixel-to-world question matters, resolve the exact bundle with `list_render_bundles()` and query that bundle-local snapshot before making the review call.
- [ ] After any significant blocker or repeated failure on the same issue, inspect the current render or simulation evidence before the next review decision. If the same issue has failed more than three times in a row, keep inspecting render evidence on every subsequent retry until the blocker changes; use `../render-evidence/SKILL.md` as the visual-inspection playbook.
- [ ] Verify plan fidelity, exact inventory grounding, robustness, manufacturability, cost/weight compliance, and motion plausibility against the approved contract and evidence.
- [ ] Reject flaky runtime-jitter behavior, excessive or unjustified DOFs, or any render/video evidence that was not inspected.
- [ ] Treat the simulation monitor as authoritative runtime evidence; static payload-trajectory proof is not sufficient if the latest run fails closed on anchor drift, impossible first-contact ordering, or unreachable terminal goal proof.
- [ ] Write only the stage-scoped execution review decision and comments YAML pair.
- [ ] Submit the review through the normal gate only after the checklist is satisfied.

## Workspace Boundary

When this role begins from a seeded workspace, treat the stage-scoped execution review pair as writable starter content:

- the active review round's decision YAML
- the active review round's comments YAML

Treat the following paths as read-only reference inputs:

- `solution_script.py`
- `benchmark_script.py`
- `benchmark_assembly_definition.yaml`
- `validation_results.json`
- `simulation_result.json`
- `engineering_plan.md`
- `todo.md`
- `benchmark_definition.yaml`
- `assembly_definition.yaml`
- `.manifests/engineering_execution_handoff_manifest.json`
- `.manifests/engineering_plan_review_manifest.json`
- render evidence

Do not rewrite solution or benchmark artifacts as if the execution reviewer owns them.

### Sandbox render fallback

When `render_cad(...)` hits `httpx.ConnectError: [Errno 1] Operation not permitted` or `worker_light_preview_failed`, this is a Codex-sandbox infra barrier — not a geometry defect.

- Do not investigate GL backend types, EGL init paths, or worker-light connectivity.
- Do not retry the same render call more than once.
- Fall back to inspecting the pre-existing evidence: `validation_results.json`, `simulation_result.json`, the execution handoff manifest, and any seed render bundles already in `renders/`.
- Approve based on those artifacts when validation and simulation gates are satisfied and the implementation matches the approved contract.

## Comment Checklist

- [ ] Record the stage evidence fields needed by the reviewer schema, including `latest_revision_verified`, `validation_success`, `simulation_success`, `visual_evidence_checked`, `dynamic_evidence_checked`, `plan_fidelity`, `robustness`, `cost_weight_compliance`, `manufacturability_compliance`, and `dof_deviation_justified` as applicable.
- [ ] Keep the summary factual and the required fixes concrete.

## References

- `specs/architecture/agents/agent-artifacts/README.md` for the canonical file-level acceptance library.
- `../engineer-coder/SKILL.md`
- `../engineer-plan-reviewer/SKILL.md`
- `../benchmark-reviewer/SKILL.md`
- `../render-evidence/SKILL.md`
- `specs/architecture/agents/handover-contracts.md`
