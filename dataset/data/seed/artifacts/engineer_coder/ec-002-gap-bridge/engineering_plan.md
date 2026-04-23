# Engineering Plan

## 1. Solution Overview

Use a freestanding bridge deck with shallow side fences to move `transfer_cube`
from the seeded `left_start_deck` across the `floor_gap` and into the
`right_goal_deck` capture zone. The benchmark-owned `bridge_reference_table`
and `gap_floor_guard` stay read-only context; the solution uses them only as
spatial references while keeping the bridge passive and within the planner
budgets.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| base_frame | 560 x 180 x 12 | aluminum_6061 | Freestanding support frame that keeps the bridge aligned without touching the benchmark fixtures |
| bridge_deck | 300 x 95 x 8 | aluminum_6061 | Main transfer surface across the gap |
| left_fence | 300 x 20 x 35 | hdpe | Left-side guide fence that prevents lateral escape |
| right_fence | 300 x 20 x 35 | hdpe | Right-side guide fence that prevents lateral escape |
| landing_pocket | 130 x 110 x 30 | hdpe | Receives the cube at the goal side and damps rebound |

**Estimated Total Weight**: 451.91 g
**Estimated Total Cost**: $57.50

## 3. Assembly Strategy

1. Place `base_frame` centered in the build zone so the support footprint stays
   clear of the `floor_gap` keep-out volume and aligned with
   `left_start_deck`.
2. Mount `bridge_deck` along the x-axis with its span centered over the gap
   corridor and its far end pointing at `right_goal_deck`.
3. Mount `left_fence` and `right_fence` along the deck edges with enough
   clearance for the jittered cube to pass without climbing the rails.
4. Position `landing_pocket` so its mouth overlaps the `goal_zone_mm` and
   captures the cube before it can rebound off the right deck.
5. Keep every part label grounded in `engineering_plan.md`, `todo.md`, and
   `assembly_definition.yaml`, and keep the benchmark fixtures unchanged.
6. The callouts `1`-`5` track the base frame, bridge deck, left fence, right
   fence, and landing pocket, respectively.

## 4. Assumption Register

| ID | Assumption | Source | Used By |
| -- | -- | -- | -- |
| ASSUMP-001 | The benchmark fixtures remain exactly as declared in `benchmark_definition.yaml`. | `benchmark_definition.yaml` | CALC-001 |
| ASSUMP-002 | The bridge may overlap each platform by 10 mm without touching benchmark-owned geometry. | Planner geometry review | CALC-001 |
| ASSUMP-003 | The engineered bridge stays passive and uses the benchmark gap only as a read-only reference. | Handoff contract | CALC-002 |
| ASSUMP-004 | The declared part volumes and unit costs in `assembly_definition.yaml` are the deterministic budget inputs. | `assembly_definition.yaml` | CALC-003 |

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Gap span coverage | `bridge_deck` length of 300 mm bridges the corridor with enough contact area at both ends. | The deck reaches across the gap without relying on unsupported overhang. |
| CALC-002 | Guide coverage | `left_fence` and `right_fence` extend the full deck length, leaving the cube a centered passive path. | The cube stays laterally constrained across jittered arrivals. |
| CALC-003 | Landing capture and budget | `landing_pocket` mouth overlaps the goal zone and the declared part budget totals 451.91 g and $57.50. | The goal-side capture remains stable and the engineer budget stays feasible. |

### CALC-001: Gap span coverage

#### Problem Statement

Determine whether the bridge span reaches across the fixed gap while keeping
usable overlap on both platforms.

#### Assumptions

- `ASSUMP-001`: The platform geometry in `benchmark_definition.yaml` is exact.
- `ASSUMP-002`: A 10 mm overlap on each side is enough for a reviewable static
  bridge seed.

#### Derivation

- The bridge corridor is 280 mm wide between the fixed platform edges.
- The `bridge_deck` length is 300 mm.
- Total overlap = 300 mm - 280 mm = 20 mm.
- Overlap per side = 20 mm / 2 = 10 mm.

#### Worst-Case Check

- A small placement error still leaves the deck spanning both platforms instead
  of leaving a gap.

#### Result

