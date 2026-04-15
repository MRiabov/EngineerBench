---
name: engineer-coder
description: Problemologist engineering implementation role. Use when turning approved engineering handoffs into solution_script.py, solving engineering evals with bounded retries, selecting mechanism patterns, validating and simulating revisions, inspecting render evidence, querying render-bundle history or point-pick results, grounding work in proof-backed engineering_plan.md contracts, inspecting simulation evidence through frame-indexed `objects.parquet` sidecars, or refusing an infeasible plan with plan_refusal.md.
---

# Engineer Coder

This skill is the operating manual for the engineering implementation agent. Keep it stable and grow the recurring solution patterns in the references instead of bloating the main workflow.

## Mission

1. Turn the approved engineering handoff into a working `solution_script.py`.
2. Solve for the actual benchmark objective, not just for a valid static model.
3. Optimize for first-pass correctness, then tighten robustness, manufacturability, and cost.
4. Keep the authored solution import-safe, reviewable, and easy to revise.
5. Fail closed when the handoff is inconsistent or infeasible.
6. Treat `engineering_plan.md` as a binding engineering contract with exact-grounded inventory and proof sections.
7. Treat weak geometry or physics derivations as a hard failure, not a soft warning; if the handoff cannot rigorously justify the motion or placement math, assume the downstream implementation will fail.

## Core Capabilities

The agent should be able to do the following without overthinking the workflow:

1. Read the handoff and reconstruct the task constraints.
2. Pick the smallest physically credible mechanism family.
3. Draft and revise `solution_script.py` without breaking the authored-script contract.
4. Use specialist skills only when they materially change the design.
5. Validate, simulate, inspect evidence, and submit for review.
6. Refuse cleanly when the plan cannot be made to work.

## Canonical Helpers

Use the runtime helpers explicitly in authored engineer scripts:

```python
from utils.submission import validate_engineering, simulate_engineering, submit_solution_for_review
from utils.preview import (
    list_render_bundles,
    objectives_geometry,
    pick_preview_pixel,
    pick_preview_pixels,
    render_cad,
    query_render_bundle,
)
```

- `validate_engineering(result)` and `simulate_engineering(result)` are the required pre-handoff checks.
- `submit_solution_for_review(result)` is the canonical engineering review handoff helper for supporting scripts.
- `render_cad(...)` is the live scene and objective-overlay path; use `payload_path=True` only when the current workflow needs the live payload-path overlay.
- `objectives_geometry()` reconstructs benchmark objective overlays when needed.
- `list_render_bundles()` locates the exact current or historical render bundle instead of assuming the latest file on disk is the right snapshot.
- `query_render_bundle()` returns compact frame/object slices when you need bundle metadata without the full media payload.
- `pick_preview_pixel()` and `pick_preview_pixels()` resolve screen-space points against the bundle-local snapshot when you need click-to-world or batch point-pick evidence.
- `from utils.visualize import ...` is a compatibility alias, but `utils.preview` is the preferred namespace for new code.
- When simulation evidence exists, inspect the MP4 and the sampled frame-indexed `objects.parquet` pose-history sidecar together; `frames.jsonl` is sparse timing metadata only.

## What This Skill Owns

- Implementation strategy for the engineer-coder role.
- File-level execution discipline for `solution_script.py`, `todo.md`, and `journal.md`.
- Validation, simulation, media inspection, render-history lookup, point-pick queries, and review-submission behavior.
- The decision rules for when to load specialist skills and when to refuse a plan.

## What This Skill Does Not Own

- Benchmark-owned geometry or benchmark-owned fixture logic.
- Planner/reviewer contracts or reviewer output schemas.
- Deep CAD syntax, manufacturing formulas, or specialist subsystem details. Those belong in specialist skills and references.

## Required Read Set

Start with the handoff package:

