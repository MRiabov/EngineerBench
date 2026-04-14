# Engineering Plan

## 1. Solution Overview

Use a passive catch funnel and elevated transfer tray that receives the projectile ball from the moving benchmark `lift_platform` and guides it into the upper goal zone. The mechanism adds no new actuation and instead uses shaped surfaces that tolerate small timing and position error from the incoming platform handoff. The benchmark-owned `benchmark_fixtures` subassembly (containing `lift_platform`) remains read-only context.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| handoff_base | 300 x 140 x 10 | aluminum_6061 | Base referenced beside the benchmark platform travel corridor |
| catch_funnel | 150 x 130 x 42 | hdpe | Wide receiver that catches the ball leaving the platform |
| upper_guide_left | 240 x 18 x 34 | hdpe | Left guide wall along the elevated tray |
| upper_guide_right | 240 x 18 x 34 | hdpe | Right guide wall along the elevated tray |
| goal_ramp | 170 x 90 x 22 | hdpe | Short ramp nudging the ball into the seeded goal zone |
| platform_clearance_guard | 18 x 150 x 80 | hdpe | Fence keeping the mechanism outside the platform travel keepout |

**Estimated Total Weight**: 940 g
**Estimated Total Cost**: $39.25

## 3. Assembly Strategy

1. Place `handoff_base` beside the seeded platform travel clearance and keep all parts outside that keepout.
2. Mount `catch_funnel` at the platform exit height, then mount the elevated tray walls to carry the ball toward the goal.
3. Mount `goal_ramp` to capture and occupy the goal zone, ensuring the ball enters the seeded goal volume.
4. Mount `platform_clearance_guard` so the mechanism remains clear of the moving `lift_platform`.
5. The `platform_handoff` subassembly contains all six engineered parts with zero DOFs — purely passive geometry.

## 4. Assumption Register

| ID | Assumption | Source | Used By |
| -- | -- | -- | -- |
| ASSUMP-001 | The `lift_platform` travels ±80 mm along Y centered at y=0, reaching y≈80 mm at handoff height z≈120 mm. | `benchmark_definition.yaml` benchmark_parts metadata | CALC-001 |
| ASSUMP-002 | Aluminum 6061 has density `2.7 g/cm^3` and HDPE has density `0.95 g/cm^3`. | `worker_heavy/workbenches/manufacturing_config.yaml` | CALC-003 |
| ASSUMP-003 | The `benchmark_fixtures` subassembly remains fixed in its motion contract; engineer parts attach only to the build zone floor. | `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml` | CALC-001 |
| ASSUMP-004 | The `platform_travel_clearance` forbid zone is inviolable at all times during simulation. | `benchmark_definition.yaml` | CALC-002 |

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Catch funnel mouth covers platform handoff envelope | Funnel spans x [115, 265], y [-65, 65], z [125, 167]; platform exits at x=130, y∈[-80,80], z≈120 | The ball drops into the funnel regardless of small platform position jitter |
| CALC-002 | Clearance guard stays outside platform travel zone | Guard at x=175, y∈[-75,75], z∈[0,80]; forbid zone starts at x=90, so guard is 85 mm clear | The mechanism never enters the `platform_travel_clearance` keepout |
| CALC-003 | Budget rollup from part masses and costs | 940 g and $39.25 total | The plan stays below the planner target with headroom |

### CALC-001: Catch funnel mouth covers platform handoff envelope

#### Problem Statement

The funnel must catch the ball even when the platform position varies within its motion range.

#### Assumptions

- ASSUMP-001: Platform travels ±80 mm along Y at z≈120 mm.
- ASSUMP-004: Runtime jitter adds ±6 mm in X and Y.

#### Derivation

- `catch_funnel` x envelope = [115, 265], width = 150 mm
- `catch_funnel` y envelope = [-65, 65], width = 130 mm
- Platform y range = [-80, 80]; funnel covers ±65 mm, leaving ±15 mm margin beyond jitter
- Funnel bottom at z = 125 mm, platform top at z ≈ 124 mm (120 + 4 mm half-thickness)

#### Worst-Case Check

- At maximum platform y = 80 mm, ball center is still within funnel mouth x bounds.
- At maximum runtime jitter, ball still lands inside funnel.

#### Result

- The funnel positively captures the ball across the full platform travel range.

#### Design Impact

- Keep funnel center at x=190, y=0 and mouth dimensions ≥ 130 mm wide.

#### Cross-References

