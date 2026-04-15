# Role Sheets

## Purpose

This directory contains the detailed role sheets that sit between the thin role prompts and the reusable skill files.

Use these sheets when revising a prompt or a skill. They answer the question the user asked here:

- what the agent does,
- what it owns,
- what it reads,
- what it writes,
- which tools it can actually use,
- what humans must explicitly tell it to make the inputs turn into the desired outputs.

## How To Use

1. Read the sheet that matches the active role before changing `config/prompts.yaml` or the role skill.
2. Update this sheet first when a role changes, then sync the skill file and the prompt.
3. Keep `config/agents_config.yaml` and the sheet in agreement whenever the role's tool surface changes.

## Shared Revision Checklist

When humans revise a prompt or skill, tell the agent at least these things:

- which files it owns and which files are read-only context,
- which skill file is the operating manual,
- which native tools it can call in the current role,
- which runtime helpers it should use from authored scripts,
- which evidence must be inspected before approval,
- which submission gate closes the role,
- whether motion proof or verification rules apply.

## Role Index

- [Benchmark Planner](./benchmark-planner.md)
- [Benchmark Plan Reviewer](./benchmark-plan-reviewer.md)
- [Benchmark Coder](./benchmark-coder.md)
- [Benchmark Reviewer](./benchmark-reviewer.md)
- [Engineering Planner](./engineer-planner.md)
- [Engineering Plan Reviewer](./engineer-plan-reviewer.md)
- [Engineering Coder](./engineer-coder.md)
- [Engineering Execution Reviewer](./engineer-execution-reviewer.md)
- [Journalling Agent](./journalling-agent.md)
- [Skill Agent](./skill-agent.md)
- [Git Agent](./git-agent.md)
