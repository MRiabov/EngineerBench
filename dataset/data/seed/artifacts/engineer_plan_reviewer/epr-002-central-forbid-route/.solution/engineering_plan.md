# Engineering Plan

## 1. Solution Overview

Use a passive offset rail path that routes the projectile ball around the seeded central blocker and into the far goal zone. The mechanism widens the capture area near spawn, steers the ball around the blocker on the positive-Y side, and settles it into a downstream goal tray.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| route_base | 760 x 150 x 10 | aluminum_6061 | Freestanding base plate spanning the permitted route corridor |
| entry_catcher | 170 x 140 x 35 | hdpe | Capture funnel that absorbs spawn jitter before the routing turn |
| outer_rail | 560 x 18 x 28 | hdpe | Outside guide rail along the routed path |
| inner_rail | 520 x 18 x 28 | hdpe | Inside guide rail that keeps the ball away from the central blocker |
| blocker_skirt | 210 x 20 x 60 | hdpe | Clearance wall keeping the ball from clipping the blocker corner |
| goal_tray | 160 x 120 x 35 | hdpe | Terminal tray overlapping the goal zone |

**Estimated Total Weight**: 1120 g
**Estimated Total Cost**: $48.50

## 3. Assembly Strategy

1. Place `route_base` fully inside the seeded build zone and keep its mid-span clear of the blocker keepout.
2. Mount `entry_catcher` near the spawn side, then mount `outer_rail` and `inner_rail` so the path bends around the blocker on one side.
3. Mount `blocker_skirt` beside the routed turn and terminate the path inside `goal_tray` so the ball settles inside the goal zone.

## 4. Cost & Weight Budget

| Item | Weight (g) | Cost ($) |
| -- | -- | -- |
| route_base | 470 | 16.0 |
| entry_catcher | 28 | 5.5 |
| outer_rail | 23 | 6.25 |
| inner_rail | 22 | 6.0 |
| blocker_skirt | 18 | 5.0 |
| goal_tray | 22 | 9.75 |
| **TOTAL** | **583** | **48.5** |

**Budget Margin**: 25% remaining versus the planner target.

## 5. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Ball clips the blocker corner under jitter | Medium | High | Use a dedicated blocker skirt and keep the routed bend outside the forbid volume |
| Ball exits the outer rail on the long bend | Medium | Medium | Increase rail height through the turn and keep the bend radius shallow |
| Goal tray receives the ball too fast | Low | Medium | Drop the tray slightly below the rail exit to absorb speed |
