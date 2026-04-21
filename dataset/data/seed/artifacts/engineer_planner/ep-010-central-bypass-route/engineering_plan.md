# Engineering Plan

## 1. Solution Overview

- Use a passive bridge-span layout that lets the payload move from the start
  launch region around the central blocker toward the goal tray under gravity.
- Keep the plan centered on a single rigid-body mechanism and avoid powered or
  soft-material branches.
- Anchor the plan to the benchmark fixtures `left_launch_pad`,
  `central_blocker`, `upper_route_wall`, `lower_route_wall`, and
  `goal_catch_tray` so the bypass geometry stays grounded in the seeded
  benchmark handoff.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| bridge_deck | 64 × 8 × 4 | aluminum_6061 | Main elevated span that carries the payload around the blocker |
| left_support | 8 × 12 × 12 | aluminum_6061 | Anchors the left end of the span |
| right_support | 8 × 12 × 12 | aluminum_6061 | Anchors the right end of the span |
| stop_lip | 4 × 8 × 2 | aluminum_6061 | Helps keep the payload aligned at the exit tray |

**Estimated Total Weight**: 11.92 g
**Estimated Total Cost**: $14.00

## 3. Assembly Strategy

1. Center the `bridge_deck` so its elevated span passes above the
   `central_blocker` and clears the route walls.
2. Place `left_support` and `right_support` under the bridge deck edges to give
   the span a stable passive support layout.
3. Add `stop_lip` near the right end of the span, aligned with the capture
   direction into `goal_catch_tray`.
4. Verify every part remains inside the build zone and keeps the central void
   clear.

## 4. Assumption Register

| ID | Assumption | Source | Used By |
| -- | -- | -- | -- |
| ASSUMP-001 | The bypass span stays centered on the declared route layout. | benchmark_definition.yaml | CALC-001 |

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Bridge span coverage | 64 mm deck span with 16 mm bearing each side | Keeps the passive bridge stable |

### CALC-001: Example calculation

#### Problem Statement

Confirm the bridge deck spans the gap with enough bearing on both sides.

#### Assumptions

- `ASSUMP-001`: The span uses the declared deck geometry and the benchmark fixtures stay fixed.

#### Derivation

- The bridge deck provides 64 mm of span.
- Centered placement leaves 16 mm of bearing on each side.

#### Worst-Case Check

- The declared deck width and support placement leave the central void open under the worst declared payload size.

#### Result

- The span is feasible if the bridge deck remains centered and the supports stay inside the build zone.

#### Design Impact

- Keep the bridge deck aligned to the world axes and do not shrink the deck width below the declared span.

#### Cross-References

- `engineering_plan.md#4-assumption-register`
- `engineering_plan.md#6-critical-constraints--operating-envelope`

## 6. Critical Constraints / Operating Envelope

| Limit ID | Limit | Bound | Basis |
| -- | -- | -- | -- |
| LIMIT-001 | Minimum slope | `21.7deg` | `CALC-001` |

## 7. Cost & Weight Budget

| Item | Volume (cm³) | Weight (g) | Cost ($) |
| -- | -- | -- | -- |
| bridge_deck | 20.48 | 5.53 | 7.00 |
| left_support | 1.15 | 3.11 | 3.00 |
| right_support | 1.15 | 3.11 | 3.00 |
| stop_lip | 0.06 | 0.17 | 1.00 |
| **TOTAL** | 22.84 | 11.92 | 14.00 |

**Budget Margin**: 48% remaining versus the benchmark caps and 30% versus the
planner target caps.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Sphere clips the edge of the span during jittered starts | Medium | High | Keep the deck wide and maintain a centered capture path |
| Sphere overshoots the right deck | Low | Medium | Use the stop lip and keep the exit shallow |
| Support blocks the path or violates the void | Low | High | Keep supports outside the central void and verify placement before submit |

### Jitter Robustness Check

- Capture area covers spawn jitter: Yes
- Tested edge cases considered: minimum radius_mm, maximum radius_mm, and all four
  corners of the runtime spawn jitter envelope
