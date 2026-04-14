# current_role.json Acceptance Criteria

## Role of the File

`.manifests/current_role.json` is the backend-owned marker for the role that
is actively running a workspace node.
It exists so submission helpers, preview helpers, and node-entry validation
can read one explicit role source instead of inferring from filenames or
environment state.

## Hard Requirements

- The file exists under `.manifests/` for every materialized workspace.
- The file is valid JSON.
- The file is a JSON object with one required string field, `agent_name`.
- `agent_name` is a valid `AgentName` string and matches the role currently
  entering or running the workspace.
- The file is rewritten when the workspace transitions to another node.
- The file is backend-owned metadata and is not writable by agent roles.
- Helpers treat the file as authoritative and fail closed on missing,
  malformed, or stale content.

## Quality Criteria

- The file is easy to diff and carries only the active role marker.
- Role lookup does not depend on `AGENT_NAME`, prompt markers, or workspace
  filename presence.
- The file stays stable across repeated retries inside the same node.

## Reviewer Look-Fors: File Antipatterns to Look For

- The file is missing, malformed, or stale.
- The file content does not match the active node.
- A helper or validator falls back to file-presence heuristics or env-based
  inference.

## Cross-References

- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/agent-harness.md`
- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/tools.md`
