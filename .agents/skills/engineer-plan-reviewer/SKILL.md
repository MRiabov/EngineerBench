---
name: engineer-plan-reviewer
description: Engineer-side review workflow for validating plan and execution handoffs, review manifests, render and simulation evidence, exact inventory grounding, formula-backed motion and payload trajectory derivations, motion-contract plausibility, plan refusals, and stage-scoped review YAML outputs. Use when reviewing engineering `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, `solution_script.py`, validation or simulation artifacts, review manifests, or refusal evidence for the Engineering Plan Reviewer or Engineering Execution Reviewer roles; when inspecting simulation evidence through frame-indexed `objects.parquet` sidecars; or when applying the engineer review checklist for plan, execution, and refusal gates.
---

# Engineer Plan Reviewer

Use this skill for both the engineering plan-review and execution-review gates. Keep the stage-specific checklists separate and treat planner and coder artifacts as read-only.

## Canonical Preview Helpers

When plan or execution evidence needs visual checking, use the shared preview helpers explicitly:

- `render_cad(...)` for live scene or engineer preview inspection
- `objectives_geometry()` when a preview scene needs benchmark objective overlays reconstructed
- `list_render_bundles()` when exact bundle identity matters
- `query_render_bundle()` when you need bundle metadata without the full media payload or frame/object slices from a simulation bundle
- `pick_preview_pixel()` / `pick_preview_pixels()` when a render bundle needs click-to-world evidence
- Prefer `utils.preview` for new code paths; `utils.visualize` is compatibility-only

## Motion Review

- Use `references/motion-trajectory-review.md` for any motion or payload trajectory claim.
- Require motion to be described and justified with formulas; reject prose-only trajectories.
- Review the trajectory against the approved anchors, contact order, tolerance bands, and terminal proof rather than inferring it from mechanism prose.

## Review Checklist

- [ ] Confirm the latest revision and matching stage manifest.
- [ ] Treat planner and coder artifacts as read-only.
- [ ] Inspect render or simulation media with `inspect_media(...)` whenever they exist.
- [ ] If final solution submission evidence exists, inspect `renders/final_solution_submission_renders/**` alongside the engineer-plan and benchmark evidence before approval.
- [ ] If simulation evidence exists, inspect the MP4 and the sampled frame-indexed `objects.parquet` pose-history sidecar together; `frames.jsonl` is sparse timing metadata, not pose history.
- [ ] If bundle identity or a pixel-to-world question matters, resolve the exact bundle with `list_render_bundles()` and query that bundle-local snapshot before making the review call.
- [ ] After any significant blocker or repeated failure on the same issue, inspect the current render or simulation evidence before the next review decision. If the same issue has failed more than three times in a row, keep inspecting render evidence on every subsequent retry until the blocker changes; use `../render-evidence/SKILL.md` as the visual-inspection playbook.
- [ ] Write only the stage-scoped review decision and comments YAML pair.
- [ ] Route invalid refusals back to coding unless the refusal proves infeasibility.
- [ ] For any motion or payload trajectory claim, verify the claim is described and formula-justified; see `references/motion-trajectory-review.md`.

### Plan Review Checklist

- [ ] Read `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, and `solution_plan_evidence_script.py`.
- [ ] Treat `solution_plan_evidence_script.py` as the inspectable source of the approved plan, and inspect render evidence with `inspect_media(...)` when present.
- [ ] When render evidence is bundle-scoped, use `list_render_bundles()` or `query_render_bundle()` to select the exact bundle before judging it.
- [ ] Verify exact inventory grounding, exact identifier mentions, budget realism, and operating-envelope clarity.
- [ ] Reject invented materials, unsupported mechanisms, or hidden DOFs.
- [ ] Reject plans that exceed benchmark caps or leave the solution mechanically ambiguous.
- [ ] For moving engineer-owned parts, do not treat static payload-trajectory proof as runtime evidence; the plan must stay compatible with the fail-closed simulation monitor and its anchor, contact-order, and terminal-goal expectations.

### Execution Review Checklist

- [ ] Read `solution_script.py`, helper modules, `validation_results.json`, `simulation_result.json`, and the active plan context.
- [ ] Require validation and simulation success for the latest revision.
- [ ] Verify plan fidelity, robustness, manufacturability, and cost/weight compliance against the approved plan.
- [ ] Reject flaky runtime-jitter behavior, excessive or unjustified DOFs, or any render/video evidence that was not inspected.

### Refusal Review Checklist

- [ ] Read `plan_refusal.md` and the rejected plan evidence.
- [ ] Confirm only when the refusal contains role-specific reasons and concrete evidence that the plan is infeasible.
- [ ] Reject generic coding failure or a refusal that can still be implemented.

## Comment Checklist

- [ ] Plan reviewers: `cross_artifact_consistency`, `feasible_mechanism`, `budget_realism`, `dof_minimality`.
- [ ] Execution reviewers: `latest_revision_verified`, `validation_success`, `simulation_success`, `visual_evidence_checked`, `dynamic_evidence_checked`, `plan_fidelity`, `robustness`, `cost_weight_compliance`, `manufacturability_compliance`, `dof_deviation_justified`.
- [ ] Use `pass`, `fail`, or `not_applicable` values only where the stage contract requires them.
- [ ] Keep the summary factual and the required fixes concrete.

## References

- `specs/architecture/agents/agent-artifacts/README.md` for the canonical file-level acceptance library.
- `references/review_contracts.md`
- `references/motion-trajectory-review.md`
- `specs/architecture/agents/roles.md`
- `specs/architecture/agents/handover-contracts.md`
