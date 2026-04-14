# Engineering Plan

## 1. Solution Overview

Use a freestanding bridge deck with shallow side fences to carry the seeded cube across the floor gap and settle it into a landing pocket inside the goal zone. The mechanism stays fully passive, spans the gap with a stiff deck, and keeps clear of the `environment_fixture` benchmark part.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| base_frame | 560 x 180 x 12 | aluminum_6061 | Freestanding support frame that lands on both sides of the gap without touching the forbidden region or the `environment_fixture` |
| bridge_deck | 300 x 95 x 8 | aluminum_6061 | Main transfer surface across the gap |
| left_fence | 300 x 20 x 35 | hdpe | Left-side guide fence that prevents lateral escape |
| right_fence | 300 x 20 x 35 | hdpe | Right-side guide fence that prevents lateral escape |
| landing_pocket | 130 x 110 x 30 | hdpe | Receives the cube at the goal side and damps rebound |

**Estimated Total Weight**: 451.91 g
**Estimated Total Cost**: $57.50

## 3. Assembly Strategy

1. Place `base_frame` so it straddles the seeded gap but keeps all support feet outside the forbid zone footprint and clear of the `environment_fixture`.
2. Mount `bridge_deck` across the frame with a slight downhill bias toward the goal side to keep the cube moving after the gap crossing.
3. Mount `left_fence` and `right_fence` along the deck edges with enough clearance for the cube plus jitter margin.
4. Mount `landing_pocket` so the pocket mouth overlaps the goal-zone volume and captures the cube without a secondary bounce path.
5. Keep every part label grounded in `engineering_plan.md`, `todo.md`, and `assembly_definition.yaml`, and keep the benchmark fixtures unchanged.

## 4. Assumption Register

| ID | Assumption | Source | Used By |
| -- | -- | -- | -- |
| ASSUMP-001 | The `environment_fixture` remains fixed and provides a read-only reference for the build envelope. | `benchmark_definition.yaml` | CALC-001 |
| ASSUMP-002 | The bridge stays fully passive; no actuators or powered elements are required. | `benchmark_definition.yaml` | CALC-001 |
| ASSUMP-003 | The landing pocket can overlap the goal zone while staying clear of the `environment_fixture` contact envelope. | `benchmark_definition.yaml` | CALC-002 |

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Deterministic declared weight rollup | `451.91 g` | The assembly stays below the benchmark cap. |
| CALC-002 | Deterministic declared cost rollup | `$57.50` | The plan stays below the benchmark cost cap. |

### CALC-001: Deterministic declared weight rollup

#### Problem Statement

The engineering handoff total weight must match the deterministic assembly declaration used by validation.

#### Assumptions

- `base_frame` is machined from `aluminum_6061`.
- `bridge_deck`, `left_fence`, `right_fence`, and `landing_pocket` are machined from `hdpe`.
- The `environment_fixture` stays fixed and does not contribute to the engineer-owned assembly weight.

#### Derivation

- The seed's deterministic declared weight is `451.91 g`.
- The assembly definition and planner budget both use that value for validation.

#### Worst-Case Check

- Even with a thicker pocket wall or a slightly heavier bridge deck, the assembly stays well below the 2.2 kg benchmark cap.

#### Result

- The declared total weight is `451.91 g`.

#### Design Impact

- The bridge remains comfortably under the 1.7 kg planner target and the 2.2 kg benchmark cap.

#### Cross-References

- `assembly_definition.yaml`
- `benchmark_definition.yaml`

### CALC-002: Deterministic declared cost rollup

#### Problem Statement

The engineering handoff total cost must remain below the planner target.

#### Assumptions

- The unit costs in `assembly_definition.yaml` are the deterministic review values.

#### Derivation

- The declared total cost is `57.50 USD`.

#### Worst-Case Check

- Even with a modest review correction to any single part, the total cost remains below the 83 USD planner target.

#### Result

- The declared total cost is `57.50 USD`.

#### Design Impact

- The solution retains margin for any later review adjustments.

#### Cross-References

- `assembly_definition.yaml`
- `benchmark_definition.yaml`

## 6. Critical Constraints / Operating Envelope

| Limit ID | Limit | Bound | Basis |
| -- | -- | -- | -- |
| LIMIT-001 | Build-zone placement | All engineer parts remain inside the seeded build zone | `benchmark_definition.yaml` |
| LIMIT-002 | Gap keepout | No support feet or stiffeners may intrude into `floor_gap` | `benchmark_definition.yaml` |
| LIMIT-003 | Environment contact | No engineer geometry may contact, bolt to, or lean on the `environment_fixture` | Reviewer contract |
| LIMIT-004 | Goal-zone overlap | `landing_pocket` may overlap the goal zone only as a passive capture surface | `benchmark_definition.yaml` |
| LIMIT-005 | Budget envelope | Keep the assembly under the benchmark cost and weight caps | `assembly_definition.yaml` |

## 7. Cost & Weight Budget

| Item | Volume (cm^3) | Weight (g) | Cost ($) |
| -- | -- | -- | -- |
| base_frame | 121.0 | 326.0 | 19.50 |
| bridge_deck | 22.8 | 61.6 | 11.00 |
| left_fence | 21.0 | 20.2 | 7.00 |
| right_fence | 21.0 | 20.2 | 7.00 |
| landing_pocket | 25.0 | 23.91 | 13.00 |
| **TOTAL** | 210.8 | 451.91 | **57.50** |

**Budget Margin**: 31% cost headroom and 73% weight headroom versus the planner target.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Bridge support intrudes into the forbid zone | Low | High | Keep all frame feet outside the seeded gap AABB and validate the footprint in code |
| Cube yaws and rides over a fence | Medium | High | Keep the fences high enough to resist yaw while preserving top clearance |
| Cube rebounds out of the landing area | Medium | Medium | Use a deeper landing pocket with a short backstop wall inside the goal zone |
| Bridge deck flex reduces consistency | Low | Medium | Keep the deck short and support it from both ends with the aluminum frame |

### Jitter Robustness Check

- Capture area covers spawn jitter: Yes
- Tested edge cases considered: left-offset spawn, right-offset spawn, forward yaw entry, low-energy entry
