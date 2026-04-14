# Benchmark Plan Review Contracts

## Core checklist

- Review only the latest revision in the active workspace.
- Treat planner-owned artifacts as read-only.
- Fail closed on missing, stale, invalid, or cross-revision artifacts.
- Use `inspect_media(...)` for render, image, or video evidence. Do not rely on filenames or text summaries alone.
- Use `specs/architecture/agents/agent-artifacts/README.md` for the file-level acceptance criteria that sit underneath this review contract.
- Keep the decision YAML as the routing source of truth. Keep the comments YAML explanatory and evidence-based.
- Treat `benchmark_plan_evidence_script.py` as the inspectable source of the approved benchmark contract.

## Required planner handoff

- `.manifests/benchmark_plan_review_manifest.json`
- `benchmark_plan.md`
- `todo.md`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `payload_trajectory_definition.yaml` when the planner bundle provides a refined path contract
- `benchmark_plan_evidence_script.py`
- `renders/**` when planner-side previews already exist

## Cross-artifact checklist

- Match all object names, labels, repeated quantities, and COTS identities across `benchmark_plan.md`, the YAML files, and the planner evidence script.
- Ensure every planner-declared inventory label and selected COTS `part_id` appears in `benchmark_plan.md` as an exact identifier mention.
- Reject nonexistent objects, relabeled inventory, silent renames, or missing repeated entries.
- Require `benchmark_assembly_definition.yaml` to be a schema-valid full `AssemblyDefinition`.
- Require `payload.material_id` to be present and to reference a known material from `manufacturing_config.yaml`.
- Require zone geometry, randomization, runtime jitter, and build-zone bounds to stay mutually consistent.
- Reject planner evidence scripts that drift from the approved inventory.

## Motion checklist

- Reject hidden, unsupported, or contradictory benchmark-side motion.
- Require any moving benchmark fixture to have a fully explicit motion contract that the reviewer can reconstruct from the handoff and evidence.
- Require enough motion-visible facts for downstream engineering intake, including the declared motion type, axis or path reference when applicable, and operating limits or envelope.
- Reject motion that is impossible, unstable, or not grounded in the declared benchmark artifacts.

## Precise path checklist

- If `payload_trajectory_definition.yaml` exists, read it as binding path-contract context.
- Compare `assembly_definition.yaml.motion_forecast` to `payload_trajectory_definition.yaml`; the precise path must refine the same moving-part set, not invent a different trajectory.
- Verify anchor coordinates, `sample_stride_s`, first-contact windows, terminal events, and tolerances against the declared geometry, DOFs, and control.
- Estimate whether the implied speeds and transition timings are physically plausible for the mechanism described in the plan.
- Treat a missing or hand-wavy payload trajectory estimate as a strong reject. If the planner has not grounded the payload motion, downstream machinery timing and sizing are usually not grounded either.
- Treat non-rigorous path math in `benchmark_plan.md` as a strong reject. If the detailed calculation section does not derive the trajectory scientifically, the trajectory estimate itself is not credible.
- Reject hidden DOFs, unsupported acceleration, impossible contact timing, or any path that cannot be satisfied without changing the plan.
- Require `benchmark_plan.md`'s detailed calculation section to expose the full derivation behind every path claim, including intermediate math for distances, timing, velocity, clearance, and tolerance checks.
- Reject path claims that are numerically stated but not actually derived in `benchmark_plan.md`.

## Comments checklist

- Use the stage-specific checklist keys from the handover contract in the comments YAML.
- Plan-review keys include `cross_artifact_consistency`, `feasible_mechanism`, `budget_realism`, and `dof_minimality`.
- Treat checklist values as `pass`, `fail`, or `not_applicable` only.
- Keep the summary factual and the required fixes concrete.

## Evidence fields

- `latest_revision_verified`
- `review_manifest_revision`
- `render_count`
- `inspected_render_count`
- `visual_inspection_min_images`
- `visual_inspection_satisfied`
- `deterministic_error_count`
- `deterministic_refusal_reason`
- `solvability_summary`
- `attachment_policy_summary`

## Output and submission

- Write only the stage-scoped benchmark-plan review decision YAML and comments YAML under `reviews/`.
- Keep comments factual, specific, and tied to evidence.
- Submit the review with `bash scripts/submit_review.sh` after the files are written.
