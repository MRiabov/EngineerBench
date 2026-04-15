# Runtime Script File Map

This reference explains the workspace files that the runtime script contract skill governs.

## Planner and Coder Artifacts

- `benchmark_definition.yaml`: benchmark-owned constraints, zones, randomization, and caps. Downstream stages read it as context, not as editable source.
- `benchmark_assembly_definition.yaml`: benchmark-owned fixture geometry and motion context copied into engineer workspaces. Treat it as read-only context.
- `assembly_definition.yaml`: planner-owned engineer handoff and the source of truth for solution-side parts, constraints, and final assembly.
- `benchmark_plan.md`: the human-readable benchmark plan that should match the validated benchmark handoff.
- `engineering_plan.md`: the human-readable engineering plan that should match the validated handoff.
- `todo.md`: the execution checklist and progress ledger for the current stage.
- `journal.md`: the run memory for blockers, failed probes, and debugging notes.
- `benchmark_script.py`: benchmark-owned geometry source. Downstream stages treat it as read-only context.
- `solution_script.py`: engineer-authored implementation source. It should expose the final assembly via `result = ...`.
- `references/function_signatures.md`: current submission-helper signatures for `validate_benchmark(...)`, `validate_engineering(...)`, `simulate_benchmark(...)`, `simulate_engineering(...)`, `submit_benchmark_for_review(...)`, and `submit_solution_for_review(...)`.

## Review And Evidence Artifacts

- `reviews/**`: stage-scoped review decisions and comments.
- `renders/**`: visual evidence for inspection, validation, and simulation.
- `.manifests/**`: backend-owned submission state. Agents should not read or write it directly.
