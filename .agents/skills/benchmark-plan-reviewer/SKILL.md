---
name: benchmark-plan-reviewer
description: Review benchmark planner handoffs before coding starts, with explicit attention to whether `payload_trajectory_definition.yaml` is physically satisfiable from the full plan. Use when validating `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, `payload_trajectory_definition.yaml` when present, `benchmark_plan_evidence_script.py`, render evidence, or the benchmark plan-review manifest; when applying the benchmark-plan review checklist for cross-artifact consistency, path feasibility, motion visibility, geometry feasibility, timing, and speed plausibility; when inspecting simulation evidence through frame-indexed `objects.parquet` sidecars; or when writing the stage-scoped benchmark-plan review YAML pair under `reviews/`.
---

# Benchmark Plan Reviewer

## Canonical Preview Helpers

When planner drafts or evidence need visual checking, use the shared preview helpers explicitly:

- `render_cad(...)` for live scene or preview-bundle inspection
- `objectives_geometry()` when a preview scene needs benchmark objective overlays reconstructed
- `list_render_bundles()` when exact bundle identity matters
- `query_render_bundle()` when you need bundle metadata without the full media payload or frame/object slices from a simulation bundle
- `pick_preview_pixel()` / `pick_preview_pixels()` when a render bundle needs click-to-world evidence
- Prefer `utils.preview` for new code paths; `utils.visualize` is compatibility-only

## Precise Path Review

Treat `payload_trajectory_definition.yaml` as binding path-contract evidence when it is present.

- Check whether the full plan can satisfy the precise path, not just whether the parts fit.
- Compare `assembly_definition.yaml.motion_forecast` to `payload_trajectory_definition.yaml`; the precise path must refine the same moving-part set.
- Verify anchor positions, `sample_stride_s`, first-contact windows, terminal events, and stated tolerances against the declared geometry and DOFs.
- Estimate whether the implied motion speed and transition timing are physically plausible for the declared mechanism.
- Treat a missing or hand-wavy payload trajectory estimate as a strong reject. If the planner has not grounded the payload motion, downstream machinery timing and sizing are usually not grounded either.
- Treat non-rigorous path math in `benchmark_plan.md` as a strong reject. If the detailed calculation section does not derive the trajectory scientifically, the trajectory estimate itself is not credible.
- Reject hidden DOFs, unsupported acceleration, impossible timing windows, or a path that only works by changing the plan.
- Require `benchmark_plan.md`'s detailed calculation section to show the full derivation behind every path-related claim, not just the final result.
- Reject any precise-path justification that leaves distances, timing, velocity, clearance, or tolerance math implicit.

## Review Checklist

- [ ] Confirm the latest planner revision and matching `.manifests/benchmark_plan_review_manifest.json`.
- [ ] Read `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, and `benchmark_plan_evidence_script.py` as read-only context.
- [ ] If present, read `payload_trajectory_definition.yaml` and verify the plan can physically satisfy its anchors, windows, and timing.
- [ ] Compare `assembly_definition.yaml.motion_forecast` to `payload_trajectory_definition.yaml`; reject a precise path that invents a different moving-part set or impossible speed profile.
- [ ] Strong reject plans that cannot state the payload trajectory clearly or that fail to derive it rigorously in `benchmark_plan.md`; a missing trajectory estimate usually means downstream machinery is not grounded either.
- [ ] Confirm `benchmark_plan.md`'s detailed calculation section fully explains the numbers used to justify the precise path, including intermediate derivations for distances, timing, speeds, and clearances.
- [ ] If render evidence exists, inspect it with `inspect_media(...)`.
- [ ] If scratch evidence exists in `renders/current-episode/**`, inspect that current-episode bundle as well before deciding.
- [ ] If a simulation bundle already exists, inspect the MP4 and the sampled frame-indexed `objects.parquet` pose-history sidecar together; `frames.jsonl` is sparse timing metadata, not pose history.
- [ ] If bundle identity or a pixel-to-world question matters, resolve the exact bundle with `list_render_bundles()` and query that bundle-local snapshot before deciding.
- [ ] After any significant blocker or repeated failure on the same issue, inspect the current render evidence before the next review decision. If the same issue has failed more than three times in a row, keep inspecting render evidence on every subsequent retry until the blocker changes; use `../render-evidence/SKILL.md` as the visual-inspection playbook.
- [ ] Treat `benchmark_plan_evidence_script.py` as the inspectable source of the approved benchmark solution, not just a helper file.
- [ ] Verify cross-artifact consistency for labels, repeated quantities, COTS identities, zone geometry, randomization, bounds, runtime jitter, and motion facts. See `references/review_contracts.md`.
- [ ] Verify `payload.material_id` resolves to a known material and `benchmark_assembly_definition.yaml` is a schema-valid full `AssemblyDefinition`.
- [ ] Reject planner drafts that depend on free-form XYZ placement as the primary positioning mechanism; require selector-driven placement, explicit mates/joints, or clearly bounded absolute anchors.
- [ ] Verify benchmark-side motion is explicit, reconstructable, and feasible; reject hidden motion or unsupported motion.
- [ ] Reject invented defaults, placeholder geometry, unlabeled inventory drift, or mismatched object references across planner artifacts.
- [ ] Write only `reviews/benchmark-plan-review-decision-round-<n>.yaml` and `reviews/benchmark-plan-review-comments-round-<n>.yaml`.
- [ ] Use the decision YAML as the routing source of truth, then run `bash scripts/submit_review.sh`.

## Workspace Boundary

When this role begins from a seeded workspace, treat the stage-scoped review YAML pair as writable review outputs:

- `reviews/benchmark-plan-review-decision-round-<n>.yaml`
- `reviews/benchmark-plan-review-comments-round-<n>.yaml`

Treat the following paths as read-only reference inputs:

- `benchmark_plan.md`
- `todo.md`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `payload_trajectory_definition.yaml` when present
- `benchmark_plan_evidence_script.py`
- render evidence
- `.manifests/benchmark_plan_review_manifest.json`

Do not convert planner handoff artifacts into reviewer-owned workspace files.

## Comment Checklist

- [ ] Populate the stage keys from the handover contract: `cross_artifact_consistency`, `feasible_mechanism`, `budget_realism`, and `dof_minimality`.
- [ ] Use `pass`, `fail`, or `not_applicable` values only.
- [ ] Keep the summary factual and the required fixes concrete.

## References

- `references/review_contracts.md` for the detailed cross-artifact, motion, and media rules.
- `specs/architecture/agents/agent-artifacts/README.md` for the canonical file-level acceptance library.
- `specs/architecture/agents/handover-contracts.md` for the canonical checklist keys and output contract.
