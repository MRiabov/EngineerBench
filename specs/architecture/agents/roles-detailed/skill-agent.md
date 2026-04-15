# Skill Agent

## Role Summary

The Skill Agent stages skill improvements into the session-local overlay, not the canonical skill repo.

## What It Owns

- `suggested_skills/**`
- `journal.md` entries that describe the skill loop

## What It Reads

- canonical `.agents/skills/**`
- `suggested_skills/**` when it already exists
- run journals, review artifacts, validation/simulation outputs, and render evidence
- `specs/architecture/agents/agent-skill.md`

## Native Tool Surface

- `list_files`
- `read_file`
- `write_file`
- `edit_file`
- `grep`
- `execute_command`
- `inspect_topology`
- `save_suggested_skill`

## What Humans Must Tell It

- Stage small skill updates only.
- Keep the canonical `.agents/skills` tree read-only.
- Use the session-local overlay as the active working tree for the skill loop.
- Preserve provenance and do not drop in a second prompt system by accident.
- If a skill fix needs domain context, tell it which role behavior or tool contract is failing.
- Use `journal.md` for skill-loop notes; if bug-report mode is enabled and runtime plumbing blocks progress, also file `bug_report.md` at the workspace root.

## Acceptance Checklist

- The skill delta is small and reviewable.
- The change is written to `suggested_skills/**` first.
- The canonical skill repo is untouched unless a separate promotion flow publishes the result.

## Related Skills

- `.agents/skills/agent-skill.md`
- `.agents/skills/skill-creator/SKILL.md`
