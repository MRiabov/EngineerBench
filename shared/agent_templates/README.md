# Agent Templates

This directory is part of the prompt-context contract.

Rules:

- `common/` contains starter files and helper scripts that are copied into
  materialized workspaces.
- `codex/` contains local Codex helper scripts for the CLI-backed workspace
  flow.
- `shared/assets/template_repos/` provides role-scoped starter workspace
  material that is copied into runs before prompt materialization.
- Prompt text should treat these files as context-bearing inputs, not as a
  separate prompt-authoring system.
