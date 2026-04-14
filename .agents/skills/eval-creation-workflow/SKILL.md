---
name: eval-creation-workflow
description: Create or repair Problemologist eval seeds by adding role-based dataset rows plus stage-correct seeded workspace artifacts with exact deterministic fields, then verify them with minimal-scope runs through dataset/evals/run_evals.py. Use this when asked to add benchmark, engineer, or reviewer evals, or when a role-based eval dataset looks structurally invalid.
---

# Eval Creation Workflow

Use this skill when creating or fixing eval seeds for this repo.

## Role-first reading

When you are seeding a row that should look like another agent's output, read the skill(s) for the agent that would normally produce that workspace first. That keeps the seed representative of the real handoff instead of merely schema-valid.

- `benchmark_planner`: `../benchmark-planner/SKILL.md`
- `benchmark_plan_reviewer`: `../benchmark-planner/SKILL.md`, `../benchmark-coder/SKILL.md`, `../benchmark-plan-reviewer/SKILL.md`
- `benchmark_coder`: `../benchmark-planner/SKILL.md`, `../benchmark-coder/SKILL.md`, `../benchmark-reviewer/SKILL.md`
- `benchmark_reviewer`: `../benchmark-planner/SKILL.md`, `../benchmark-coder/SKILL.md`, `../benchmark-reviewer/SKILL.md`
- `engineer_planner`: `../benchmark-planner/SKILL.md`, `../engineer-planner/SKILL.md`
- `engineer_plan_reviewer`: `../engineer-planner/SKILL.md`, `../engineer-coder/SKILL.md`, `../engineer-plan-reviewer/SKILL.md`, `../benchmark-reviewer/SKILL.md`
- `engineer_coder`: `../engineer-planner/SKILL.md`, `../benchmark-planner/SKILL.md`, `../benchmark-coder/SKILL.md`, `../engineer-plan-reviewer/SKILL.md`, `../benchmark-reviewer/SKILL.md`
- `engineer_execution_reviewer`: `../engineer-coder/SKILL.md`, `../engineer-plan-reviewer/SKILL.md`, `../benchmark-reviewer/SKILL.md`, plus `../../../specs/architecture/agents/handover-contracts.md` when you need the stage contract instead of a local skill file

The main rule is simple: non-initial roles do not get plain prompt-only rows. They get seeded workspace files that match the handoff contract for that stage.

Seeded artifacts must already satisfy any deterministic checks that will run before LLM evaluation; numeric, enum, and derived fields should be materialized exactly, not approximated later.

For the detailed seed-hygiene checklist, contract expectations, and command snippets, see:

- [agent-artifacts README](../../../specs/architecture/agents/agent-artifacts/README.md)
- [references/index.md](references/index.md)
- [references/role_input_index.md](references/role_input_index.md)
- [references/common_seed_failure_patterns.md](references/common_seed_failure_patterns.md)
- [references/file-contract-template.md](references/file-contract-template.md)
- [references/seed-hygiene.md](references/seed-hygiene.md)
- [references/validation-commands.md](references/validation-commands.md)
- [references/artifact_inventory.md](references/artifact_inventory.md)

If a filename does not yet have a dedicated acceptance reference, start from `references/file-contract-template.md` and specialize it with the active role contract, validator, and cross-file checks.
Use `references/artifact_inventory.md` when you need to discover which file families are in scope before authoring the per-file criteria.

## Read first

Open only what you need, but default to these after the role skills above:

1. `specs/desired_architecture.md`
2. `specs/architecture/agents/handover-contracts.md`
3. `specs/architecture/agents/roles.md`
4. `specs/architecture/evals-architecture.md`
5. `specs/dataset-generation.md`
6. `specs/integration-tests.md`

## Non-negotiable rules

