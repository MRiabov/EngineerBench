# Engineering Plan

## 1. Solution Overview

Use a completely freestanding twin-wall chute that receives the projectile ball on the left side and carries it to the right goal zone without drilling, bolting into, or leaning on the environment. Stability comes from a wide aluminum base and low center of mass rather than external attachment.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| freestanding_base | 620 x 180 x 12 | aluminum_6061 | Wide low center-of-mass base keeping the transfer stable without attachment |
| capture_funnel | 160 x 140 x 40 | hdpe | Capture pocket covering the seeded spawn jitter |
| left_wall | 460 x 20 x 32 | hdpe | Left chute wall |
| right_wall | 460 x 20 x 32 | hdpe | Right chute wall |
| exit_tray | 140 x 110 x 35 | hdpe | Goal-side tray settling the ball in the target |
| ballast_block | 180 x 80 x 18 | steel_cold_rolled | Extra mass on the base to prevent tip-over |

**Estimated Total Weight**: 980 g
**Estimated Total Cost**: $42.75

## 3. Assembly Strategy

1. Keep `freestanding_base` centered in the build zone and mount `ballast_block` low on the base to stabilize the mechanism.
2. Mount `capture_funnel`, `left_wall`, and `right_wall` on the base only, with no fasteners or contact into the environment.
3. Terminate the transfer in `exit_tray` overlapping the seeded goal zone so the ball settles without rebounding out.

## 4. Cost & Weight Budget

| Item | Weight (g) | Cost ($) |
| -- | -- | -- |
| freestanding_base | 455 | 15.5 |
| capture_funnel | 27 | 5.0 |
| left_wall | 22 | 5.5 |
| right_wall | 22 | 5.5 |
| exit_tray | 21 | 8.25 |
| ballast_block | 260 | 3.0 |
| **TOTAL** | **807** | **42.75** |

**Budget Margin**: 21% remaining versus the planner target.

## 5. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Freestanding assembly tips under impact | Medium | High | Keep a wide base and add low-mounted ballast |
| Ball escapes due to spawn jitter | Medium | Medium | Use an oversized capture funnel before the chute narrows |
| Hidden environment contact violates the no-drill rule | Low | High | Keep all geometry referenced from the freestanding base and leave explicit clearance to nearby fixtures |
