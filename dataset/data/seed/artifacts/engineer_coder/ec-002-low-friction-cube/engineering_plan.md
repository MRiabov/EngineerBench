# Engineering Plan

## 1. Solution Overview

Use a single HDPE `guide_rail` sweep to form the `low_friction_route`
assembly. The evidence script keeps the geometry compact and readable while the
read-only `slider_cube` payload stays benchmark-owned on the fixed
`environment_fixture` plane.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| guide_rail | 620 x 120 x 50 | hdpe | Single CNC guide sweep that matches the evidence corridor and carries the `low_friction_route` label set |

**Estimated Total Weight**: 52.48 g
**Estimated Total Cost**: $8.00

## 3. Assembly Strategy

The `low_friction_route` assembly is built from one manufactured part:

1. Place `guide_rail` as the only manufactured part in the `low_friction_route`
   compound.
2. Anchor the route to the fixed `environment_fixture` so the plan stays on the
   read-only benchmark plane.
3. Preserve the exact six-anchor corridor already encoded in
   `solution_plan_evidence_script.py`; the labels must stay stable so the render
   bundle stays readable.
4. Keep the route compact enough that the evidence scene remains a single
   inspectable sweep instead of a multi-part detour.

### Placement Notes

- `guide_rail`: swept along the descending corridor from `(-280.0, 0.0, 140.0)`
  to `(315.0, 0.0, 17.0)` with the same 12 x 6 profile used by the evidence
  script.
- `low_friction_route`: the compound label for the single-part route assembly.

## 4. Assumption Register

| ID | Assumption | Source | Used By |
| -- | -- | -- | -- |
| ASSUMP-001 | `hdpe` uses the repository density and CNC price model from `manufacturing_config.yaml`. | `worker_heavy/workbenches/manufacturing_config.yaml` | CALC-001, CALC-002 |
| ASSUMP-002 | The `environment_fixture` remains fixed and is only read as reference context. | `benchmark_definition.yaml` | CALC-003 |
| ASSUMP-003 | The routed corridor stays inside the seeded build zone and clears the central forbid block. | `benchmark_definition.yaml` | CALC-003 |
| ASSUMP-004 | The planner evidence script is the authoritative geometry preview for `guide_rail` and `low_friction_route`. | `solution_plan_evidence_script.py` | CALC-003 |

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Deterministic declared weight rollup for the single manufactured part | `55238.4 mm3 x 0.95 g/cm3 / 1000 = 52.48 g` | The route stays far below the 980 g planner target |
| CALC-002 | Deterministic declared cost rollup for the single manufactured part | `8.00 USD` | The route stays far below the 50 USD planner target |
| CALC-003 | Path proof envelope | `guide_rail` follows a 6-anchor corridor from the build-zone start to the goal-zone contact with a 0.25 s sampling stride | `assembly_definition.yaml.coarse_payload_trajectory`, `solution_plan_evidence_script.py` |

### CALC-001: Deterministic declared weight rollup

#### Problem Statement

The engineer-owned assembly weight must match the single fabricated route part.

#### Assumptions

- `guide_rail` is machined from `hdpe`.
- The solid corresponds to the 12 x 6 swept profile over the 767.2 mm routed
  centerline.

#### Derivation

- Swept profile area: `12 mm x 6 mm = 72 mm2`
- Centerline length: `767.2 mm`
- Finished volume: `72 mm2 x 767.2 mm = 55238.4 mm3`
- Material density: `0.95 g/cm3`
- Weight: `55238.4 mm3 x 0.95 / 1000 = 52.48 g`

#### Worst-Case Check

- The declared weight stays well below the 980 g cap even if the route is
  treated as a single solid part.

#### Result

- The declared total weight is `52.48 g`.

#### Design Impact

- The single guide remains lightweight and easy to review.

#### Cross-References

- `assembly_definition.yaml`
- `solution_plan_evidence_script.py`

### CALC-002: Deterministic declared cost rollup

#### Problem Statement

The plan must stay under the benchmark cost cap.

#### Assumptions

- The declared unit cost is the deterministic manufacturing estimate for the
  single route part.

#### Derivation

- `guide_rail`: `$8.00`
- Total: `$8.00`

#### Worst-Case Check

- The declared cost remains at `$8.00`, which is far below the `$50.00`
  planner target.

#### Result

- The declared total cost is `$8.00`.

#### Design Impact

- The route stays simple enough that the cost model is easy to audit.

#### Cross-References

- `assembly_definition.yaml`

### CALC-003: Path proof envelope

#### Problem Statement

The engineer-coder starter must carry a concrete waypoint sequence so the
coarse forecast and the preview render both stay inspectable before coding
starts.

#### Assumptions

- `guide_rail` is the payload-proof label used by the planner motion proof.
- The path stays within the seeded build zone at the first anchor and ends with
  explicit goal-zone contact at the final anchor.
- The waypoint corridor is summarized as an average-segment envelope, not a
  measured runtime trace.

#### Derivation

- Start: `(-280.0, 0.0, 140.0)` at `t = 0.0 s`
- Left capture lane: `(-240.0, 0.0, 128.0)` at `t = 1.5 s`
- Bypass corner: `(-240.0, 110.0, 110.0)` at `t = 2.4 s`
- Goal lane entry: `(-40.0, 110.0, 86.0)` at `t = 3.6 s`
- Goal approach: `(240.0, 110.0, 50.0)` at `t = 4.8 s`
- Goal contact: `(315.0, 0.0, 17.0)` at `t = 6.0 s`
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

- The starter plan exposes a concrete waypoint story instead of a blank
  trajectory scaffold.

#### Cross-References

- `assembly_definition.yaml`
- `solution_plan_evidence_script.py`

## 6. Critical Constraints / Operating Envelope

| Limit ID | Limit | Bound | Basis |
| -- | -- | -- | -- |
| LIMIT-001 | Build-zone placement | The `guide_rail` route stays inside the seeded build zone | `benchmark_definition.yaml` |
| LIMIT-002 | Forbid-zone bypass | The routed corridor stays outside the central collision block | `benchmark_definition.yaml` |
| LIMIT-003 | Goal-zone contact | The terminal anchor lands in the goal zone | `benchmark_definition.yaml` |
| LIMIT-004 | Single-part stability | The `guide_rail` stays rigid on the fixed plane | Assembly strategy |
| LIMIT-005 | Layout legibility | The routed preview keeps the same labels and placement order as the evidence script | `solution_plan_evidence_script.py` |
| LIMIT-006 | Path proof | The engineer-coder path proof keeps the starter `guide_rail` label stable while tracing the exact corridor | `assembly_definition.yaml.coarse_payload_trajectory` |

## 7. Cost & Weight Budget

| Item | Weight (g) | Cost ($) |
| -- | -- | -- |
| guide_rail | 52.48 | 8.00 |
| **TOTAL** | **52.48** | **8.00** |

**Budget Margin**: 84% cost headroom and 95% weight headroom versus the planner target.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| The rail sweep clips the bend at the bypass corner | Low | Medium | Keep the corridor anchors fixed and preserve the current 12 x 6 profile |
| The goal contact rises or falls outside the preview envelope | Low | Medium | Keep the terminal anchor at `(315.0, 0.0, 17.0)` |
| The plan becomes harder to review if the labels drift | Low | High | Keep `low_friction_route` and `guide_rail` stable across the plan and YAML |
