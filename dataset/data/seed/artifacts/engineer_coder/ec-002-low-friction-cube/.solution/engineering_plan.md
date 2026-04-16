# Engineering Plan

## 1. Solution Overview

Use a passive low-angle chute with tall guide walls and a shaped bypass around the
central forbid block to move the low-friction ABS cube into the goal zone. The
geometry avoids relying on friction and instead constrains the cube with
continuous walls and gentle transitions. The read-only `slider_cube` payload
enters the `entry_box` and is then guided by the `low_friction_route` assembly
on the fixed `environment_fixture` reference plane.

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

1. Mount `slide_base` on the `environment_fixture` so the route has a stable,
   low-friction foundation.
2. Place `entry_box` at the left end of the base so the jittered cube is
   captured before it reaches the routed section.
3. Mount `guide_wall_left` and `guide_wall_right` as continuous rails along the
   chute edges, then place `blocker_bypass_panel` on the positive-Y side of the
   central keepout to force the bypass.
4. Mount `goal_pocket` overlapping the seeded goal zone so the cube settles
   inside the target instead of skating through it.
5. Keep the layout compact enough that the route remains legible in the plan
   preview and in the seeded engineer render bundle.
6. Preserve the motion-proof scaffold on the starter `solution_assembly`
   label so the required path trace can detour around the central forbid block
   without changing the inventory labels used by the seeded handoff package.

### Placement Notes

- `slide_base`: centered at `(20.0, 0.0, 9.0)` with its long axis aligned to X.
- `entry_box`: centered at `(-225.0, 0.0, 33.0)` on the left capture end.
- `guide_wall_left`: centered at `(-40.0, -66.0, 35.0)` as the lower rail.
- `guide_wall_right`: centered at `(0.0, 66.0, 35.0)` as the upper rail.
- `blocker_bypass_panel`: centered at `(145.0, 42.0, 46.5)` to lift the route
  around the blocker on the positive-Y side.
- `goal_pocket`: centered at `(315.0, 0.0, 30.0)` so its mouth overlaps the
  goal zone.

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
| CALC-003 | Path proof envelope | `solution_assembly` follows a 6-anchor corridor from the build-zone start to the goal-zone contact with a 0.25 s sampling stride | `assembly_definition.yaml.coarse_payload_trajectory`, `payload_trajectory_definition.yaml` |

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

### CALC-003: Path proof envelope

#### Problem Statement

The engineer-coder starter must carry a concrete waypoint sequence so the coarse
forecast and refined payload proof are both inspectable before coding starts.

#### Assumptions

- `solution_assembly` is the payload-proof label used by the starter geometry.
- The path stays within the seeded build zone at the first anchor and ends with
  explicit goal-zone contact at the final anchor.
- The waypoint corridor is summarized as an average-segment envelope, not a
  measured runtime trace.

#### Derivation

- Start: `(-280.0, 0.0, 180.0)` at `t = 0.0 s`
- Left capture lane: `(-240.0, 0.0, 168.0)` at `t = 1.5 s`
- Bypass corner: `(-240.0, 110.0, 150.0)` at `t = 2.4 s`
- Goal lane entry: `(-40.0, 110.0, 126.0)` at `t = 3.6 s`
- Goal approach: `(240.0, 110.0, 90.0)` at `t = 4.8 s`
- Goal contact: `(315.0, 0.0, 57.0)` at `t = 6.0 s`
- Sample stride: `0.25 s`

Segment lengths and average speeds:

- `41.8 mm / 1.5 s = 27.8 mm/s`
- `111.5 mm / 0.9 s = 123.9 mm/s`
- `201.4 mm / 1.2 s = 167.9 mm/s`
- `282.3 mm / 1.2 s = 235.3 mm/s`
- `137.2 mm / 1.2 s = 114.3 mm/s`
- Corridor average: `774.1 mm / 6.0 s = 129.0 mm/s`

#### Worst-Case Check

- The first point stays inside the build zone, the corridor remains above the
  central forbid block, and the terminal point lands inside the goal zone.

#### Result

- The payload proof is explicit enough for render inspection and for the
  engineer coder to refine without re-planning.

#### Design Impact

- The starter plan now exposes a concrete waypoint story instead of a blank
  trajectory scaffold.

#### Cross-References

- `assembly_definition.yaml`
- `payload_trajectory_definition.yaml`
- `solution_script.py`

## 6. Critical Constraints / Operating Envelope

| Limit ID | Limit | Bound | Basis |
| -- | -- | -- | -- |
| LIMIT-001 | Build-zone placement | All engineer parts remain inside the seeded build zone | `benchmark_definition.yaml` |
| LIMIT-002 | Forbid-zone bypass | The routed path must stay outside the central collision block | `benchmark_definition.yaml` |
| LIMIT-003 | Goal-zone overlap | `goal_pocket` must overlap the goal zone | `benchmark_definition.yaml` |
| LIMIT-004 | Stability envelope | `slide_base` stays flat and does not tip under cube impact | Assembly strategy |
| LIMIT-005 | Layout legibility | The routed preview keeps the same labels and placement order as the evidence script | `solution_plan_evidence_script.py` |
| LIMIT-006 | Path proof | The engineer-coder path proof keeps the starter `solution_assembly` label stable while routing above the center collision block | `assembly_definition.yaml.coarse_payload_trajectory` |

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
