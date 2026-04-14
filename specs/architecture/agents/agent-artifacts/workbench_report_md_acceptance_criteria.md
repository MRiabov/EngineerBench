# workbench_report.md Acceptance Criteria

## Role of the File

`workbench_report.md` is the short outcome summary for execution-review flows.
It is worth being a dedicated artifact because reviewers need a compact statement of the outcome that still matches the validation and simulation evidence.

## Hard Requirements

- The summary is consistent with validation and simulation evidence.
- The summary names the concrete pass/fail reason.
- The summary does not contradict the review decision or the logs.

## Quality Criteria

- The report is brief enough to scan quickly but specific enough to be useful.
- The summary reflects the current revision rather than a generic run status.
- The wording is grounded in the actual review package, not a paraphrase of unrelated logs.

## Reviewer Look-Fors: File Antipatterns to Look For

- The summary tells a different story from the review artifacts.
- The pass/fail reason is too vague to map back to the run.
- The report references stale validation or simulation data.
- The file reads like a note to self instead of a review-facing outcome summary.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/evals-architecture.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
