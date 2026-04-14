# Engineering Plan

## 1. Solution Overview

Use a freestanding bridge deck with shallow side fences to carry the seeded cube across the floor gap and settle it into a landing pocket inside the goal zone. The mechanism stays fully passive, spans the gap with a stiff deck, and uses fence geometry rather than friction to keep the cube aligned.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| base_frame | 560 x 180 x 12 | aluminum_6061 | Freestanding support frame that lands on both sides of the gap without touching the forbidden region |
| bridge_deck | 300 x 95 x 8 | aluminum_6061 | Main transfer surface across the gap |
| left_fence | 300 x 20 x 35 | hdpe | Left-side guide fence that prevents lateral escape |
| right_fence | 300 x 20 x 35 | hdpe | Right-side guide fence that prevents lateral escape |
| landing_pocket | 130 x 110 x 30 | hdpe | Receives the cube at the goal side and damps rebound |

**Estimated Total Weight**: 1320 g
**Estimated Total Cost**: $57.50

## 3. Assembly Strategy

1. Place `base_frame` so it straddles the seeded gap but keeps all support feet outside the forbid zone footprint.
2. Mount `bridge_deck` across the frame with a slight downhill bias toward the goal side to keep the cube moving after the gap crossing.
3. Mount `left_fence` and `right_fence` along the deck edges with enough clearance for the cube plus jitter margin.
4. Mount `landing_pocket` so the pocket mouth overlaps the goal-zone volume and captures the cube without a secondary bounce path.

## 4. Cost & Weight Budget

| Item | Volume (cm^3) | Weight (g) | Cost ($) |
| -- | -- | -- | -- |
| base_frame | 121.0 | 326.0 | 19.50 |
| bridge_deck | 22.8 | 61.6 | 11.00 |
| left_fence | 21.0 | 20.2 | 7.00 |
| right_fence | 21.0 | 20.2 | 7.00 |
| landing_pocket | 25.0 | 24.0 | 13.00 |
| **TOTAL** | 210.8 | 451.0 | **57.50** |

**Budget Margin**: 31% remaining versus the planner target.

## 5. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Bridge support intrudes into the forbid zone | Low | High | Keep all frame feet outside the seeded gap AABB and validate the footprint in code |
| Cube yaws and rides over a fence | Medium | High | Keep the fences high enough to resist yaw while preserving top clearance |
| Cube rebounds out of the landing area | Medium | Medium | Use a deeper landing pocket with a short backstop wall inside the goal zone |
| Bridge deck flex reduces consistency | Low | Medium | Keep the deck short and support it from both ends with the aluminum frame |

### Jitter Robustness Check

- Capture area covers spawn jitter: Yes
- Tested edge cases considered: left-offset spawn, right-offset spawn, forward yaw entry, low-energy entry
