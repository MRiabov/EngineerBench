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

**Estimated Total Weight**: 425.4 g
**Estimated Total Cost**: $46.25

## 3. Assembly Strategy

1. Mount `wide_entry` on `funnel_base` so the mouth covers the seeded spawn jitter before any narrowing begins.
2. Mount `taper_left` and `taper_right` on a long taper that gradually reduces the path width to the seeded narrow-goal throat.
3. Mount `throat_insert` and `goal_pocket` precisely on the goal centerline so the ball cannot slip past the narrow target.

## 4. Assumption Register

| ID | Assumption | Source | Used By |
| -- | -- | -- | -- |
| ASSUMP-001 | `aluminum_6061` and `hdpe` use the repository densities in `manufacturing_config.yaml`. | `worker_heavy/workbenches/manufacturing_config.yaml` | CALC-001 |
| ASSUMP-002 | The wide entry covers the full seeded jitter envelope before the funnel narrows. | `benchmark_definition.yaml` | CALC-001 |
| ASSUMP-003 | The goal pocket overlaps the narrow goal zone and settles the ball at rest. | `benchmark_definition.yaml` | CALC-002 |

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Deterministic declared weight rollup | `345.60 + 24.70 + 16.15 + 16.15 + 8.55 + 14.25 = 425.40 g` | The assembly stays below the 980 g benchmark cap |
| CALC-002 | Deterministic declared cost rollup | `15.50 + 5.25 + 6.50 + 6.50 + 4.00 + 8.50 = 46.25 USD` | The plan stays below the 56 USD benchmark cap |

### CALC-001: Deterministic declared weight rollup

#### Problem Statement

The engineer-owned assembly weight must match the deterministic catalog and density calculation.

#### Assumptions

- `funnel_base` is machined from `aluminum_6061`.
- `wide_entry`, `taper_left`, `taper_right`, `throat_insert`, and `goal_pocket` are machined from `hdpe`.

#### Derivation

- `funnel_base`: `345.60 g`
- `wide_entry`: `24.70 g`
- `taper_left`: `16.15 g`
- `taper_right`: `16.15 g`
- `throat_insert`: `8.55 g`
- `goal_pocket`: `14.25 g`
- Total: `425.40 g`

#### Result

- The declared total weight is `425.40 g`.

#### Design Impact

- The funnel can remain long and rigid while staying under the benchmark cap.

#### Worst-Case Check

- The total remains below the 980 g cap even with the longer base and tapered throat.

#### Cross-References

- `assembly_definition.yaml`
- `benchmark_definition.yaml`

### CALC-002: Deterministic declared cost rollup

#### Problem Statement

The plan must stay under the benchmark cost cap.

#### Derivation

- `funnel_base`: `$15.50`
- `wide_entry`: `$5.25`
- `taper_left`: `$6.50`
- `taper_right`: `$6.50`
- `throat_insert`: `$4.00`
- `goal_pocket`: `$8.50`
- Total: `$46.25`

#### Result

- The declared total cost is `$46.25`.

#### Design Impact

- The funnel retains enough material thickness to keep the throat precise.

#### Assumptions

- The listed unit costs are the deterministic manufacturing estimates for each part.

#### Worst-Case Check

- The declared cost remains at `$46.25`, which is below the `$56.00` cap.

#### Cross-References

- `assembly_definition.yaml`
- `benchmark_definition.yaml`

## 6. Critical Constraints / Operating Envelope

| Limit ID | Limit | Bound | Basis |
| -- | -- | -- | -- |
| LIMIT-001 | Build-zone placement | All engineer parts remain inside the seeded build zone | `benchmark_definition.yaml` |
| LIMIT-002 | Throat alignment | The throat insert stays aligned with the narrow goal centerline | Assembly strategy |
| LIMIT-003 | Goal-zone overlap | `goal_pocket` must overlap the goal zone | `benchmark_definition.yaml` |
| LIMIT-004 | Stability envelope | `funnel_base` stays flat and does not cantilever beyond the footprint | Assembly strategy |

## 7. Cost & Weight Budget

| Item | Weight (g) | Cost ($) |
| -- | -- | -- |
| funnel_base | 345.60 | 15.50 |
| wide_entry | 24.70 | 5.25 |
| taper_left | 16.15 | 6.50 |
| taper_right | 16.15 | 6.50 |
| throat_insert | 8.55 | 4.00 |
| goal_pocket | 14.25 | 8.50 |
| **TOTAL** | **425.40** | **46.25** |

**Budget Margin**: 19% cost headroom and 57% weight headroom versus the planner target.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Ball clips the funnel throat under jitter | Medium | High | Use a long gradual taper instead of a sudden constriction |
| Goal pocket sits off-center from the narrow target | Low | High | Reference the final pocket to the goal-zone centerline and throat insert datum |
| Ball rebounds out of the narrow goal after entry | Medium | Medium | Use a closed pocket at the end of the precision throat |