01. Planner-style entrypoints may be prompt-only.
02. Coder, reviewer, and downstream role evals must be seeded with the files that role is supposed to receive at entry.
03. Do not invent alternate filenames for handoff artifacts or reviewer manifests.
04. Prefer `seed_artifact_dir` over large inline `seed_files`.
05. Use `seed_files` only for tiny cases or one-off overrides.
06. Validate the seed contract first with `scripts/validate_eval_seed.py`.
07. After the seed validator passes, validate one task at a time with `dataset/evals/run_evals.py`.
08. If a stage requires a manifest or hash, populate a real contract-valid file rather than weakening validation, and compute any deterministic derived values exactly.
09. Negative eval cases must still pass deterministic hard checks at seeded entry so the run reaches LLM evaluation; they may be semantically bad, but they should not be schema-invalid or rely on approximate deterministic fields.
10. Do not add "negative" seeds that are out of bounds, over cost/weight caps, self-intersecting, schema-invalid, or otherwise guaranteed to fail before the target role is evaluated.
11. If the model needs to view changes, regenerate the seed views first with `scripts/update_eval_seed_renders.py` and inspect the regenerated images; do not rely on stale render artifacts or the deprecated `scripts/validate_eval_seed.py --update-renders` alias.

## File layout

- Dataset rows live in `dataset/data/seed/role_based/<agent>.json`
- Seeded stage artifacts live in `dataset/data/seed/artifacts/<agent>/<task-id>/`
- Eval runner entry is `dataset/evals/run_evals.py`

## Stage selection

First decide what role you are creating the eval for.

- Initial planner roles:
  Usually need `id`, `task`, and `expected_criteria`.
- Coder / implementer roles:
  Need upstream handoff artifacts already present in the workspace.
- Reviewer roles:
  Need implementation outputs and reviewer manifest files already present.
- Retry / rejection cases:
  Seed the rejection context too, such as review files or validation logs, instead of describing it only in prose.

## Minimum dataset row pattern

Prompt-only planner row:

```json
{
  "id": "bp-001-example",
  "task": "Create a benchmark where ...",
  "expected_criteria": "Plan includes ..."
}
```

Seeded role row:

```json
{
  "id": "bc-001-example",
  "task": "Use the seeded artifacts in the workspace to ...",
  "seed_artifact_dir": "dataset/data/seed/artifacts/benchmark_coder/bc-001-example",
  "expected_criteria": "Creates ..."
}
```

## Stage artifact defaults

Use these as the default minimums unless the target role contract requires more.

- `benchmark_planner`:
  Usually prompt-only.
- `benchmark_coder`:
  Seed `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `journal.md`.
- `benchmark_reviewer`:
  Seed `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `journal.md`, `script.py`, `validation_results.json`, `simulation_result.json`, `.manifests/benchmark_review_manifest.json`.
- Engineering and electronics roles:
  Seed `engineering_plan.md` and follow the exact handoff contract in `specs/architecture/agents/handover-contracts.md`. Do not guess file names.

For engineering eval seeds with motion proof, keep `assembly_definition.yaml.motion_forecast` and `payload_trajectory_definition.yaml` aligned on the same moving parts, build-safe start, contact order, and terminal goal proof. If `engineering_plan.md` includes timing or speed math, derive it from the exact waypoint sequence in the precise path and state whether the result is an average-segment envelope or a measured runtime trace.

If the role consumes reviewer decisions, also seed the stage-specific review file under `reviews/`.

## File-Specific Reference Library

When this workflow creates or modifies any eval artifact, load the matching acceptance-criteria reference in `../../../specs/architecture/agents/agent-artifacts/` before you finalize the seed.
Use `references/index.md` or `references/artifact_inventory.md` first if you need the file map.

The canonical files in that library use the same basenames as the workspace artifacts, including:

- `benchmark_definition_yaml_acceptance_criteria.md`
- `benchmark_assembly_definition_yaml_acceptance_criteria.md`
- `assembly_definition_yaml_acceptance_criteria.md`
- `plan_md_acceptance_criteria.md`
- `todo_md_acceptance_criteria.md`
- `journal_md_acceptance_criteria.md`
- `benchmark_plan_evidence_script_py_acceptance_criteria.md`
- `solution_plan_evidence_script_py_acceptance_criteria.md`
- `benchmark_script_py_acceptance_criteria.md`
- `solution_script_py_acceptance_criteria.md`
- `validation_results_json_acceptance_criteria.md`
- `simulation_result_json_acceptance_criteria.md`
- `plan_refusal_md_acceptance_criteria.md`
- `workbench_report_md_acceptance_criteria.md`
- `scene_json_acceptance_criteria.md`
- `payload_trajectory_definition_yaml_acceptance_criteria.md`
- `reviewer_manifest_acceptance_criteria.md`
- `benchmark_plan_review_yaml_acceptance_criteria.md`
- `benchmark_execution_review_yaml_acceptance_criteria.md`
- `engineering_plan_review_yaml_acceptance_criteria.md`
- `engineering_execution_review_yaml_acceptance_criteria.md`
- `electronics_review_yaml_acceptance_criteria.md`
- `renders_acceptance_criteria.md`

