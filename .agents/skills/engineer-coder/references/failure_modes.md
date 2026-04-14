# Failure Modes

## Table of Contents

1. [Geometry and placement](#geometry-and-placement)
2. [Contract and schema](#contract-and-schema)
3. [Manufacturability and cost](#manufacturability-and-cost)
4. [Simulation and robustness](#simulation-and-robustness)
5. [Evidence and review](#evidence-and-review)
6. [Render history and point-pick](#render-history-and-point-pick)
7. [Refusal and handoff](#refusal-and-handoff)

## Geometry and placement

Signals:

- Intersections
- Out-of-bounds parts
- A path that looks correct in sketch space but not in final placement
- Missing support continuity between adjacent surfaces
- Geometry or physics math is not rigorous enough to support the intended path
- The payload trajectory is only described qualitatively, not derived

Likely causes:

- Wrong datum
- Wrong rotation
- Gaps between handoff surfaces
- The final envelope was not checked after placement
- The planner handoff did not provide a formula-backed trajectory or clearance derivation
- The motion estimate was inferred from prose instead of calculated from the contract

First fix:

- Inspect the final placed geometry and fix the narrowest placement error.
- If the path math is hand-wavy, stop and surface the handoff defect instead of compensating in `solution_script.py`.

## Contract and schema

Signals:

- Missing or malformed handoff files
- Wrong top-level labels
- `result` not bound correctly
- Import-time side effects
- Wrote benchmark-owned files from the engineer side
- `engineering_plan.md` is missing an exact identifier mention for a declared label or selected COTS `part_id`
- `engineering_plan.md` is missing the tightened proof sections for a binding engineering claim, such as the Assumption Register, Detailed Calculations, or Critical Constraints / Operating Envelope
- A numeric claim in `engineering_plan.md` has no `CALC-*` anchor or relies on prose-only assumptions
- Planner-authored evidence scripts change labels, quantities, or COTS identities

Likely causes:

- The script contract was not kept import-safe
- Ownership boundaries were ignored
- A fallback was invented instead of fixing the source
- The planner handoff was not exact-grounded
- The planner handoff did not supply the proof structure needed to justify a binding numeric claim
- The planner script drifted from the approved inventory

First fix:

- Restore the file contract and ownership boundaries before changing the design.
- Stop and surface the handoff defect; do not compensate in `solution_script.py`.
- Treat missing proof sections or calculation anchors as a handoff defect, not a modeling gap.

## Manufacturability and cost

Signals:

- Cost over budget
- Weight over budget
- Unsupported stock assumptions
- Unclear or impossible machining access
- Material choice does not match the process

Likely causes:

- Too many unique parts
- Excessive volume
- Wrong process family
- Geometry that is easy to model but hard to make

First fix:

- Simplify the mechanism or switch to a more realistic process/material combination.

## Simulation and robustness

Signals:

- Goal reached only on the nominal seed
- Jitter-sensitive failure
- Overdependence on a precise start position
- Unstable motion or flakiness
- Static validation passes, but the moving object exits the build zone or goes the wrong way
- A mirrored or reversed transfer path in video despite a plausible static layout
- Static validation passes, the scene looks coherent in preview, but the payload never gets onto the intended support surface
- The first simulation frame shows the object falling through open space or landing below the path before any meaningful transfer begins

Likely causes:

- Capture margins are too small
- Contact geometry is too delicate
- The mechanism assumes exact timing
- The design has unnecessary degrees of freedom
- Slope sign, handedness, or datum orientation is reversed
- The motion stack was tuned with too many coupled changes at once
- The support surface starts above the spawn height, so the object never makes initial contact
- The path was debugged visually instead of checking the actual contact height at the start and handoff points

First fix:

- Inspect the first simulation frame or video, verify the real motion direction, and change only the dominant motion determinant.
- Increase tolerance to runtime variation and remove fragile dependency points.
- Compute the start-contact surface height and the goal-contact surface height before another simulation run.
- If the object never touches the path, lower or reshape the support instead of tuning capture details.

## Evidence and review

Signals:

- Reviewer rejects a plan or implementation that looked plausible at a glance
- Render evidence was ignored
- Text summaries contradicted the actual media
- A mixed review was treated as a blanket rejection or a blanket approval

Likely causes:

- The wrong evidence was used
- Media inspection was skipped
- Valid reviewer items were mixed with non-applicable requests

First fix:

- Inspect the actual media and separate valid checklist items from noise.

## Render history and point-pick

Signals:

- The render looks plausible, but the issue depends on a different revision or bundle.
- Click-to-world or ray-pick output is wrong even though the image looks fine.
- Code keeps using the newest path instead of the bundle for the current revision.
- Scratch and persistent render evidence are conflated.

Likely causes:

- Wrong bundle selected from history.
- Query ran against a different scene snapshot than the media under review.
- A screen-space question is being answered from image bytes or stale filenames.

First fix:

- Use `list_render_bundles()` to select the exact bundle, then `query_render_bundle()` or `pick_preview_pixel()` against that bundle-local snapshot.
- If visual confirmation is needed, inspect the media for that bundle with `inspect_media(...)`.
- Do not change geometry until the bundle identity is confirmed.

## Refusal and handoff

Signals:

- The plan cannot be implemented as written
- The handoff contradicts itself
- Budgets or objective geometry make the task impossible
- The plan relies on missing proof sections or ungrounded numeric claims that the coder cannot safely infer

Likely causes:

- The planner handoff is internally inconsistent
- Required benchmark-owned facts are missing
- The task requires a different mechanism family than the handoff allows
- The engineering plan omitted the proof scaffolding required by the tightened template

First fix:

- Write `plan_refusal.md` with concrete evidence and stop pretending the plan is salvageable.
