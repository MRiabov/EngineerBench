---
name: benchmark-coder
description: Benchmark implementation role for turning approved benchmark plans into benchmark_script.py and helper modules, validating and simulating benchmark revisions, preserving planner inventory exactness, handling benchmark-side motion or imported fixture geometry, and refusing only when the approved plan is infeasible. Use when working as the Benchmark Coder after plan approval, when fixing benchmark validation or simulation failures, when producing review-ready benchmark evidence, when deciding whether to write plan_refusal.md, or when inspecting simulation evidence through frame-indexed `objects.parquet` sidecars.
---

# Benchmark Coder

This skill operationalizes the `benchmark_coder` prompt in `config/prompts.yaml` and the benchmark handoff contracts. It keeps the role focused on the current approved plan, the read-only benchmark context, and the validation/simulation gate that decides whether the benchmark is ready for review.

## Mission

1. Turn the approved benchmark handoff into a working `benchmark_script.py`.
2. Implement the benchmark geometry exactly as declared, without inventing new fixture behavior or sizes.
3. Keep the authored benchmark import-safe, reviewable, and easy to revise.
4. Validate and simulate the latest revision before handoff.
5. Refuse cleanly when the approved plan is genuinely infeasible.

## Canonical Helpers

Use the runtime helpers explicitly in authored benchmark scripts:

```python
from utils.submission import validate_benchmark, simulate_benchmark, submit_benchmark_for_review
from utils.preview import (
    list_render_bundles,
    objectives_geometry,
    pick_preview_pixel,
    pick_preview_pixels,
    render_cad,
    query_render_bundle,
)
```

- `validate_benchmark(result)` and `simulate_benchmark(result)` are the required pre-handoff checks.
- `submit_benchmark_for_review(result)` is the final benchmark review handoff helper.
- `render_cad(...)` is the live scene and objective-overlay path; use `payload_path=True` only when the current workflow needs the live payload-path overlay.
- `objectives_geometry()` reconstructs benchmark objective overlays when needed.
- `list_render_bundles()` selects the exact current or historical render bundle before you inspect media or point-pick results.
- `query_render_bundle()` returns compact bundle metadata and frame/object slices without pulling the full media payload.
- `pick_preview_pixel()` and `pick_preview_pixels()` resolve screen-space points against the bundle-local snapshot when click-to-world evidence matters.
- `from utils.visualize import ...` is a compatibility alias, but `utils.preview` is the preferred namespace for new code.
- When simulation evidence exists, inspect the MP4 and the sampled frame-indexed `objects.parquet` pose-history sidecar together; `frames.jsonl` is sparse timing metadata only.

## Geometry Contract

- Base every size, offset, and clearance on approved geometry, declared dimensions, or explicit formulas.
- Do not guess a number. If the handoff or workspace context is missing a needed value, treat it as a defect and stop.
- For moving benchmark fixtures, derive pose and travel from the declared axis or joint frame, not from an arbitrary world coordinate.
- Prefer selector-driven placement over free-form XYZ positioning. Use face/axis selectors and explicit mates/joints when materializing the approved benchmark geometry; if the plan truly requires absolute 3-coordinate anchors, preserve only the few already approved and treat them as prone to mispositioning.

## What This Skill Owns

- Implementation strategy for `benchmark_script.py` and supporting `*.py` files.
- File-level execution discipline for `todo.md`, `journal.md`, and `plan_refusal.md`.
- Validation, simulation, evidence inspection, and submission readiness for benchmark revisions.
- The decision rules for when to continue iterating and when to refuse the approved plan.

## What This Skill Does Not Own

- `benchmark_definition.yaml` or `benchmark_assembly_definition.yaml`; those are benchmark-owned read-only context after plan approval.
- `benchmark_plan_evidence_script.py`; that is planner-owned read-only context.
- Reviewer outputs under `reviews/`.
- Engineer solution files such as `solution_script.py`.

## Workspace Boundary

When this role begins from a seeded workspace, treat the following paths as writable starter content:

- `benchmark_script.py`
- `todo.md`
- `journal.md`
- any benchmark-side helper modules
- `plan_refusal.md` when the approved plan is infeasible

Treat the following paths as read-only reference inputs:

- `benchmark_plan.md`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_plan_evidence_script.py`
- validation and simulation outputs
- render evidence
- reviewer artifacts

Do not pre-solve the writable files or rewrite read-only benchmark context as if the benchmark coder owns it.

## Required Read Set

Start with the benchmark handoff package:

- `benchmark_plan.md`
- `todo.md`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_script.py` when it already exists
- `benchmark_plan_evidence_script.py`
- `validation_results.json`
- `simulation_result.json`
- `scene.json`
- `renders/**`
- `reviews/**`

