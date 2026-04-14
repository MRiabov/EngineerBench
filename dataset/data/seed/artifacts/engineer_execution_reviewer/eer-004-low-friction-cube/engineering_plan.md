# Engineering Plan

## 1. Solution Overview

Use a passive low-angle chute with tall guide walls and a shaped bypass around the central forbid block to move the low-friction cube into the goal zone. The geometry avoids relying on friction and instead constrains the cube with continuous walls and gentle transitions.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| slide_base | 620 x 140 x 10 | aluminum_6061 | Freestanding base for the low-friction guide path |
| entry_box | 160 x 120 x 38 | hdpe | Wide entry pocket that catches the jittered cube without rebound |
| guide_wall_left | 420 x 18 x 42 | hdpe | Left continuous wall guiding the cube around the blocker |
| guide_wall_right | 390 x 18 x 42 | hdpe | Right continuous wall shaping the bypass path |
| blocker_bypass_panel | 200 x 18 x 65 | hdpe | Panel that keeps the cube from sliding into the central forbid block |
| goal_pocket | 110 x 90 x 32 | hdpe | Final pocket settling the cube in the goal zone |

**Estimated Total Weight**: 870 g
**Estimated Total Cost**: $39.50

## 3. Assembly Strategy

1. Mount `entry_box` on `slide_base` so the jittered cube is captured before it reaches the routed section.
2. Mount the two guide walls and `blocker_bypass_panel` to create a smooth, continuous path around the seeded forbid zone.
3. Mount `goal_pocket` overlapping the seeded goal zone so the cube cannot skate through the target.

## 4. Cost & Weight Budget

| Item | Weight (g) | Cost ($) |
| -- | -- | -- |
| slide_base | 390 | 14.5 |
| entry_box | 24 | 5.0 |
| guide_wall_left | 18 | 5.75 |
| guide_wall_right | 17 | 5.25 |
| blocker_bypass_panel | 16 | 4.5 |
| goal_pocket | 19 | 4.5 |
| **TOTAL** | **484** | **39.5** |

**Budget Margin**: 21% remaining versus the planner target.

## 5. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Cube slides too fast and clips the blocker | Medium | High | Keep the routed path continuous and use a tall bypass panel at the critical corner |
| Cube rebounds out of the goal under low friction | Medium | Medium | Use a closed goal pocket instead of an open tray |
| Entry jitter sends the cube into a wall edge | Low | Medium | Use a wide entry box before the chute narrows |
