## 1. Learning Objective

Move a 40 mm steel sphere one meter sideways into the goal zone using only fixed guide geometry and gravity.

## 2. Geometry

- Ground plane.
- Left and right support platforms.
- Containment rails across the transfer span.

## 3. Objectives

- Reach goal zone.
- Stay inside bounds.
- Remain manufacturable and reviewer-ready.

## 4. Randomization

- No runtime randomization beyond the fixed sphere radius_mm and deterministic
  start pose declared in `benchmark_definition.yaml`.

## 5. Implementation Notes

- The benchmark-owned `environment_fixture` stays fixed and is the only
  benchmark part declared in the handoff.
- The static geometry remains the review target; no hidden actuation or moving
  benchmark-side fixtures are implied.