## Plan Grounding

When `benchmark_plan.md` or the planner-authored evidence script already encode the approved labels, repeated quantities, or geometry, copy that exact contract forward into `benchmark_script.py` instead of re-deriving it. The benchmark coder translates the approved plan into build123d; it does not reinterpret the contract.
Treat the planner YAML handoff as the machine-readable source of truth and the planner evidence script as the inspectable source of the approved benchmark solution.
Because the approved planner handoff has already passed collision and geometry review, treat its layout as collision-validated and preserve the exact dimensions, offsets, and clearances whenever the plan is feasible to implement as written.
That collision review does not imply manufacturability validation or simulation coverage; the coder still has to validate and simulate the implemented revision before handoff.
When the benchmark planner uses its structured template, read `benchmark_plan.md` as a sectioned contract, not prose: the useful sections include `Learning objective`, `Environment geometry (with static randomization)`, `Input objective (payload)`, `Objective locations`, `Simulation bounds`, `Constraints handed to engineering`, `Success criteria`, and `Planner artifacts`.

Load sibling skill guidance only when it changes the implementation outcome:

- [engineer-coder](../engineer-coder/SKILL.md) for shared implementation discipline such as import safety, validation strategy, and evidence handling.
- [render-evidence](../render-evidence/SKILL.md) when media inspection or render bundle handling is needed.
- [runtime-script-contract](../runtime-script-contract/SKILL.md)
- [build123d-cad-drafting-skill](../build123d-cad-drafting-skill/SKILL.md)
- [mechanical-engineering](../mechanical-engineering/SKILL.md)
- [manufacturing-knowledge](../manufacturing-knowledge/SKILL.md) when cost or weight constraints drive the design.
- [specs/architecture/agents/agent-artifacts/README.md](../../../specs/architecture/agents/agent-artifacts/README.md) when you need file-level acceptance criteria for `benchmark_script.py`, validation, simulation, `scene.json`, `plan_refusal.md`, or render evidence.

## Source Hierarchy

When files disagree, use the strictest currently approved contract in this order:

1. The approved benchmark handoff artifacts for the current revision.
2. Benchmark-owned read-only context already present in the workspace.
3. Benchmark implementation files and workspace evidence.
4. Runtime contracts and specialist skills.

Do not invent fallback behavior to paper over contradictions. If the approved plan is internally inconsistent or cannot be implemented, surface that with evidence.

## Operating Loop

1. Read the handoff quickly and reconstruct the objective, zones, randomization, and benchmark-side motion contract.
2. Choose the smallest benchmark geometry family that can satisfy the plan.
3. Implement or revise `benchmark_script.py` and helper modules.
4. Run `python benchmark_script.py` as the canonical execution path.
5. Fix import, geometry, labeling, or contract failures first.
6. Run validation and simulation on the latest revision.
7. Inspect render images or simulation media when they exist or when motion behavior is uncertain. If the question depends on bundle identity or pixel-to-world mapping, select the exact bundle with `list_render_bundles()` and query that bundle-local snapshot with `query_render_bundle()` or `pick_preview_pixel()` before changing geometry.
8. Keep `todo.md` and `journal.md` synchronized with the work actually being done.
9. Submit for review only when the latest revision is valid, simulated, and ready.

## Design Rules

- Prefer passive geometry unless the approved benchmark explicitly requires motion.
- Never invent benchmark-side motion, fallback labels, hidden constraints, or undeclared fixture behavior.
- Keep benchmark-owned fixtures and objective overlays read-only and reconstruct them faithfully.
- Keep planner-authored evidence grounded in the approved inventory. The labels and repeated quantities in that script and in `benchmark_plan.md` must match the approved handoff exactly; missing, extra, or relabeled items are contract failures, not implementation freedom.
- Do not "clean up" or resize a collision-validated planner layout to make it look simpler; preserve the approved dimensions and placement relationships unless the plan is genuinely infeasible and must be refused.
- Preserve explicit motion contracts for any moving benchmark fixture: identity, motion kind, axis or path, bounds, trigger, and engineer interaction flag if relevant.
- Keep authored labels unique and stable.
- Use the simplest geometry that still satisfies the reviewed plan and the runtime jitter.
- Use imported components only when exact part identity matters, and preserve the concrete part instance.
- Keep scripts import-safe. The final benchmark assembly must be exposed as `result = build()` or as a `build()` function returning a `Compound`.

