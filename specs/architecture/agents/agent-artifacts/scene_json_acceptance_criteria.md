# scene.json Acceptance Criteria

## Role of the File

`scene.json` is the serialized scene snapshot for selected seeded workflows.
It is worth being a dedicated artifact because later seed repair and review workflows need an exact, parseable snapshot of the authored scene state rather than a text-only description.

## Hard Requirements

- The file matches the authored source and evidence.
- The file is parseable and current to the seeded revision.
- The file preserves exact object identities needed by the role.

## Quality Criteria

- The snapshot is complete enough to support later comparison against the persisted workspace.
- The identities and structure are stable enough that reviewers do not have to guess which object is which.
- The file is specific enough to be useful without recreating the scene from scratch.

## Reviewer Look-Fors: File Antipatterns to Look For

- The snapshot is stale or belongs to a different revision.
- Object identities, counts, or labels drift from the authored source.
- The file is parseable but not useful for comparing the current workspace state.
- The scene state in the snapshot does not agree with the evidence or the current workspace.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/rendering.md`
- `specs/architecture/simulation.md`
