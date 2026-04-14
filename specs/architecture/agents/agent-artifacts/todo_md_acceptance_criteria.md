# todo.md Acceptance Criteria

## Role of the File

`todo.md` is the execution-order checklist for the current stage.
It is worth being a dedicated artifact because it tells the next role what remains to be done, in what order, without leaking stale bookkeeping from earlier stages.

## Hard Requirements

- The TODO list reflects the current stage only.
- The items are ordered in execution order and are concrete enough to act on.
- Checkboxes are used consistently.
- Completed items are marked consistently with the current revision state.
- The list matches the plan and the seeded artifacts.
- The file does not introduce unsupported work outside the current contract.

## Quality Criteria

- Each line maps cleanly to a real next action, not a vague intention.
- The checklist is short enough to be useful but complete enough to debug progress.
- Stage transition state is obvious at a glance.

## Reviewer Look-Fors: File Antipatterns to Look For

- Stale items from a prior stage remain in the file.
- Completed-state markers do not match the current workspace state.
- The checklist hides unsupported work, missing dependencies, or off-contract tasks.
- The order of items does not match the actual execution sequence.

## Cross-References

- `specs/architecture/agents/roles.md`
- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
