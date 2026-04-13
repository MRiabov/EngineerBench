# Reviewer Manifest Acceptance Criteria

## Role of the File

The reviewer manifest is the stage routing gate metadata written under `.manifests/` for reviewer entry points.
It is worth being a dedicated artifact because reviewer-stage routing must fail closed on stale, missing, or wrong-stage handoff metadata.

## Required Manifests

- `.manifests/benchmark_plan_review_manifest.json`
- `.manifests/benchmark_review_manifest.json`
- `.manifests/engineering_plan_review_manifest.json`
- `.manifests/engineering_execution_handoff_manifest.json`

Older references in the repo may still use the legacy `engineering_execution_review_manifest.json` wording.
The live runtime contract uses the handoff name above.

## Hard Requirements

- The stage-specific manifest exists for the active reviewer stage.
- The manifest is schema-valid and points at the latest revision only.
- The manifest matches the stage being evaluated.
- The manifest carries valid revision and session metadata, including `reviewer_stage`.
- The manifest filename matches the live runtime contract for that stage, including `.manifests/engineering_execution_handoff_manifest.json` for engineering execution.
- Comments YAML and decision YAML remain tied to the same current package.

## Quality Criteria

- The manifest is explicit enough that routing and artifact lookup do not depend on guesswork.
- The stored metadata is sufficient to tell whether the reviewer is looking at the current revision and session.
- The file keeps the stage boundary visible rather than hiding it behind generic metadata.

## Reviewer Look-Fors

- The manifest is missing, stale, schema-invalid, or for the wrong stage.
- Session metadata points at a different workspace revision or another session entirely.
- The file uses legacy wording without matching the live runtime filename.
- A reviewer would have to infer the current package from text instead of reading the manifest.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/evals-architecture.md`
