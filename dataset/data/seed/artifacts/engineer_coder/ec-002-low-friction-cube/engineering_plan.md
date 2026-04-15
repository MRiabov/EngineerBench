# Engineering Plan

## 1. Solution Overview

Use a passive low-angle chute with tall guide walls and a shaped bypass around the central forbid block to move the low-friction ABS cube into the goal zone. The geometry avoids relying on friction and instead constrains the cube with continuous walls and gentle transitions. The read-only `slider_cube` payload enters the `entry_box` and is then guided by the `low_friction_route` assembly on a freestanding aluminum base.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| slide_base | 620 x 140 x 10 | aluminum_6061 | Freestanding base for the low-friction guide path |
| entry_box | 160 x 120 x 38 | hdpe | Wide entry pocket that catches the jittered cube without rebound |
| guide_wall_left | 420 x 18 x 42 | hdpe | Left continuous wall guiding the cube around the blocker |
| guide_wall_right | 390 x 18 x 42 | hdpe | Right continuous wall shaping the bypass path |
| blocker_bypass_panel | 200 x 18 x 65 | hdpe | Panel that keeps the cube from sliding into the central forbid block |
| goal_pocket | 110 x 90 x 32 | hdpe | Final pocket settling the cube in the goal zone |

**Estimated Total Weight**: 315.11 g
**Estimated Total Cost**: $39.50

## 3. Assembly Strategy

The `low_friction_route` assembly is built on the `slide_base` as the root part:

1. Mount `entry_box` on `slide_base` so the jittered cube is captured before it reaches the routed section.
2. Mount the two guide walls and `blocker_bypass_panel` to create a smooth, continuous path around the seeded forbid zone.
3. Mount `goal_pocket` overlapping the seeded goal zone so the cube cannot skate through the target.

## 4. Assumption Register

| ID | Assumption | Source | Used By |
| -- | -- | -- | -- |
| ASSUMP-001 | `aluminum_6061` and `hdpe` use the repository densities in `manufacturing_config.yaml`. | `worker_heavy/workbenches/manufacturing_config.yaml` | CALC-001 |
| ASSUMP-002 | The bypass panel stays outside the seeded forbid zone while keeping the route continuous. | `benchmark_definition.yaml` | CALC-001 |
| ASSUMP-003 | The goal pocket overlaps the goal zone and contains the cube at rest. | `benchmark_definition.yaml` | CALC-002 |
| ASSUMP-004 | The `environment_fixture` remains fixed and provides the aluminum reference plane for the build zone. | `benchmark_definition.yaml` | CALC-001 |

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Deterministic declared weight rollup | `234.36 + 19.95 + 15.20 + 14.25 + 13.30 + 18.05 = 315.11 g` | The assembly stays below the 980 g planner target |
| CALC-002 | Deterministic declared cost rollup | `14.50 + 5.00 + 5.75 + 5.25 + 4.50 + 4.50 = 39.50 USD` | The plan stays below the 50 USD planner target |

### CALC-001: Deterministic declared weight rollup

#### Problem Statement

The engineer-owned assembly weight must match the deterministic catalog and density calculation.

#### Assumptions

- `slide_base` is machined from `aluminum_6061`.
- `entry_box`, `guide_wall_left`, `guide_wall_right`, `blocker_bypass_panel`, and `goal_pocket` are machined from `hdpe`.

#### Derivation

- `slide_base`: `620 x 140 x 10 mm` stock, `86800 mm3` finished volume, `234.36 g`
- `entry_box`: `160 x 120 x 38 mm` stock, `21000 mm3` finished volume, `19.95 g`
- `guide_wall_left`: `420 x 18 x 42 mm` stock, `16000 mm3` finished volume, `15.20 g`
- `guide_wall_right`: `390 x 18 x 42 mm` stock, `15000 mm3` finished volume, `14.25 g`
- `blocker_bypass_panel`: `200 x 18 x 65 mm` stock, `14000 mm3` finished volume, `13.30 g`
- `goal_pocket`: `110 x 90 x 32 mm` stock, `19000 mm3` finished volume, `18.05 g`
- Total: `315.11 g`

#### Worst-Case Check

- The guide still stays well below the 980 g cap even at the deterministic declared weight of `315.11 g`.

#### Result

- The declared total weight is `315.11 g`.

#### Design Impact

- The low-friction guide remains comfortably under the 980 g planner target.

#### Cross-References

- `assembly_definition.yaml`
- `benchmark_definition.yaml`

### CALC-002: Deterministic declared cost rollup

#### Problem Statement

The plan must stay under the benchmark cost cap.

#### Assumptions

- The listed unit costs are the deterministic manufacturing estimates for each part.

#### Derivation

- `slide_base`: `$14.50`
- `entry_box`: `$5.00`
- `guide_wall_left`: `$5.75`
- `guide_wall_right`: `$5.25`
- `blocker_bypass_panel`: `$4.50`
- `goal_pocket`: `$4.50`
- Total: `$39.50`

#### Worst-Case Check

- The declared cost remains at `$39.50`, which is below the `$50.00` planner target.

#### Result

- The declared total cost is `$39.50`.

#### Design Impact

- The funnel can stay wide enough to tolerate the cube jitter envelope.

#### Cross-References

- `assembly_definition.yaml`
- `benchmark_definition.yaml`

## 6. Critical Constraints / Operating Envelope

| Limit ID | Limit | Bound | Basis |
| -- | -- | -- | -- |
| LIMIT-001 | Build-zone placement | All engineer parts remain inside the seeded build zone | `benchmark_definition.yaml` |
| LIMIT-002 | Forbid-zone bypass | The routed path must stay outside the central collision block | `benchmark_definition.yaml` |
| LIMIT-003 | Goal-zone overlap | `goal_pocket` must overlap the goal zone | `benchmark_definition.yaml` |
| LIMIT-004 | Stability envelope | `slide_base` stays flat and does not tip under cube impact | Assembly strategy |

## 7. Cost & Weight Budget

| Item | Weight (g) | Cost ($) |
| -- | -- | -- |
| slide_base | 234.36 | 14.50 |
| entry_box | 19.95 | 5.00 |
| guide_wall_left | 15.20 | 5.75 |
| guide_wall_right | 14.25 | 5.25 |
| blocker_bypass_panel | 13.30 | 4.50 |
| goal_pocket | 18.05 | 4.50 |
| **TOTAL** | **315.11** | **39.50** |

**Budget Margin**: 21% cost headroom and 68% weight headroom versus the planner target.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Cube slides too fast and clips the blocker | Medium | High | Keep the routed path continuous and use a tall bypass panel at the critical corner |
| Cube rebounds out of the goal under low friction | Medium | Medium | Use a closed goal pocket instead of an open tray |
| Entry jitter sends the cube into a wall edge | Low | Medium | Use a wide entry box before the chute narrows |