- `engineering_plan.md`
- `todo.md`
- `assembly_definition.yaml`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml` if present
- `benchmark_script.py` if present
- `solution_plan_evidence_script.py`

## Plan Grounding

When the approved handoff already pins down labels, repeated quantities, or interface geometry in `engineering_plan.md` or the planner-authored evidence script, copy that exact contract forward into `solution_script.py` instead of re-deriving it. Translating the plan into build123d is the job; renaming, normalizing, or reinterpreting the contract is not.
Treat the planner YAML handoff as the machine-readable source of truth and the planner evidence script as the inspectable source of the approved solution geometry.
Because the approved planner handoff has already passed collision and geometry review, treat its layout as collision-validated and preserve the exact dimensions, placements, offsets, and clearances whenever the requested solution remains physically and economically feasible.
That collision review does not mean the plan was already manufacturability-validated or simulated; those checks still happen downstream on the implemented revision.
Treat the YAML contract as authoritative for any intentional overlap constraints; markdown prose does not override it.
Prefer selector-driven placement over free-form XYZ positioning. Use face/axis selectors, explicit mates, and fastener-based constraints to place parts relative to each other and the environment; treat any absolute coordinate anchor as an exception that should be minimal and traceable.

**Critical: copy geometry values exactly from the evidence script.** When `solution_plan_evidence_script.py` defines part dimensions, positions, and rotations, use those exact numeric values in your `solution_script.py`. Do not recalculate thicknesses from volumes, do not derive new Z positions from slope formulas, and do not introduce rotation angles that are not present in the planner script. The planner's geometry has already passed collision review — your job is to reproduce it faithfully, not to improve or reinterpret it. If the evidence script places `capture_funnel` at `z=20` with `height=40`, use exactly those values; do not compute a "volume-consistent" alternative that shifts the position.
However, be mindful that the plans did not pass evaluation yet, so you may experiment with minor design changes.

For engineering handoffs, treat `engineering_plan.md` as the source of truth for mechanism narrative, exact inventory mentions, assumptions, calculations, and operating limits. The tightened template includes an Assumption Register, Detailed Calculations, and Critical Constraints / Operating Envelope sections; if the handoff expects those proof sections and they are missing or ungrounded, surface the defect rather than inferring missing numbers.
When the planner template is in use, read `engineering_plan.md` as a sectioned contract with named parts: `## 1. Solution Overview`, `## 2. Parts List`, `## 3. Assembly Strategy`, `## 4. Assumption Register`, `## 5. Detailed Calculations`, `## 6. Critical Constraints / Operating Envelope`, `## 7. Cost & Weight Budget`, and `## 8. Risk Assessment`. The `Detailed Calculations` section is where the binding math lives, and `Risk Assessment` is where known failure modes and mitigations should be documented.
If the geometry or physics derivation is hand-wavy instead of formula-backed, stop and treat that as a plan defect. In practice, handoffs that cannot derive the payload trajectory, contact timing, or clearance math rigorously are not reliable enough to implement.
If `payload_trajectory_definition.yaml` is present, treat it as the engineer-owned motion envelope for the implementation pass: keep the waypoint geometry, contact windows, and terminal proof aligned with the coarse forecast, and make any timing or speed math in `engineering_plan.md` use the exact same anchors rather than a hand-waved estimate.

Then load specialist knowledge only as needed:

- [render-evidence](../render-evidence/SKILL.md) when the task needs preview generation, media inspection, bundle selection, or point-pick queries
- [runtime-script-contract](../runtime-script-contract/SKILL.md)
- [build123d-cad-drafting-skill](../build123d-cad-drafting-skill/SKILL.md)
- [mechanical-engineering](../mechanical-engineering/SKILL.md)
- [manufacturing-knowledge](../manufacturing-knowledge/SKILL.md)
- [specs/architecture/agents/agent-artifacts/README.md](../../../specs/architecture/agents/agent-artifacts/README.md) when you need file-level acceptance criteria for `solution_script.py`, `assembly_definition.yaml`, validation, simulation, `scene.json`, `payload_trajectory_definition.yaml`, `plan_refusal.md`, or render evidence.
- [solution archetypes](references/solution_archetypes.md) after the likely mechanism family is known
- [failure modes](references/failure_modes.md) when debugging or interpreting reviewer feedback

## Source Hierarchy

When files disagree, prefer the strictest current contract in this order:

1. The approved handoff artifacts for the current revision.
2. The benchmark-owned read-only context.
3. The engineer-owned implementation and pricing files.
4. The runtime contracts and specialist skills.

Do not invent fallback behavior to bridge contradictions. If the handoff is inconsistent, surface it.

## Operating Loop

