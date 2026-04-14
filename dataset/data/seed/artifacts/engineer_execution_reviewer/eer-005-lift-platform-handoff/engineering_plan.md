# Engineering Plan

## 1. Solution Overview

Use a passive catch funnel and elevated transfer tray that receives the projectile ball from the moving benchmark lift platform and guides it into the upper goal zone. The mechanism adds no new actuation and instead uses shaped surfaces that tolerate small timing and position error from the incoming platform handoff.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| handoff_base | 300 x 140 x 10 | aluminum_6061 | Base referenced beside the benchmark platform travel corridor |
| catch_funnel | 150 x 130 x 42 | hdpe | Wide receiver that catches the ball leaving the platform |
| upper_guide_left | 240 x 18 x 34 | hdpe | Left guide wall along the elevated tray |
| upper_guide_right | 240 x 18 x 34 | hdpe | Right guide wall along the elevated tray |
| goal_ramp | 170 x 90 x 22 | hdpe | Short ramp nudging the ball into the seeded goal zone |
| platform_clearance_guard | 150 x 18 x 80 | hdpe | Fence keeping the mechanism outside the platform travel keepout |

**Estimated Total Weight**: 940 g
**Estimated Total Cost**: $44.25

## 3. Assembly Strategy

1. Place `handoff_base` beside the seeded platform travel clearance and keep all parts outside that keepout.
2. Mount `catch_funnel` at the platform exit height, then mount the elevated tray walls to carry the ball toward the goal.
3. Mount `goal_ramp` and `platform_clearance_guard` so the ball enters the goal zone while the mechanism remains clear of the moving platform.

## 4. Cost & Weight Budget

| Item | Weight (g) | Cost ($) |
| -- | -- | -- |
| handoff_base | 250 | 13.5 |
| catch_funnel | 23 | 5.5 |
| upper_guide_left | 16 | 5.25 |
| upper_guide_right | 16 | 5.25 |
| goal_ramp | 18 | 5.0 |
| platform_clearance_guard | 17 | 4.75 |
| **TOTAL** | **340** | **39.25** |

**Budget Margin**: 24% remaining versus the planner target.

## 5. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Platform releases the ball outside the tray centerline | Medium | High | Oversize the catch funnel mouth relative to the seeded runtime jitter |
| Mechanism enters the benchmark platform keepout | Low | High | Add an explicit clearance guard and keep the base offset from the travel corridor |
| Ball exits the upper tray too early | Medium | Medium | Use continuous sidewalls until the final goal ramp |
