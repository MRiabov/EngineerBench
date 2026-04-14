---
name: runtime-script-contract
description: Canonical import and execution contract for authored benchmark and engineer scripts. Use when writing `benchmark_script.py` or `solution_script.py` that call validation, simulation, or submission helpers.
---

# Runtime Script Contract

Use this skill when authoring build123d scripts that the runtime will execute or inspect.

## Canonical Sources

- `benchmark_script.py`: benchmark-owned geometry source. Treat it as read-only context in downstream engineer and reviewer stages.
- `solution_script.py`: engineer-authored implementation source.

## Read This

- `references/files.md` for the workspace file map and artifact ownership rules.
- `references/function_signatures.md` for the current submission-helper signatures.
- `../render-evidence/references/function_signatures.md` for the current preview and point-pick helper signatures.

## Canonical Imports

Use top-level `utils` imports in authored scripts:

```python
from utils.submission import (
    validate_benchmark,
    simulate_benchmark,
    submit_benchmark_for_review,
    validate_engineering,
    simulate_engineering,
    submit_solution_for_review,
)
from utils.metadata import PartMetadata, CompoundMetadata
from utils.preview import (
    list_render_bundles,
    objectives_geometry,
    pick_preview_pixel,
    pick_preview_pixels,
    preview,
    query_render_bundle,
)
```

`shared.*` paths are implementation internals. Do not use them in authored agent scripts.

For render evidence and point-pick workflows, prefer the namespaced helpers in `utils.preview`; use `utils.visualize` only as a compatibility alias when older code already references it. `list_render_bundles()` selects the exact bundle, `query_render_bundle()` returns compact bundle slices, and `pick_preview_pixel()` / `pick_preview_pixels()` resolve pixel-to-world evidence against the bundle-local snapshot.
The exact callable signatures live in the reference snapshots listed above; use those files instead of calling `help(...)` during every eval run.

For ordinary mechanical engineer scripts, keep imports minimal:

- default to `build123d` plus `utils.metadata`
- add other `utils.*` imports only when the final geometry or task contract actually uses them
- do not leave unused helper imports in the final file

## Core Contract

- Bind the final object at module scope as `result = ...`.
- `build()` remains an optional compatibility helper, not the primary contract.
- Keep the primary geometry and assembly definition in the stage-owned authored file.
- For benchmark coder tasks, implement the approved benchmark in `benchmark_script.py`.
- For engineering coder tasks, implement the approved solution in `solution_script.py`.
- In benchmark and engineer assemblies, every top-level child label must be unique and must not be `environment` or start with `zone_`. Those names are reserved for the scene root and simulator-generated objective bodies, and duplicate labels collide with MJCF mesh/body names.

## Evaluation Playbook

Use this sequence for benchmark-coder and engineer-coder evals:

01. Read `benchmark_plan.md` for benchmark-coder tasks or `engineering_plan.md` for engineer-coder tasks, plus `todo.md`, `assembly_definition.yaml`, and `benchmark_definition.yaml`.
02. If benchmark geometry exists, read `benchmark_script.py` as read-only context before drafting the solution.
03. Read `skills/build123d-cad-drafting-skill/SKILL.md` before the first geometry draft.
04. If the design includes imported components, read the relevant part-identity guidance before drafting the part geometry or motion contract.
05. Only read `skills/electronics-engineering/SKILL.md` if the approved handoff explicitly contains an `electronics` section or the benchmark declares `electronics_requirements`. Motors alone do not imply an electronics task, and mechanical wire-routing placeholders do not qualify.
06. Keep the first `solution_script.py` draft compact and complete for the handoff. Prefer a direct `result = ...` binding and avoid extra helper files.
07. Run one cheap syntax check first, then one real probe against the authored file:
    - `py_compile` or equivalent
    - import `result` from the authored file
    - `from utils.submission import validate_benchmark, simulate_benchmark` for benchmark scripts or `validate_engineering, simulate_engineering` for engineering scripts
    - `validate_benchmark(result)` / `simulate_benchmark(result)` or `validate_engineering(result)` / `simulate_engineering(result)` if validation passes
    - If local `simulate_engineering` fails with sandbox/infra errors (`Operation not permitted` from EGL/GPU, `httpx.ConnectError` to workers) while validation passes, proceed to `submit_solution_for_review(result)` anyway. The eval runner executes simulation through the real heavy-worker path. Record the sandbox limitation in `journal.md` and do not loop on geometry for infra barriers.