## Workflow

1. Inspect adjacent seeds for naming, tone, and scope.
2. Determine whether the target role is an initial role or a seeded downstream role.
3. Add or edit the JSON row in `dataset/data/seed/role_based/<agent>.json`.
4. If seeded, create `dataset/data/seed/artifacts/<agent>/<task-id>/`.
5. Materialize the exact files that the role should see on disk at entry.
6. If a manifest references file hashes, compute the real hash and patch the manifest.
7. Run the seeded-entry validator for that one task.
8. Only after the validator passes, run a minimal eval for that one task.
9. Confirm logs show the correct seeded stage entry, not an accidental planner start.

## Review-manifest rule

Reviewer stages are fail-closed.

- Benchmark reviewer manifest path:
  `.manifests/benchmark_review_manifest.json`
- Engineering plan reviewer manifest path:
  `.manifests/engineering_plan_review_manifest.json`
- Engineering execution reviewer manifest path:
  `.manifests/engineering_execution_handoff_manifest.json`
- Electronics reviewer manifest path:
  `.manifests/electronics_review_manifest.json`

If the manifest is missing, stale, or schema-invalid, fix the seeded artifact set. Do not loosen the gate.

## Useful commands

List IDs for one agent:

```bash
jq -r '.[].id' dataset/data/seed/role_based/benchmark_coder.json
```

Run one eval:

```bash
uv run dataset/evals/run_evals.py \
  --agent benchmark_coder \
  --task-id bc-001-example \
  --limit 1 \
  --concurrency 1 \
  --verbose --log-level INFO
```

Validate one seeded entry before the full eval:

```bash
uv run scripts/validate_eval_seed.py \
  --agent benchmark_coder \
  --task-id bc-001-example
```

If render regeneration itself is the thing under repair, use the dedicated
maintenance script directly:

```bash
uv run scripts/update_eval_seed_renders.py \
  --agent benchmark_coder \
  --task-id bc-001-example
```

`scripts/validate_eval_seed.py --update-renders` remains a deprecated
compatibility alias, but `scripts/update_eval_seed_renders.py` is the clearer
entrypoint when seed render updates have significant issues.

Validate an entire agent dataset as a filtering pass:

```bash
uv run scripts/validate_eval_seed.py \
  --agent benchmark_reviewer
```

Validate multiple agents in one command:

```bash
uv run scripts/validate_eval_seed.py \
  --agent "benchmark_planner or benchmark_plan_reviewer" \
  --agent "[benchmark_coder,benchmark_reviewer]"
```

Check that seeding happened:

```bash
rg "eval_seed_workspace_applied|start_node=" logs/evals/run_evals.log logs/evals/controller.log
```

Compute a file hash for manifests:

```bash
sha256sum dataset/data/seed/artifacts/benchmark_reviewer/br-001-example/script.py
```

## Validation checklist

Before finishing, verify all of the following:

1. The JSON row parses cleanly.
2. `seed_artifact_dir` exists for seeded roles.
3. Required stage files are present under that directory.
4. Reviewer manifests use the correct stage-specific filename.
5. The seeded-entry validator passes for the target task.
6. The single-task eval starts at the intended role.
7. The run outcome (pass/fail) is driven by real model/runtime evaluation reasons, not by seed-structure invalidity.
8. For negative cases, hard checks pass and the task reaches the intended LLM-evaluated criterion (for example, reviewer detection of subpar plans/execution evidence).

## What good output looks like

- Planner evals read like realistic user requests.
- Coder evals start with planner artifacts already present.
- Reviewer evals start with implementation artifacts and manifests already present.
- The seeded files are specific enough to exercise the role, but small enough to debug quickly.
- Deterministic fields are exact at entry, not inferred by the evaluator later.

## Anti-patterns

- Prompt-only coder or reviewer rows.
- Embedding giant YAML or Python blobs directly in the JSON row.
- Missing manifests for reviewer stages.
- Using made-up artifact names instead of contract names.
- Skipping the seeded-entry validator and discovering a bad seed only during full eval.
- Validating with broad batches before the single seeded case works.
- Treating hard-check failures as valid "negative" LLM eval cases.