### Ball-Transfer Benchmarks

When the benchmark involves a spawned payload ball rolling along a transfer surface:

- **Do NOT include the payload in `build()`** — the simulation system spawns `benchmark_moved_object__projectile_ball` independently from `benchmark_definition.yaml`. Returning it from `build()` creates a duplicate body at the same position; the two balls collide and explode apart, causing instant `OUT_OF_BOUNDS`. The evidence script (`benchmark_plan_evidence_script.py`) returns fixtures only — match that pattern.
- **Ball drop distance controls bounce** — a drop of ≤ 2 mm onto the transfer surface minimises bounce. If the ball bounces wildly, the surface is too far below the spawn point. Raise the surface until the gap is small; do not widen walls or add mass to compensate.
- **Forbid-zone ceiling constraint** — the ball centre must stay above the forbid zone's max-Z while crossing the forbid zone's X,Y bounds. For a sphere of radius *r*, the surface height *h* at any point inside the forbid zone must satisfy *h + r > forbid_zone_max_z*. With *r* ∈ [4, 6] mm and a forbid zone ceiling at Z = 14, the surface needs *h* > 8–10 mm at the crossing point.
- **Lateral containment is valid** — thin side walls placed outside the forbid zone Y-bounds are a legitimate strategy for keeping the ball on a sloped surface. Verify walls do not intersect the forbid zone, existing fixtures, or the gap floor guard.

## Retry Discipline

- Change one dominant failure mode at a time.
- If a validation failure repeats after one targeted fix, record that in `journal.md` and reconsider the benchmark family instead of layering unrelated edits.
- Do not widen the search with unrelated repo spelunking once the objective is clear.
- Distinguish plan infeasibility from implementation mistakes.
- Refusal is valid only for an infeasible approved plan, not for generic coding failure.

## Evidence And Review

- Validation success is necessary but not sufficient.
- Simulation success is necessary but not sufficient.
- If render images or simulation media exist, inspect them before handoff, especially when motion is present.
- If `render_cad(...)` evidence exists for the current revision, inspect the render bundle before changing geometry.
- After any significant blocker or repeated failure on the same issue, inspect the current render or simulation evidence before the next geometry change. If the same issue has failed more than three times in a row, keep inspecting render evidence on every subsequent retry until the blocker changes; use `../render-evidence/SKILL.md` as the visual-inspection playbook.
- Treat screenshots and video as evidence, not as text summaries.
- Keep review readiness tied to the current revision, not a stale earlier run.

### Simulation Trajectory Diagnostics

When a simulation fails with `OUT_OF_BOUNDS` or `FORBID_ZONE_HIT`, inspect the frame-indexed `objects.parquet` sidecar before changing geometry:

```python
import pandas as pd
from pathlib import Path

# Find the latest simulation parquet
parquet_files = sorted(Path('.').rglob('objects.parquet'))
df = pd.read_parquet(parquet_files[-1])
ball = df[df['label'].astype(str).str.contains('projectile_ball')]
for _, row in ball.iterrows():
    print(f'  frame={row.frame_index} pos={row.position}')
```

- **1–2 frames captured, position jumps to ~±48**: the ball never landed on any surface. It either fell through a gap or was launched by a collision with a duplicate body. Check: (a) the payload is NOT in `build()`, (b) every fixture that should catch the ball actually exists and is positioned correctly.
- **Many frames, gradual drift off an edge**: the ball is on a surface but the slope or exit trajectory carries it past the bounds. Adjust the bridge end height or add lateral containment.
- **`FORBID_ZONE_HIT`**: the ball centre entered the forbid zone. Raise the transfer surface at the crossing point so that `surface_height + ball_radius > forbid_max_z`.
- **`PHYSICS_INSTABILITY` with `[Errno 111] Connection refused`**: the physics engine crashed, often due to intersecting geometry or extreme velocities. Run validation first — geometric intersections in the fixture set cause this.

## Refusal Path

- Refuse only when the approved benchmark plan is genuinely infeasible or contradictory.
- If `benchmark_plan.md` is not exact-grounded or the planner-authored scripts drift from the approved inventory, surface the handoff defect instead of compensating in `benchmark_script.py`.
- Write `plan_refusal.md` with concrete evidence.
- Do not silently pivot to a different benchmark.

## Extending This Skill

- Add recurring benchmark geometry families and implementation heuristics to `references/benchmark_patterns.md`.
- Add recurring blockers, diagnostics, and repair patterns to `references/failure_modes.md`.
- Mirror shared patterns from `engineer-coder` only when the benchmark semantics are actually the same.
