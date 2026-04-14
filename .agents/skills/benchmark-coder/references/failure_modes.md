# Failure Modes

## Table of Contents

1. [Geometry and placement](#geometry-and-placement)
2. [Contract and schema](#contract-and-schema)
3. [Simulation and robustness](#simulation-and-robustness)
4. [Evidence and review](#evidence-and-review)
5. [Refusal and handoff](#refusal-and-handoff)

## Geometry and placement

Signals:

- Intersections
- Out-of-bounds parts
- A path that looks correct in sketch space but not in final placement
- Missing continuity between adjacent surfaces

Likely causes:

- Wrong datum
- Wrong rotation
- Gaps between handoff surfaces
- The final envelope was not checked after placement

First fix:

- Inspect the final placed geometry and fix the narrowest placement error.

## Contract and schema

Signals:

- Missing or malformed handoff files
- Wrong top-level labels
- `result` not bound correctly
- Import-time side effects
- Edited benchmark-owned files from the benchmark coder side
- `benchmark_plan.md` is missing an exact identifier mention for a declared label or selected COTS `part_id`
- Planner-authored evidence scripts change labels, quantities, or COTS identities

Likely causes:

- The script contract was not kept import-safe
- Ownership boundaries were ignored
- A fallback was invented instead of fixing the source
- The planner handoff was not exact-grounded
- The planner scripts drifted from the approved inventory

First fix:

- Restore the file contract and ownership boundaries before changing the design.
- Stop and surface the handoff defect; do not compensate in `benchmark_script.py`.

## Simulation and robustness

Signals:

- The benchmark only works on the nominal seed
- Runtime jitter breaks the scene
- The fixture motion is unstable or reversed
- Static validation passes, but simulation fails

Likely causes:

- Capture margins are too small
- Contact geometry is too delicate
- The motion stack assumes exact timing
- The design has unnecessary degrees of freedom

First fix:

- Inspect the first simulation frame or video, verify the real motion direction, and change only the dominant motion determinant.
- Increase tolerance to runtime variation and remove fragile dependency points.

## Evidence and review

Signals:

- Reviewer rejects a benchmark that looked plausible at a glance
- Render evidence was ignored
- Text summaries contradicted the actual media
- Mixed reviewer feedback was treated as a blanket rejection or blanket approval

Likely causes:

- The wrong evidence was used
- Media inspection was skipped
- Valid reviewer items were mixed with non-applicable requests

First fix:

- Inspect the actual media and separate valid checklist items from noise.

## Refusal and handoff

Signals:

- The plan cannot be implemented as written
- The handoff contradicts itself
- Required benchmark-side motion metadata is missing

Likely causes:

- The planner handoff is internally inconsistent
- Required benchmark-owned facts are missing
- The task requires a different benchmark family than the handoff allows

First fix:

- Write `plan_refusal.md` with concrete evidence and stop pretending the plan is salvageable.
