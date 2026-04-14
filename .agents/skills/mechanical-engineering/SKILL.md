---
name: mechanical-engineering
description: Mechanical mechanism design, friction-aware passive transfer, and simulation guidance for Problemologist. Use this when solving or reviewing passive-transfer mechanisms, realistic constraints/DOFs, manufacturing-config material coefficients, or when a benchmark/solution needs concrete mechanical design patterns instead of prompt-specific hints.
---

# Mechanical Engineering

Use this skill as a router. Keep the main prompt lean and load only the reference that matches the current problem.

## When To Read Which Reference

- `references/mechanism_patterns.md`
  Use for mechanism synthesis, passive/gravity transfer, realistic motion paths, and minimal-DOF decisions.
- `references/optimization.md`
  Use when a design already works and you are refining cost, weight, or safety factor.
- `references/friction_and_manufacturing_config.md`
  Use for material friction coefficients, incline threshold checks, and workspace manufacturing-config lookups.
  Use when the mechanism includes imported components, motors, or benchmark fixtures that must preserve part identity, provenance, or ownership.

## Core Rules

1. Make the transport mechanism explicit.
   If the object must move laterally, roll, slide, funnel, deflect, or stay captured, model the actual surfaces or components that do that work. Spawn pedestals and containment walls are not enough.
2. Prefer the simplest physically credible mechanism family.
   Start with passive gravity transfer before adding motors, joints, or extra DOFs. Add motion only when the task truly requires it.
3. Every non-static DOF must map to a real mechanism.
   Bearings, sliders, motors, fasteners, or another allowed physical constraint must justify the motion. Convenience DOFs are review failures.
4. Keep manufacturing and physics aligned.
   Benchmark-owned fixtures are not priced as manufactured parts, but engineer-authored parts still need realistic geometry, materials, and attachment logic.
5. Never guess a size.
   Derive every length, thickness, gap, capture width, wall height, clearance, and support offset from declared source dimensions, measured geometry, or manufacturing constants. If the required value is missing, stop and surface the missing input instead of inventing a plausible number.
6. When the mechanism is joint-driven, place parts from joint axes, contact surfaces, and datum offsets instead of arbitrary world coordinates.
7. Before relying on a passive slide or chute, compare the slope to the actual friction coefficient in `manufacturing_config.yaml`.
   If `tan(theta)` does not beat the relevant `friction_coef`, treat the mechanism as stalled until geometry or family changes.
8. If the mechanism uses imported components, keep the concrete part contract separate from the motion contract.
   Do not treat motors, fixtures, or other catalog-backed parts as generic geometry.
9. Before tuning capture pockets or side rails, verify that the object actually reaches the support surface at the declared spawn height.
   If the object never makes first contact, lower or reshape the first support surface before changing capture geometry.

## Passive-Transfer Debugging

- Start from the dynamic requirement, not the static shape. The real success condition is "ball stays captured and reaches the goal," so judge the first design pass against motion, not just valid geometry.
- Separate validation from effectiveness. Passing geometry validation is necessary, but it is not evidence of a working mechanism. Stop treating validation success as progress once simulation is still failing.
- Inspect the first simulation frames or video as soon as direction is uncertain.
- When the motion is reversed, verify slope sign, handedness, and datum orientation before changing capture width or seam cleanup.
- When the object never gets onto the intended path, check first contact height at the spawn point before tuning pocket geometry.
- For friction-sensitive passive transfer, use the workspace manufacturing config rather than a guessed coefficient. If the object stalls, first check `tan(theta)` against `friction_coef`, then widen capture or change the mechanism family.
- Treat seed hints for direction, x-position, and capture span as hard constraints.
- Change one variable at a time; validation success is necessary, but it is not proof that the mechanism works.

## Workflow

1. Identify the required mechanism family.
2. Read the matching reference file.
3. Build the simplest geometry that makes the required motion physically inevitable.
4. Validate or simulate.
5. Refine only after the base mechanism exists and is physically coherent.

## Notes

- Do not move long mechanism heuristics back into `config/prompts.yaml`; keep them here or in references.
- Keep benchmark-specific solution tricks in reference files so they can be updated independently of the prompt contract.
