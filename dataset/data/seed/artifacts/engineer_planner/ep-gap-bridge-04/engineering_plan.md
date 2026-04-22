# Engineering Plan

## 1. Solution Overview

- **Core Mechanism**: A pocketed `bridge_deck` spans the 280 mm clear gap
  between `left_start_deck` and `right_goal_deck`, creating a continuous
  passive path for `transfer_cube`.
- **Key Principle**: Keep the deck centered over the gap so the coarse payload
  path can run from `benchmark_definition.payload.start_position_mm` to the
  goal-zone center without using any benchmark-owned motion.
- **Robustness Strategy**: Short `left_support` and `right_support` anchor
  blocks give the span overlap on both platforms, and a small `stop_lip`
  prevents overshoot at the goal-side exit while `bridge_reference_table`
  remains a read-only alignment cue.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| bridge_deck | 300 × 95 × 8 | aluminum_6061 | Pocketed main span that carries `transfer_cube` across the gap |
| left_support | 24 × 95 × 18 | aluminum_6061 | Left anchor block that keys the span to `left_start_deck` |
| right_support | 24 × 95 × 18 | aluminum_6061 | Right anchor block that keys the span to `right_goal_deck` |
| stop_lip | 8 × 95 × 12 | aluminum_6061 | Exit guard that keeps `transfer_cube` from rolling past the goal edge |

**Estimated Total Weight**: 11.92 g
**Estimated Total Cost**: $14.00

## 3. Assembly Strategy

1. Center the `bridge_deck` so it overlaps each platform by 10 mm and keeps
   its midpoint over `bridge_reference_table`.
2. Place `left_support` and `right_support` as short interface blocks at the
   deck ends so the span has a clean transition onto the benchmark fixtures.
3. Mount `stop_lip` on the goal-side exit edge so `transfer_cube` settles into
   `right_goal_deck` instead of rolling back off the bridge.
4. Keep all engineered parts above the `gap_floor_guard` top face and inside
   the declared build zone.

## 4. Assumption Register

| ID | Assumption | Source | Used By |
| -- | -- | -- | -- |
| ASSUMP-001 | `left_start_deck` and `right_goal_deck` remain exactly at the centers and sizes declared in `benchmark_definition.yaml`. | `benchmark_definition.yaml` | CALC-001 |
| ASSUMP-002 | A 10 mm overlap on each platform is sufficient for the planner-stage bridge envelope. | Planner geometry review | CALC-001, CALC-002 |
| ASSUMP-003 | The bridge top plane may sit at z=78 mm and still keep the payload path below the 80 mm spawn ceiling. | `benchmark_definition.yaml` | CALC-002 |
| ASSUMP-004 | The `part_volume_mm3` values in `assembly_definition.yaml` represent the reduced-mass machined blanks used for costing. | `assembly_definition.yaml` | CALC-003 |

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Bridge span versus the fixed gap | 280 mm clear span, 300 mm bridge deck, 10 mm overlap per side | Confirms the span reaches both platforms without guessing geometry |
| CALC-002 | Vertical envelope for the transfer path | Bridge top plane at z=78 mm, which stays below the 80 mm spawn ceiling and above the 40 mm `gap_floor_guard` top | Keeps the coarse motion contract inside the safe envelope |
| CALC-003 | Cost and weight budget | 4.416 cm³ total machined volume, 11.9232 g total weight, $14.00 total cost | Leaves large headroom under the planner target and benchmark caps |

### CALC-001: Bridge span versus the fixed gap

#### Problem Statement

Determine the minimum span needed to bridge the read-only platform geometry.

#### Assumptions

- `ASSUMP-001`: The fixture dimensions in `benchmark_definition.yaml` are exact.
- `ASSUMP-002`: The bridge may overlap each deck by 10 mm.

#### Derivation

- `left_start_deck` spans x = -310 mm to -130 mm, so its right edge is at -130 mm.
- `right_goal_deck` spans x = 150 mm to 350 mm, so its left edge is at 150 mm.
- Clear gap = 150 - (-130) = 280 mm.
- Chosen `bridge_deck` length = 300 mm, so total overlap = 300 - 280 = 20 mm.
- Overlap per side = 20 / 2 = 10 mm.

#### Worst-Case Check

- A 5 mm placement error in either direction still leaves 5 mm of overlap on
  each side, which is enough for the planned span.

#### Result

- The span is long enough to bridge the gap while remaining centered on the
  benchmark fixtures.

#### Design Impact

- Use a 300 mm bridge length instead of a shorter template placeholder.

#### Cross-References

