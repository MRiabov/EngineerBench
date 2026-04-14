# Eval Seed Hygiene

Use these rules when repairing or extending eval seeds for the engineering planner.

## Validation Sequence

1. Validate the smallest relevant seed slice first with `scripts/validate_eval_seed.py`.
2. Fix the seed artifacts, not the validator, when a drafting or grounding mismatch appears.
3. Re-run the narrowest passing slice before widening scope.

## Drafting Seeds

- Keep `benchmark_plan_evidence_script.py` aligned with the benchmark-owned fixture contract only.
- Do not pull solution-side parts into benchmark drafting geometry.
- Preserve checked-in render bundles and manifests when the seed contract expects them.
- Do not rely on ad hoc regeneration to make a seed valid if the repository is supposed to own the render artifacts.

## Planner Grounding

- Keep `engineering_plan.md` exact-mention complete for every planner-declared inventory label and selected COTS `part_id`.
- Keep labels stable across `engineering_plan.md`, YAML, and both drafting scripts.
- Prefer read-only benchmark-owned context when the benchmark handoff is the source of truth.

## Practical Check

When a seed is close but still failing, inspect the current failure mode and patch the source contract directly:

- missing or stale render bundle manifests
- benchmark evidence scripts that drift beyond the benchmark-owned fixture
- plan text that omits a required exact identifier mention
