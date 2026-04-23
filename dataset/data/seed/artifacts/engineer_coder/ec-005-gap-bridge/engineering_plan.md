# Engineering Plan

## 1. Solution Overview

Use a freestanding bridge deck with shallow side fences to move `transfer_cube` from the seeded `left_start_deck` across the `floor_gap` and into the `right_goal_deck` capture zone. The benchmark-owned `bridge_reference_table` and `gap_floor_guard` stay read-only context; the solution uses them only as spatial references while keeping the bridge passive and within the planner budgets.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| base_frame | 560 x 180 x 12 | aluminum_6061 | Freestanding support frame that keeps the bridge aligned without touching the benchmark fixtures |
| bridge_deck | 300 x 95 x 8 | aluminum_6061 | Main transfer surface across the gap |
| left_fence | 300 x 20 x 35 | hdpe | Left-side guide fence that prevents lateral escape |
| right_fence | 300 x 20 x 35 | hdpe | Right-side guide fence that prevents lateral escape |
| landing_pocket | 130 x 110 x 30 | hdpe | Receives the cube at the goal side and damps rebound |

**Estimated Total Weight**: 451 g
**Estimated Total Cost**: $57.50

## 3. Assembly Strategy

1. Place `base_frame` centered in the build zone so the support footprint stays clear of the `floor_gap` keep-out volume and aligned with `left_start_deck`.
2. Mount `bridge_deck` along the x-axis with its span centered over the gap corridor and its far end pointing at `right_goal_deck`.
3. Mount `left_fence` and `right_fence` along the deck edges with enough clearance for the jittered cube to pass without climbing the rails.
4. Position `landing_pocket` so its mouth overlaps the `goal_zone_mm` and captures the cube before it can rebound off the right deck.
5. Keep every part label grounded in `engineering_plan.md`, `todo.md`, and `assembly_definition.yaml`, and keep the benchmark fixtures unchanged.
6. The callouts `1`-`5` track the base frame, bridge deck, left fence, right fence, and landing pocket, respectively.

## 4. Assumption Register

- The bridge remains fully passive; no actuators are needed or allowed.
- The support frame can straddle the gap without touching the forbid zone footprint.
- The landing pocket can overlap the goal zone while staying clear of the right deck rebound path.

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Gap span coverage | `bridge_deck` length of 300 mm bridges the corridor with enough contact area at both ends. | The deck reaches across the gap without relying on unsupported overhang. |
| CALC-002 | Guide coverage | `left_fence` and `right_fence` extend the full deck length, leaving the cube a centered passive path. | The cube stays laterally constrained across jittered arrivals. |
| CALC-003 | Landing capture | `landing_pocket` mouth overlaps the goal zone so the cube settles before rebounding off the deck edge. | The goal-side capture remains stable under bounce. |

## 6. Critical Constraints / Operating Envelope

- Build zone: keep the frame feet and deck footprint inside the benchmark build bounds.
- Gap keepout: no support feet or stiffeners may intrude into `floor_gap`.
- Motion contract: passive only, no added motion or powered components.
- Goal zone: the landing pocket must overlap the goal volume and contain the cube after crossing.
- Budget envelope: maintain the current weight/cost headroom so the planner target remains feasible.

## 7. Cost & Weight Budget

| Item | Volume (cm^3) | Weight (g) | Cost ($) |
| -- | -- | -- | -- |
| base_frame | 121.0 | 326.70 | 19.50 |
| bridge_deck | 22.8 | 61.56 | 11.00 |
| left_fence | 21.0 | 19.95 | 7.00 |
| right_fence | 21.0 | 19.95 | 7.00 |
| landing_pocket | 25.0 | 23.75 | 13.00 |
| **TOTAL** | 210.8 | 451.91 | **57.50** |

**Budget Margin**: 23% cost headroom and 56% weight headroom versus the planner target.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Bridge support intrudes into the forbid zone | Low | High | Keep all frame feet outside the seeded gap AABB and validate the footprint in code |
| Cube yaws and rides over a fence | Medium | High | Keep the fences high enough to resist yaw while preserving top clearance |
| Cube rebounds out of the landing area | Medium | Medium | Use a deeper landing pocket with a short backstop wall inside the goal zone |
| Bridge deck flex reduces consistency | Low | Medium | Keep the deck short and support it from both ends with the aluminum frame |

### Jitter Robustness Check

- Capture area covers spawn jitter: Yes
- Tested edge cases considered: left-offset spawn, right-offset spawn, low-Z spawn, high-Z spawn, shallow-angle entry