- `engineering_plan.md#4-assumption-register`
- `benchmark_definition.yaml`
- `assembly_definition.yaml`

### CALC-002: Vertical envelope for the transfer path

#### Problem Statement

Keep the coarse transfer path below the spawn-height ceiling and above the
floor-gap guard.

#### Assumptions

- `ASSUMP-002`: The bridge deck may sit flush on the platform top plane.
- `ASSUMP-003`: The payload path should not exceed the 80 mm spawn height.

#### Derivation

- The benchmark platform tops are at z = 70 mm.
- The `bridge_deck` thickness is 8 mm, so the bridge top plane is z = 78 mm.
- The `gap_floor_guard` top face is at z = 40 mm.
- The bridge top plane therefore stays 2 mm below the 80 mm spawn ceiling and
  38 mm above the floor-gap guard.

#### Worst-Case Check

- A 2 mm upward error would put the bridge top at z = 80 mm, which reaches the
  ceiling but does not exceed it; the nominal build target keeps margin below
  that limit.

#### Result

- The bridge stays in the intended vertical envelope for the coarse motion
  forecast.

#### Design Impact

- Keep the bridge and stop lip low enough that the transfer path can remain
  visually legible and build-zone safe.

#### Cross-References

- `assembly_definition.yaml#coarse_payload_trajectory`
- `benchmark_definition.yaml`
- `engineering_plan.md#3-assembly-strategy`

### CALC-003: Cost and weight budget

#### Problem Statement

Estimate the planner-stage mass and cost for the pocketed bridge parts.

#### Assumptions

- `ASSUMP-004`: `aluminum_6061` is approximated at 2.7 g/cm³ for the weight
  estimate.
- The part costs in `assembly_definition.yaml` are the planner estimates used
  for budget checks.

#### Derivation

- `bridge_deck`: 2,048 mm³ = 2.048 cm³ -> 5.53 g.
- `left_support`: 1,152 mm³ = 1.152 cm³ -> 3.11 g.
- `right_support`: 1,152 mm³ = 1.152 cm³ -> 3.11 g.
- `stop_lip`: 64 mm³ = 0.064 cm³ -> 0.17 g.
- Total volume = 2.048 + 1.152 + 1.152 + 0.064 = 4.416 cm³.
- Total weight = 4.416 × 2.7 = 11.9232 g.
- Total cost = 7 + 3 + 3 + 1 = $14.00.

#### Worst-Case Check

- Even if each part cost estimate is rounded up by 20%, the plan remains well
  below the 18 USD planner target and the 27 USD benchmark cap.

#### Result

- The plan is lightweight and inexpensive enough to leave implementation margin.

#### Design Impact

- The bridge can stay pocketed without threatening the budget envelope.

#### Cross-References

- `assembly_definition.yaml#totals`
- `engineering_plan.md#2-parts-list`
- `engineering_plan.md#7-cost--weight-budget`

## 6. Critical Constraints / Operating Envelope

| Limit ID | Limit | Bound | Basis |
| -- | -- | -- | -- |
| LIMIT-001 | Minimum deck overlap | `10 mm` per side | `CALC-001` |
| LIMIT-002 | Bridge top plane | `78 mm` nominal | `CALC-002` |
| LIMIT-003 | Estimated total weight | `11.9232 g` | `CALC-003` |
| LIMIT-004 | Estimated total cost | `$14.00` | `CALC-003` |

## 7. Cost & Weight Budget

| Item | Volume (cm³) | Weight (g) | Cost ($) |
| -- | -- | -- | -- |
| bridge_deck | 2.048 | 5.53 | 7.00 |
| left_support | 1.152 | 3.11 | 3.00 |
| right_support | 1.152 | 3.11 | 3.00 |
| stop_lip | 0.064 | 0.17 | 1.00 |
| **TOTAL** | 4.416 | 11.92 | 14.00 |

**Budget Margin**: cost remains 4.00 USD under the planner target and 13.00 USD
under the benchmark cap; weight remains 8.08 g under the planner target and
18.08 g under the benchmark cap.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| `transfer_cube` clips the bridge edge during jittered starts | Medium | High | Keep the deck centered and preserve the 10 mm overlap on both decks |
| `transfer_cube` overshoots the right deck | Low | Medium | Use the goal-side `stop_lip` and keep the exit guard short |
| Anchor blocks drift into benchmark-owned geometry | Low | High | Keep the engineered parts aligned to the bridge ends and clear of `gap_floor_guard` |

### Jitter Robustness Check

- Capture corridor covers spawn jitter: Yes
- Tested edge cases considered: left-offset spawn, right-offset spawn, low-Z
  spawn, and high-Z spawn
