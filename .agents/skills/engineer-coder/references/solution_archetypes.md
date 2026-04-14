# Solution Archetypes

## Table of Contents

1. [How to choose](#how-to-choose)
2. [Passive transfer](#passive-transfer)
3. [Actuated solutions](#actuated-solutions)
4. [Electronics-backed solutions](#electronics-backed-solutions)
5. [Render history and point-pick](#render-history-and-point-pick)
6. [Convergence heuristics](#convergence-heuristics)

## How to choose

Choose the smallest mechanism family that can satisfy the objective under runtime jitter.

- If gravity and geometry are enough, use a passive transfer family.
- If the task needs timing, reset, or sequencing, add only the minimum actuation needed.
- If the handoff explicitly includes electronics, keep the logical circuit and the physical routing consistent.

When in doubt, start with the simplest family that can plausibly solve the problem and only escalate after a concrete failure explains why.

## Passive transfer

Use for drop, redirect, catch, funnel, capture, and guide tasks.

Common forms:

- Ramp
- Chute
- Funnel
- Deflector
- Capture pocket
- Guide rail

Drafting cues:

- Make the transport path continuous.
- Keep support surfaces aligned with the intended motion direction.
- Include enough lateral containment to survive jitter and bounce.
- Avoid tiny ledges or gaps that only work on the nominal seed.
- If the path is mirrored or drains the wrong way, fix handedness, slope sign, or datum orientation before widening capture or adding complexity.
- Verify that the cube actually contacts the support surface at the declared spawn height before tuning anything else.
- If the cube never reaches the path, lower or reshape the first contact surface instead of spending time on pocket details.

Typical failure modes:

- The object leaves the intended path.
- The object bounces out at the handoff.
- The guide is technically valid but too narrow for jitter.
- The path is continuous in concept but not in the actual placed geometry.
- The path is mirrored relative to the intended goal direction.

First response:

- Increase capture margin.
- Remove unsupported gaps.
- Re-check the final placed envelope, not just the sketch.
- Verify the first rendered motion before spending time on cosmetic cleanup.
- Confirm first contact at the spawn point with a quick analytic height check before another simulation pass.

## Actuated solutions

Use when a passive path cannot satisfy the objective.

Common forms:

- Gate
- Pusher
- Latch
- Slider
- Lever
- Cam-driven reset

Drafting cues:

- Declare the motion contract explicitly.
- Minimize DOFs.
- Give each moving part a real physical reason to move.
- Define the stop positions and travel limits clearly.

Typical failure modes:

- A motion axis exists only because it was convenient.
- The control contract is ambiguous.
- The design works only if the actuator is treated like magic.
- The mechanism collides with its own supports or with the benchmark environment.

First response:

- Remove unneeded DOFs.
- Add clear stops and path constraints.
- Reconcile the motion path with the surrounding geometry.

## Electronics-backed solutions

Use only when the approved handoff explicitly requires electronics or the benchmark declares electronics requirements.

Rules:

- Keep the logical circuit and the physical routing consistent.
- Validate the circuit before physics concerns.
- Route wires with clearance and tension in mind.
- Do not invent electronics because a mechanism has a motor.

Typical failure modes:

- The circuit is valid on paper but impossible in the geometry.
- The wire path collides with the mechanism.
- The design silently assumes power, control, or switching behavior that was never declared.

First response:

- Separate netlist issues from routing issues.
- Fix the logical contract first, then the physical path.

## Render history and point-pick

Use when you need to interpret render bundles, drafting packages, or screen-space queries.

Common forms:

- Live scene preview via `render_cad(...)`
- Bundle history selection via `list_render_bundles()`
- Compact bundle slices via `query_render_bundle()`
- Screen-space click-to-world queries via `pick_preview_pixel()` and `pick_preview_pixels()`

Drafting cues:

- Select the exact bundle that matches the revision under test before inspecting media.
- Use `payload_path=True` only when verifying the live payload-path overlay in a render bundle.
- Treat bundle-local history as authoritative; do not infer a world point from image bytes or a stale filename.
- Use batch point-picks when you need to compare several candidate pixels against the same bundle snapshot.

Typical failure modes:

- The latest visible render is not the bundle you meant to inspect.
- A click is interpreted against the wrong scene snapshot.
- A drafting preview is used to answer a live-motion question, or vice versa.

First response:

- Identify the exact bundle, inspect or query that bundle-local snapshot, and only then revise geometry.

## Convergence heuristics

- Prefer the first physically credible geometry over an elaborate speculative one.
- Solve the nominal objective and runtime jitter together.
- Reduce sensitivity before increasing complexity.
- If the approved handoff already pins down the exact geometry, labels, or inventory, copy that contract forward verbatim into `solution_script.py` and spend effort on the build123d translation, not on re-deciding the mechanism.
- If the first simulation shows the object moving away from the goal, treat it as a directionality bug, not a robustness bug.
- If the first simulation shows the object never reaching the support path, treat it as a contact-height bug, not a capture-margin bug.
- If a review or simulation failure recurs, promote the winning pattern into this file so the next run starts from a better prior.
- Keep new patterns here concise enough to reuse, but specific enough to be actionable.
