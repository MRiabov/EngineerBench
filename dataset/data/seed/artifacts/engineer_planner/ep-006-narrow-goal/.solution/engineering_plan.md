# Engineering Plan

## 1. Solution Overview

- **Core Mechanism**: A bridge deck spans the gap between the left start deck
  and the right goal deck, creating a continuous passive path for the sphere.
- **Key Principle**: The span preserves momentum and prevents the sphere from
  dropping into the central void.
- **Robustness Strategy**: Wide contact surfaces, symmetric supports, and a
  small stop lip at the exit keep the solution stable across the declared spawn
  jitter.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| bridge_deck | 64 × 8 × 4 | aluminum_6061 | Main span that carries the sphere across the gap |
| left_support | 8 × 12 × 12 | aluminum_6061 | Anchors the left end of the span |
| right_support | 8 × 12 × 12 | aluminum_6061 | Anchors the right end of the span |
| stop_lip | 4 × 8 × 2 | aluminum_6061 | Keeps the sphere from overshooting the right deck |

**Estimated Total Weight**: 11.92 g
**Estimated Total Cost**: $14.00

## 3. Assembly Strategy

1. Center the `bridge_deck` across the gap so its span runs from the left deck
   to the right deck.
2. Place `left_support` and `right_support` under the bridge deck edges to give
   the span a stable passive support layout.
3. Add `stop_lip` near the right end of the span, aligned with the capture
   direction into `right_goal_deck`.
4. Verify every part remains inside the build zone and keeps the central void
   clear.

## 4. Assumption Register

| ID | Assumption | Source | Used By |
| -- | -- | -- | -- |
| ASSUMP-001 | ... | ... | CALC-001 |

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | ... | ... | ... |

### CALC-001: Example calculation

#### Problem Statement

...

#### Assumptions

- `ASSUMP-001`: ...

#### Derivation

- ...

#### Worst-Case Check

- ...

#### Result

- ...

#### Design Impact

- ...

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
- Tested edge cases considered: minimum radius, maximum radius, and all four
  corners of the runtime spawn jitter envelope
