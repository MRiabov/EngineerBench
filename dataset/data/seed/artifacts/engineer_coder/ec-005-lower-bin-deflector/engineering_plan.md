# Engineering Plan

## 1. Solution Overview

Use a passive catch-and-deflect chute that intercepts the projectile ball below its elevated start point, steers it around the seeded direct-drop dead zone, and drops it into the lower bin goal zone. The mechanism relies on fixed geometry only and keeps the ball away from the central dead-zone volume. The engineer-owned assembly is named `lower_bin_redirector`, and it is designed against the read-only benchmark reference plane from `environment_fixture`.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| catch_plate | 260 x 130 x 10 | aluminum_6061 | Upper catch plate intercepting the falling ball |
| left_wall | 210 x 18 x 55 | hdpe | Left wall of the deflection chute |
| right_wall | 210 x 18 x 55 | hdpe | Right wall of the deflection chute |
| turn_lip | 120 x 70 x 18 | hdpe | Curved lip steering the ball away from the dead zone |
| lower_funnel | 150 x 110 x 30 | hdpe | Funnel guiding the ball into the lower bin |
| support_column | 180 x 30 x 120 | aluminum_6061 | Column holding the catch plate at the correct intercept height |

**Estimated Total Weight**: 458.5 g
**Estimated Total Cost**: $43.75

## 3. Assembly Strategy

1. Mount `catch_plate` on `support_column` so it intercepts the seeded falling ball before the trajectory enters `direct_drop_dead_zone`.
2. Mount `left_wall`, `right_wall`, and `turn_lip` on the catch plate to steer the ball toward the lower-bin side of the workspace.
3. Mount `lower_funnel` overlapping the seeded goal zone so the ball settles in the lower bin instead of bouncing out.

## 4. Assumption Register

| ID | Assumption | Source | Used By |
| -- | -- | -- | -- |
| ASSUMP-001 | `aluminum_6061` and `hdpe` use the repository densities in `manufacturing_config.yaml`. | `worker_heavy/workbenches/manufacturing_config.yaml` | CALC-001 |
| ASSUMP-002 | The benchmark-owned `environment_fixture` remains fixed and provides the aluminum reference plane for the build zone. | `benchmark_definition.yaml` | CALC-001 |
| ASSUMP-003 | The catch plate stays above the dead zone and the lower funnel stays inside the goal zone. | `benchmark_definition.yaml` | CALC-001 |
| ASSUMP-004 | The deflection path remains passive and does not rely on any actuation. | `benchmark_definition.yaml` | CALC-002 |

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Deterministic declared weight rollup | `259.20 + 14.25 + 14.25 + 9.50 + 20.90 + 140.40 = 458.50 g` | The assembly stays below the 1050 g benchmark cap |
| CALC-002 | Deterministic declared cost rollup | `12.50 + 5.00 + 5.00 + 4.50 + 6.75 + 10.00 = 43.75 USD` | The plan stays below the 57 USD benchmark cap |

### CALC-001: Deterministic declared weight rollup

#### Problem Statement

The engineer-owned assembly weight must match the deterministic catalog and density calculation.

#### Assumptions

- `catch_plate` and `support_column` are machined from `aluminum_6061`.
- `left_wall`, `right_wall`, `turn_lip`, and `lower_funnel` are machined from `hdpe`.

#### Derivation

- `catch_plate`: `259.20 g`
- `left_wall`: `14.25 g`
- `right_wall`: `14.25 g`
- `turn_lip`: `9.50 g`
- `lower_funnel`: `20.90 g`
- `support_column`: `140.40 g`
- Total: `458.50 g`

#### Worst-Case Check

- The total remains below the 1050 g cap even with the tall support column and aluminum catch plate.

#### Result

- The declared total weight is `458.50 g`.

#### Design Impact

- The catch-and-deflect chute remains comfortably under the benchmark cap.

#### Cross-References

- `assembly_definition.yaml`
- `benchmark_definition.yaml`

### CALC-002: Deterministic declared cost rollup

#### Problem Statement

The plan must stay under the benchmark cost cap.

#### Assumptions

- The listed unit costs are the deterministic manufacturing estimates for each part.

#### Derivation

- `catch_plate`: `$12.50`
- `left_wall`: `$5.00`
- `right_wall`: `$5.00`
- `turn_lip`: `$4.50`
- `lower_funnel`: `$6.75`
- `support_column`: `$10.00`
- Total: `$43.75`

#### Worst-Case Check

- The declared cost remains at `$43.75`, which is below the `$57.00` cap.

#### Result

- The declared total cost is `$43.75`.

#### Design Impact

- The support column can stay tall enough to catch the elevated ball.

#### Cross-References

- `assembly_definition.yaml`
- `benchmark_definition.yaml`

## 6. Critical Constraints / Operating Envelope

| Limit ID | Limit | Bound | Basis |
| -- | -- | -- | -- |
| LIMIT-001 | Build-zone placement | All engineer parts remain inside the seeded build zone | `benchmark_definition.yaml` |
| LIMIT-002 | Dead-zone bypass | The chute path stays clear of `direct_drop_dead_zone` | `benchmark_definition.yaml` |
| LIMIT-003 | Goal-zone overlap | `lower_funnel` must overlap the goal zone | `benchmark_definition.yaml` |
| LIMIT-004 | Stability envelope | `support_column` keeps the catch plate rigid under impact | Assembly strategy |

## 7. Cost & Weight Budget

| Item | Weight (g) | Cost ($) |
| -- | -- | -- |
| catch_plate | 259.20 | 12.50 |
| left_wall | 14.25 | 5.00 |
| right_wall | 14.25 | 5.00 |
| turn_lip | 9.50 | 4.50 |
| lower_funnel | 20.90 | 6.75 |
| support_column | 140.40 | 10.00 |
| **TOTAL** | **458.50** | **43.75** |

**Budget Margin**: 23% cost headroom and 56% weight headroom versus the planner target.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Ball misses the catch plate under spawn jitter | Medium | High | Oversize the catch plate relative to the seeded jitter envelope |
| Ball re-enters the dead zone after deflection | Medium | High | Use a curved turn lip and chute walls that keep the path offset from the keepout |
| Ball rebounds out of the lower bin | Low | Medium | Use a funnel insert and goal overlap at the final pocket |
