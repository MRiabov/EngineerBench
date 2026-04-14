# Review Contracts

## Core checklist

- Review only the latest revision in the active workspace.
- Treat planner and coder artifacts as read-only.
- Fail closed on missing, stale, or invalid reviewer manifests.
- Use `inspect_media(...)` whenever render or video media exist.
- Use `specs/architecture/agents/agent-artifacts/README.md` for the file-level acceptance criteria that sit underneath this review contract.
- Let the decision YAML drive routing; keep comments YAML explanatory.
- Keep validation strict. Unknown fields, stale files, or cross-revision artifacts invalidate the review.
- Treat `solution_plan_evidence_script.py` as the inspectable source of the approved plan.
- Use `references/motion-trajectory-review.md` for any motion or payload trajectory claim.

## Plan review gate

- Manifest: `.manifests/engineering_plan_review_manifest.json`
- Required files:
  - `engineering_plan.md`
  - `todo.md`
  - `benchmark_definition.yaml`
  - `assembly_definition.yaml`
  - `solution_plan_evidence_script.py`
- Reject when inventory labels, repeated quantities, or COTS identities drift across the plan and drafting scripts.
- Reject when `engineering_plan.md` omits exact identifier mentions for declared labels and selected `part_id`s.
- Reject when the plan exceeds benchmark caps, depends on invented materials, or leaves the operating envelope implicit.
- Reject excessive or unjustified engineering DOFs.
- Reject prose-only motion or payload trajectory claims.
- Reject motion forecasts that are not backed by formulas, anchor order, contact order, or tolerance derivations.
- Inspect renders if available before approval.

## Execution review gate

- Manifest: `.manifests/engineering_execution_handoff_manifest.json`
- Required files:
  - `solution_script.py`
  - helper `*.py` files owned by the current revision
  - `engineering_plan.md`
  - `todo.md`
  - `benchmark_definition.yaml`
  - `assembly_definition.yaml`
  - `validation_results.json`
  - `simulation_result.json`
- Reject when the implemented inventory or motion contract drifts from the approved plan.
- Reject when validation or simulation is absent, stale, or failed.
- Reject when runtime jitter is not exercised or the solution is flaky across seeds.
- Reject when render images or simulation video exist and were not inspected before approval.
- Flag unnecessary DOFs as a robustness risk even when a single run succeeds.
- Reject implementation evidence that leaves motion or payload trajectory ambiguous, prose-only, or unsupported by the approved contract.

## Refusal review

- Require `plan_refusal.md` when the coder refuses an approved plan.
- Confirm only when the refusal contains role-specific reasons and concrete evidence that the plan is infeasible.
- Reject generic coding failure, missing evidence, or a refusal that can still be implemented.

## Review output files

- Plan review decision: `reviews/engineering-plan-review-decision-round-<n>.yaml`
- Plan review comments: `reviews/engineering-plan-review-comments-round-<n>.yaml`
- Execution review decision: `reviews/engineering-execution-review-decision-round-<n>.yaml`
- Execution review comments: `reviews/engineering-execution-review-comments-round-<n>.yaml`

## Comment checklist keys

- Plan reviewers use `cross_artifact_consistency`, `feasible_mechanism`, `budget_realism`, and `dof_minimality`.
- Execution reviewers use `latest_revision_verified`, `validation_success`, `simulation_success`, `visual_evidence_checked`, `dynamic_evidence_checked`, `plan_fidelity`, `robustness`, `cost_weight_compliance`, `manufacturability_compliance`, and `dof_deviation_justified`.
- Treat checklist values as `pass`, `fail`, or `not_applicable`.