- The bridge deck clears the span requirement with symmetric overlap.

#### Design Impact

- The deck can stay short enough to remain rigid while still bridging the gap.

#### Cross-References

- `benchmark_definition.yaml`
- `assembly_definition.yaml`

### CALC-002: Guide coverage

#### Problem Statement

Verify that the side fences cover the full bridge length and keep the payload
path centered.

#### Assumptions

- `ASSUMP-003`: The bridge remains passive and the fences are only lateral
  guides.

#### Derivation

- `left_fence` length = 300 mm.
- `right_fence` length = 300 mm.
- Each fence spans the same corridor as the bridge deck.

#### Worst-Case Check

- If one fence is struck first under jitter, the opposite fence still keeps the
  cube from drifting completely off the bridge.

#### Result

- The path remains laterally constrained across the deck.

#### Design Impact

- The bridge stays readable as a passive transfer path instead of a loose open
  shelf.

#### Cross-References

- `engineering_plan.md#3-assembly-strategy`
- `assembly_definition.yaml`

### CALC-003: Landing capture and budget

#### Problem Statement

Verify that the landing pocket covers the goal-side capture and that the
declared mass and cost stay within the planner target.

#### Assumptions

- `ASSUMP-004`: The declared per-part volumes and costs are the deterministic
  budget inputs.
- The goal-side pocket can overlap the goal zone and still remain readable as a
  passive capture feature.

#### Derivation

- `landing_pocket` overlaps the goal zone mouth and damps rebound.
- Total weight = 326.70 + 61.56 + 19.95 + 19.95 + 23.75 = 451.91 g.
- Total cost = 19.50 + 11.00 + 7.00 + 7.00 + 13.00 = $57.50.

#### Worst-Case Check

- The totals leave ample headroom under the planner target and benchmark cap.

#### Result

- The capture zone and budget both remain feasible.

#### Design Impact

- The seed stays simple enough for engineer coder to implement without
  re-planning.

#### Cross-References

- `assembly_definition.yaml#totals`
- `benchmark_definition.yaml`

## 6. Critical Constraints / Operating Envelope

| Limit ID | Limit | Bound | Basis |
| -- | -- | -- | -- |
| LIMIT-001 | Build-zone placement | The bridge feet and deck footprint stay inside the benchmark build bounds | `benchmark_definition.yaml` |
| LIMIT-002 | Gap keepout | No support feet or stiffeners may intrude into `floor_gap` | `benchmark_definition.yaml` |
| LIMIT-003 | Motion contract | The bridge remains passive only, with no actuators or powered components | Handoff contract |
| LIMIT-004 | Goal-zone capture | The landing pocket must overlap the goal volume and contain the cube after crossing | `benchmark_definition.yaml` |
| LIMIT-005 | Budget envelope | Maintain the current weight/cost headroom so the planner target remains feasible | `assembly_definition.yaml` |

## 7. Cost & Weight Budget

| Item | Volume (cm^3) | Weight (g) | Cost ($) |
| -- | -- | -- | -- |
| base_frame | 121.0 | 326.70 | 19.50 |
| bridge_deck | 22.8 | 61.56 | 11.00 |
| left_fence | 21.0 | 19.95 | 7.00 |
| right_fence | 21.0 | 19.95 | 7.00 |
| landing_pocket | 25.0 | 23.75 | 13.00 |
| **TOTAL** | 210.8 | 451.91 | **57.50** |

**Budget Margin**: 23% cost headroom and 56% weight headroom versus the
planner target.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Bridge support intrudes into the forbid zone | Low | High | Keep all frame feet outside the seeded gap AABB and validate the footprint in code |
| Cube yaws and rides over a fence | Medium | High | Keep the fences high enough to resist yaw while preserving top clearance |
| Cube rebounds out of the landing area | Medium | Medium | Use a deeper landing pocket with a short backstop wall inside the goal zone |
| Bridge deck flex reduces consistency | Low | Medium | Keep the deck short and support it from both ends with the aluminum frame |

### Jitter Robustness Check

- Capture area covers spawn jitter: Yes
- Tested edge cases considered: left-offset spawn, right-offset spawn, low-Z spawn, high-Z spawn, shallow-angle entry