08. If validation fails, fix the geometry or placement in the authored file, not the execution contract.
09. If the same issue persists after one targeted fix, record the blocker in `journal.md` and stop diagnostics instead of widening into repo spelunking.
10. For engineer-owned scripts, do not copy benchmark-only `fixed=True` examples into the implementation unless the current task explicitly says you are authoring benchmark fixtures.
11. If the workspace includes a reviewer-approved seed artifact for the same mechanism family, mirror its placement pattern and datums before inventing a new layout.
12. If the task includes explicit electronics requirements, keep the electrical design in the approved handoff artifacts and direct geometry implementation. Do not import `utils.electronics`, `shared.*`, or `worker_heavy.*` from the authored script.

## Placement Contract

- Place top-level authored parts with `Location(...)` through `move`, `moved`, or direct `location` assignment.
- Prefer explicit datum alignment for parts that sit on a base plate or floor.
- Do not rely on `part.position = (...)` as the runtime placement contract.

## Execution Modes

Choose the narrowest mode that matches the task contract.

### Import-safe mode

Use when the workspace, validator, or seeded handoff expects the module to be imported safely.

- expose `result` or `build()`
- avoid validation, simulation, or submission side effects on import
- keep the file reusable by external validators

### Script-execution mode

Use only when the task explicitly allows direct execution side effects from the authored script.

- helper calls such as `validate_benchmark(...)`, `simulate_benchmark(...)`, and `submit_benchmark_for_review(...)` or `validate_engineering(...)`, `simulate_engineering(...)`, and `submit_solution_for_review(...)` may live in the module body only when that execution model is explicitly part of the task
- do not add wrapper files just to trigger those helpers

## Contract Boundary

- Validation should operate on the real stage-owned authored file rather than alternate reconstructed geometry.
- If dedicated runtime helper tools are exposed, prefer them; otherwise use one short workspace-root `execute_command(...)` probe that imports `result` from the authored file and calls `utils.submission.validate_benchmark(...)` / `simulate_benchmark(...)` or `validate_engineering(...)` / `simulate_engineering(...)`.
- `execute_command(...)` already runs from the seeded workspace root. Do not prepend `cd /workspace` or other host-specific workspace paths before those checks.

## Safety Rules

01. Do not use `if __name__ == "__main__":` in authored scripts.
02. Use workspace-relative paths such as `benchmark_script.py`, `solution_script.py`, `todo.md`, and `renders/preview.png`.
03. Do not add a leading slash to workspace artifacts. Use `benchmark_script.py`, `solution_script.py`, `journal.md`, `todo.md`, `renders/...`, and `simulation_result.json`, not `/benchmark_script.py`, `/solution_script.py`, `/journal.md`, `/todo.md`, `/renders/...`, or `/simulation_result.json`.
04. Keep long operational guidance in skills like this one rather than copying it into planner/coder prompts.
05. Keep authored scripts terse. Avoid long module docstrings, banner comment blocks, and other decorative prose in files that will be emitted through `write_file(...)`.
06. If a tool call would require a very large or quote-heavy `content` string, simplify the script content first so the `write_file(...)` arguments remain valid JSON.
07. If `write_file(...)` is rejected for invalid JSON arguments, do not retry the same large payload. Write a compact import-safe stub first, then expand the file with smaller `edit_file(...)` replacements.
08. Do not import visualization-only helpers such as `ocp_vscode`, and do not call `show(...)` from authored workspace scripts.
09. Updating `todo.md` is not a reason to stop early. Finish the required assembly unless a concrete blocker forces a partial handoff or refusal.
10. For simple freestanding/passive mechanical seeds, start with the fewest primitives and booleans that satisfy the planner handoff. Avoid decorative fillets, chamfers, and optional detailing unless functionally required.
11. For simple passive seeds, the normal read set is the planner handoff plus any read-only benchmark geometry context that is present. Do not treat general CAD skills or large helper references as mandatory pre-reads before the first draft.
12. If validation or simulation is explicitly required before handoff, a syntax-only `py_compile` check is not enough. Keep the authored file import-safe, then run one real probe against `result` and fix any runtime failure before stopping.
13. If the task expects review handoff, the final workflow step is a Python helper call to `submit_benchmark_for_review(result)` or `submit_solution_for_review(result)` after validation and simulation succeed. This is not a shell helper and it is not a replacement for the validation/simulation checks.
14. Any extra command-like workflow that is not already exposed as a native helper belongs in a checked-in shell script, not a prompt-only pseudo-tool.