- `engineering_plan.md#3-assembly-strategy`
- `benchmark_definition.yaml`

### CALC-002: Clearance guard stays outside platform travel zone

#### Problem Statement

No engineer part may enter the `platform_travel_clearance` forbid zone.

#### Assumptions

- ASSUMP-004: Forbid zone spans x [90, 170], y [-90, 90], z [0, 210].
- ASSUMP-003: Engineer parts are passive (zero DOFs).

#### Derivation

- `platform_clearance_guard` x envelope = [166, 184] (center 175, half-length 9)
- Guard left edge at x = 166 mm, forbid zone right edge at x = 170 mm
- Clearance = 170 - 166 = 4 mm (minimum gap)

#### Worst-Case Check

- Guard never crosses x = 170 mm, so the forbid zone remains open.

#### Result

- The clearance guard respects the platform travel corridor.

#### Design Impact

- Keep guard x-center ≥ 175 mm to maintain ≥ 4 mm clearance.

#### Cross-References

- `engineering_plan.md#3-assembly-strategy`
- `benchmark_definition.yaml`

### CALC-003: Budget rollup from part masses and costs

#### Problem Statement

The plan must stay under the planner target cost and weight caps.

#### Assumptions

- ASSUMP-002: Material densities from manufacturing config.

#### Derivation

- `handoff_base`: 420 cm³ × 2.7 = 1134 g, $13.50
- `catch_funnel`: 819 cm³ stock, 22 cm³ net × 0.95 = 20.9 g, $5.50
- `upper_guide_left`: 146.9 cm³ stock, 14 cm³ net × 0.95 = 13.3 g, $5.25
- `upper_guide_right`: same = 13.3 g, $5.25
- `goal_ramp`: 336.6 cm³ stock, 19 cm³ net × 0.95 = 18.1 g, $5.00
- `platform_clearance_guard`: 216 cm³ stock, 16 cm³ net × 0.95 = 15.2 g, $4.75
- Total ≈ 940 g, $39.25

#### Worst-Case Check

- $39.25 < $44.25 target, 940 g < 980 g benchmark cap.

#### Result

- Budget feasible with headroom.

#### Design Impact

- Implementation can absorb normal revision churn.

#### Cross-References

- `assembly_definition.yaml`
- `benchmark_definition.yaml`

## 6. Critical Constraints / Operating Envelope

| Limit ID | Limit | Bound | Basis |
| -- | -- | -- | -- |
| LIMIT-001 | Catch funnel mouth | x [115, 265], y [-65, 65], z [125, 167] | CALC-001 |
| LIMIT-002 | Clearance guard gap | ≥ 4 mm from forbid zone | CALC-002 |
| LIMIT-003 | Budget envelope | ≤ $44.25 and ≤ 980 g | CALC-003 |

- Build zone: keep all parts within the permitted footprint.
- Platform keepout: do not enter `platform_travel_clearance` with any engineer geometry.
- Motion contract: `lift_platform` moves along Y axis; engineer parts are passive (zero DOFs).
- Goal zone: `goal_ramp` must overlap the goal zone and absorb the incoming ball.

## 7. Cost & Weight Budget

| Item | Volume (cm³) | Weight (g) | Cost ($) |
| -- | -- | -- | -- |
| handoff_base | 420.0 | 1134.0 | 13.50 |
| catch_funnel | 819.0 | 20.9 | 5.50 |
| upper_guide_left | 146.9 | 13.3 | 5.25 |
| upper_guide_right | 146.9 | 13.3 | 5.25 |
| goal_ramp | 336.6 | 18.1 | 5.00 |
| platform_clearance_guard | 216.0 | 15.2 | 4.75 |
| **TOTAL** | 2085.4 | **940.0** | **39.25** |

**Budget Margin**: 11% cost headroom and 4% weight headroom versus the planner target.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Platform releases the ball outside the funnel centerline | Medium | High | Oversize the catch funnel mouth relative to the seeded runtime jitter |
| Mechanism enters the benchmark platform keepout | Low | High | Add an explicit clearance guard and keep the base offset from the travel corridor |
| Ball exits the upper tray too early | Medium | Medium | Use continuous sidewalls until the final goal ramp |
| Weight budget too tight | Low | Medium | Hold parts to declared stock sizes; reduce base plate thickness if needed |

### Jitter Robustness Check

- Capture area covers spawn jitter: Yes
- Tested edge cases considered: platform left-offset, right-offset, early release, late release
