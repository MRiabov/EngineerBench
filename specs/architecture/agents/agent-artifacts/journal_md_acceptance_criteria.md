# journal.md Acceptance Criteria

## Role of the File

`journal.md` is the debugging and attempt log for the current revision.
It is worth being a dedicated artifact because it preserves blockers, failed probes, and next steps without replacing the canonical handoff files.

## Hard Requirements

- The journal records blockers, failed probes, and next steps.
- Entries are concrete, time-ordered, and tied to the current revision.
- The journal distinguishes observations from conclusions.
- The file remains consistent with the visible workspace state.

## Quality Criteria

- The notes are specific enough to help a later session resume the run quickly.
- The journal captures why a dead end was explored, not just that it failed.
- The entries are short and actionable rather than narrative filler.

## Reviewer Look-Fors: File Antipatterns to Look For

- Vague status notes or generic commentary replace concrete attempts.
- The journal references stale revisions or artifacts that are no longer present.
- Conclusions are stated without a supporting observation or probe result.
- The journal is used as a substitute for the actual plan, YAML, or review contract.

## Cross-References

- `specs/architecture/agents/roles.md`
- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
