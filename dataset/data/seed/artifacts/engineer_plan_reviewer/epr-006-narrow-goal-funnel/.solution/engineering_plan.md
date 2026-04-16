# Engineering Plan

## 1. Solution Overview

Use a long precision funnel that captures the projectile ball over a wide upstream area and narrows into a tight throat aligned with the narrow goal zone. The mechanism stays passive and relies on careful funnel geometry instead of actuation.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| funnel_base | 720 x 150 x 10 | aluminum_6061 | Stable base under the long guidance funnel |
| wide_entry | 170 x 150 x 38 | hdpe | Broad capture section covering the seeded jitter envelope |
| taper_left | 470 x 18 x 34 | hdpe | Left narrowing wall of the precision funnel |
| taper_right | 470 x 18 x 34 | hdpe | Right narrowing wall of the precision funnel |
| throat_insert | 120 x 30 x 26 | hdpe | Final precision throat aligned to the goal width |
| goal_pocket | 90 x 55 x 28 | hdpe | Final pocket overlapping the narrow goal zone |

**Estimated Total Weight**: 1010 g
**Estimated Total Cost**: $46.25

## 3. Assembly Strategy

1. Mount `wide_entry` on `funnel_base` so the mouth covers the seeded spawn jitter before any narrowing begins.
2. Mount `taper_left` and `taper_right` on a long taper that gradually reduces the path width to the seeded narrow-goal throat.
3. Mount `throat_insert` and `goal_pocket` precisely on the goal centerline so the ball cannot slip past the narrow target.

## 4. Cost & Weight Budget

| Item | Weight (g) | Cost ($) |
| -- | -- | -- |
| funnel_base | 430 | 15.5 |
| wide_entry | 29 | 5.25 |
| taper_left | 19 | 6.5 |
| taper_right | 19 | 6.5 |
| throat_insert | 8 | 4.0 |
| goal_pocket | 14 | 8.5 |
| **TOTAL** | **519** | **46.25** |

**Budget Margin**: 17% remaining versus the planner target.

## 5. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Ball clips the funnel throat under jitter | Medium | High | Use a long gradual taper instead of a sudden constriction |
| Goal pocket sits off-center from the narrow target | Low | High | Reference the final pocket to the goal-zone centerline and throat insert datum |
| Ball rebounds out of the narrow goal after entry | Medium | Medium | Use a closed pocket at the end of the precision throat |