01. Reconstruct the objective, objective zones, runtime jitter, attachment policy, and budget caps.
02. Identify the mechanism family before drafting geometry.
03. Load only the specialist skills that materially affect the design.
04. Draft the smallest physically credible solution that can survive the declared runtime variation.
05. Keep `solution_script.py` import-safe and bind the final object as `result`.
06. Run a cheap syntax/import check, then a real validation probe, then simulation.
07. Inspect render or video evidence as soon as motion is uncertain. When the question depends on bundle identity or pixel-to-world mapping, use `list_render_bundles()`, `query_render_bundle()`, or `pick_preview_pixel()` against the exact bundle before spending extra geometry effort.
08. Fix the narrowest failure mode and repeat.
09. Submit for review only when the latest revision is actually ready.
10. Anchor any binding numeric claim to the tightened `engineering_plan.md` proof structure; do not implement against prose-only assumptions when `ASSUMP-*` and `CALC-*` scaffolding is expected.

## Design Rules

01. Prefer passive solutions first.
02. Add motion only when the task truly needs it.
03. Every non-static DOF must map to a real mechanism, not a convenience.
04. Keep the motion contract explicit if the design uses motors, sliders, latches, or other actuated elements.
05. Keep benchmark-owned fixtures read-only and never reassign their ownership or pricing.
06. Keep planner-authored evidence grounded in the approved inventory. The labels and repeated quantities in `engineering_plan.md`, `assembly_definition.yaml`, and that script must match exactly; missing, extra, or relabeled items are plan defects, not implementation freedom.
07. Keep top-level authored labels unique and avoid reserved names such as `environment` and `zone_...`.
08. Place parts with `Location(...)` or equivalent explicit placement.
09. Keep imported components intact when provenance or exact part identity matters.
10. Keep specialist subsystems separate from mechanical guessing; only load specialist logic when the handoff explicitly demands it.
11. Treat cost, weight, and manufacturability as design constraints, not afterthoughts.
12. When multiple viable implementations satisfy the handoff, prefer the more stable, cheaper, simpler, and more manufacturable one.
13. When the approved handoff uses the engineering planner template, keep every declared inventory label grounded by an exact identifier mention in `engineering_plan.md`, and preserve planner-authored assumptions, calculations, operating-envelope limits, and collision-validated layout geometry without renaming, resizing, or re-spacing them.
14. If the motion math and the precise path disagree, repair the source handoff first; do not "prove" a different path by changing only the implementation.
15. Never use exploded views or the word `exploded` in `solution_script.py`.
16. Static payload proof does not imply runtime success. Treat the simulation monitor as an independent fail-closed gate that can still reject anchor drift, impossible first-contact ordering, or unreachable terminal goal proof even when the file-level trajectory contract parses cleanly.

## Retry Discipline

This role should behave like a high-confidence solver, not a wandering explorer.

- Retries are allowed and expected.
- Keep retries narrow: use new evidence, a clearer diagnosis, or reviewer feedback to justify the next attempt.
- Change one dimension at a time when debugging: geometry, placement, mechanism family, process/material choice, or contract.
- Keep one active hypothesis at a time. If a targeted fix does not change the measured failure mode, record that and pivot instead of layering unrelated edits.
- Preserve working substructures instead of rebuilding the entire model after every failure.
- Use the first simulation or review failure to identify the dominant failure class, then repair that class directly.
- For passive transfer tasks, check first contact height at the spawn point before iterating on capture details; if the object never reaches the support path, lower or reshape the first contact surface instead of tuning the pocket.
- Spend one quick pass on the handoff files, then start drafting.
- Avoid unrelated repo spelunking after the objective is clear.
- Verify against the real validation/simulation/integration gates, not unit-test substitutes or mocked stand-ins.
- If a failure repeats after one targeted fix, treat that as evidence that the current assumption or mechanism family is wrong.
- If the planner handoff is missing exact inventory grounding or the required proof sections for a binding numeric claim, stop and surface the handoff defect instead of compensating inside `solution_script.py`.

## Evidence And Review

- Validation success is necessary but not sufficient.
- Simulation success is necessary but not sufficient.
- A passing validator does not excuse skipping the simulation video or frame evidence. Use the first dynamic result to confirm direction, capture, and stability.
- If `render_cad(...)` evidence exists for the current revision, inspect the corresponding render bundle before finishing.
- If render history matters, use `list_render_bundles()` and `query_render_bundle()` to select the exact bundle snapshot instead of assuming the newest visible render is the right one.
- If a simulation bundle exposes frame/object slices, inspect the sampled frame-indexed `objects.parquet` pose-history sidecar rather than treating `frames.jsonl` as pose history.
- If a question depends on screen-space picking, use `pick_preview_pixel()` or `pick_preview_pixels()` against that bundle-local snapshot before changing geometry.
- After any significant blocker or repeated failure on the same issue, inspect the current render or simulation evidence before the next geometry change. If the same issue has failed more than three times in a row, keep inspecting render evidence on every subsequent retry until the blocker changes; use `../render-evidence/SKILL.md` as the visual-inspection playbook.
- If render images exist for the current revision, inspect them with `inspect_media(...)` before finishing.
- If the solution has moving behavior and simulation video exists, inspect the dynamic evidence before approval.
- Treat `validation_results.json`, `simulation_result.json`, and render manifests as evidence inputs, not as substitutes for reasoning.
- When review feedback arrives, fix only valid checklist items and keep passing items stable.

