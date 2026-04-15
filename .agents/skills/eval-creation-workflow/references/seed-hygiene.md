# Seed Hygiene

Use these rules when repairing or extending eval seeds for Problemologist.

## Validation Sequence

1. Validate the smallest relevant seed slice first with `scripts/validate_eval_seed.py`.
2. Fix the seed artifacts, not the validator, when a drafting or grounding mismatch appears.
3. Re-run the narrowest passing slice before widening scope.

## Role Selection

- Planner-style entrypoints may be prompt-only.
- Coder, reviewer, and downstream role evals must be seeded with the files that role is supposed to receive at entry.
- Retry and rejection cases should seed the rejection context too, such as review files or validation logs.

## Artifact Rules

- Do not invent alternate filenames for handoff artifacts or reviewer manifests.
- Prefer `seed_artifact_dir` over large inline `seed_files`.
- Use `seed_files` only for tiny cases or one-off overrides.
- If a stage requires a manifest or hash, populate a real contract-valid file rather than weakening validation, and compute any deterministic derived values exactly.
- Negative eval cases must still pass deterministic hard checks at seeded entry so the run reaches LLM evaluation.

## Stage Defaults

- `benchmark_planner`: usually prompt-only.
- `benchmark_coder`: seed `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `journal.md`.
- `benchmark_reviewer`: seed `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `journal.md`, `script.py`, `validation_results.json`, `simulation_result.json`, `.manifests/benchmark_review_manifest.json`.
- `engineering_planner`: usually prompt-only or seeded with `engineering_plan.md`, `todo.md`, `benchmark_definition.yaml`, `assembly_definition.yaml`, and `benchmark_assembly_definition.yaml`.
- `engineering_*` roles: seed `engineering_plan.md` plus the role-appropriate downstream artifacts from the active handoff.
- Engineering roles: follow `specs/architecture/agents/handover-contracts.md` exactly.

## Practical Check

When a seed is close but still failing, inspect the current failure mode and patch the source contract directly:

- missing or stale render bundle manifests
- benchmark evidence scripts that drift beyond the benchmark-owned fixture
- plan text that omits a required exact identifier mention
