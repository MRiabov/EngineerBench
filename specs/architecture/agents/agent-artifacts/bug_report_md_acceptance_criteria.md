# bug_report.md Acceptance Criteria

## Role of the File

`bug_report.md` is the maintainer-facing debug report for runtime and
infrastructure blockers.
It exists so a blocked agent can file one concise, workspace-root report
without turning the bug report into a replacement for `journal.md`,
`plan_refusal.md`, or review YAML.

## Hard Requirements

- The file lives at the workspace root when bug-report mode is enabled.
- The report names the active role.
- The report includes session or episode identifiers when available.
- The report includes the exact failing command, tool call, or runtime action.
- The report states expected versus actual behavior.
- The report references the relevant artifact paths.
- The report stays separate from `journal.md`, `plan_refusal.md`, and stage review artifacts.

## Quality Criteria

- The report is short, factual, and directly actionable for maintainers.
- The blocker description is specific enough to reproduce or triage without reading the entire workspace.
- The report makes it clear whether the blocker is infrastructure, harness, workspace materialization, prompt transport, filesystem policy, render plumbing, eval orchestration, or other runtime plumbing.

## Reviewer Look-Fors: File Antipatterns to Look For

- The file is used as a task journal or a narrative status update.
- The report omits the active role, command, or relevant artifact path.
- The report treats filing itself as a stop condition when the task is otherwise still runnable.
- The report invents task-level failures instead of naming the runtime blocker that actually occurred.

## Cross-References

- `specs/architecture/agents/agent-harness.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/roles.md`
- `specs/architecture/agents/handover-contracts.md`