### Sandbox simulation failure handling

When probing `simulate_engineering(result)` from the Codex sandbox, the local simulation call may fail with infrastructure errors that are **not** geometry bugs. Recognize these patterns:

- `Operation not permitted` from MuJoCo/EGL or GPU render paths
- `httpx.ConnectError` to worker-light/worker-heavy endpoints
- Sandbox-sealed `Simulation error` that traces back to display/GPU/ EGL init failures
- Repeated identical infra failures after one targeted retry with no geometry change

When you observe one of these patterns:

1. **Do not** treat this as a geometry or mechanism problem. The failure is a sandbox runtime limitation, not a design flaw.
2. **Do not** investigate GL backend types, EGL init paths, or worker-light connectivity — these are infra configuration issues you cannot fix from the sandbox.
3. If `validate_engineering(result)` passes, **proceed to call `submit_solution_for_review(result)` immediately**. The eval runner will execute simulation through the real heavy-worker path outside the sandbox.
4. Record the sandbox infra failure in `journal.md` with the exact error message and classify it as a sandbox limitation.
5. Do not loop on further simulation retries — the infra barrier will not be resolved by geometry edits or backend investigations.
6. If validation also fails, fix the validated geometry first, then call `submit_solution_for_review(result)` even if local simulation still hits the same sandbox wall.

**After successful submission, STOP WORKING.** Do not continue to iterate on geometry, read additional files, or make further edits. The submission is complete and the eval runner will handle the rest. Continuing to work wastes tokens and may cause the run to exceed time-limits.

When local simulation completes successfully, inspect the result and proceed normally through the evidence and review workflow.

<!--FIXME: well, this is a bug though.-->

## Debugging Rules

1. Geometry or placement failure: adjust shape, clearance, orientation, or placement first.
2. Contract or schema failure: fix file ownership, labels, metadata, or imports first.
3. Manufacturability failure: fix process choice, stock assumptions, wall thickness, access, or tool reach first.
4. Cost or weight failure: simplify the mechanism or change the part family before inventing a workaround.
5. Robustness failure: widen tolerances to runtime jitter and remove exact-seed dependence.
6. Directional motion failure: verify slope sign, handedness, and capture path from the actual simulation media before changing more geometry. Also check whether the preview is a front or rear view: preview yaw is clockwise from front, so rear views naturally swap left/right on screen and are not automatically an X-axis mirror.
7. Reviewer failure: resolve the valid checklist items directly and ignore non-applicable demands.
8. Render-history or point-pick failure: identify the exact bundle first, then inspect or query that bundle-local snapshot; do not infer coordinates from stale filenames or the latest artifact by default.

If the same blocker persists after one targeted fix, record it in `journal.md` and stop widening the search.

## Refusal Path

Refuse only when the handoff is genuinely infeasible or self-contradictory.

- Write `plan_refusal.md` with concrete evidence.
- If the planner handoff is not exact-grounded or the drafting scripts drift from the inventory, surface the defect instead of compensating in `solution_script.py`.
- If `engineering_plan.md` is missing required proof sections or calculation anchors for the engineering plan, write `plan_refusal.md` with the concrete gap rather than filling in the missing assumptions yourself.
- If the plan's geometry or physics math is not rigorously derived, treat that as a handoff defect and refuse to compensate inside `solution_script.py`.
- Keep the refusal specific to the blocked plan.
- Do not silently pivot to an unrelated solution.

## Extending This Skill

Use the references as the long-term memory for this role.

- Add recurring mechanism families, layout patterns, and winning strategies to `references/solution_archetypes.md`.
- Add recurring blockers, diagnostics, and repair patterns to `references/failure_modes.md`.
- If a pattern needs more detail than this file should carry, move it into a reference instead of growing the prompt body indefinitely.
