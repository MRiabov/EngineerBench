# Engineering Plan

## 1. Solution Overview

- **Core Mechanism**: This starter template uses a single `starter_stub_block`
  as a neutral marker so the workspace stays valid without pretending to be a
  solved mechanism.
- **Key Principle**: Keep the stub scene compact, readable, and obviously
  starter-only until a task-specific revision replaces it.
- **Boundary Rule**: Treat `benchmark_definition.yaml` and
  `benchmark_assembly_definition.yaml` as read-only context; the engineered
  contract lives in `assembly_definition.yaml`.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| `starter_stub_block` | 5 x 5 x 5 | aluminum_6061 | Neutral starter block that keeps the template schema-valid without implying a real solution |

**Estimated Total Weight**: 0.34 g
**Estimated Total Cost**: $1.00

## 3. Assembly Strategy

1. Keep the `starter_stub_block` centered at the origin so the scene is easy to
   inspect and clearly not a finished design.
2. Keep `starter_stub_assembly` as a single-part container so the final
   assembly remains valid but minimal.
3. Leave the benchmark-owned files unchanged and use them only as read-only
   task context.
4. Replace the stub labels with task-specific engineering labels when a real
   solution is authored.

## 4. Assumption Register

| ID | Assumption | Source | Used By |
| -- | -- | -- | -- |
| ASSUMP-001 | `benchmark_definition.yaml` and `benchmark_assembly_definition.yaml` are read-only inputs for the engineer planner. | Handoff contract | CALC-001, CALC-002, CALC-003 |
| ASSUMP-002 | A single neutral block is enough to keep the starter workspace schema-valid. | Starter template policy | CALC-001 |
| ASSUMP-003 | `aluminum_6061` uses the shared manufacturing config density for the weight estimate. | `manufacturing_config.yaml` | CALC-002 |
| ASSUMP-004 | The declared unit cost is intentionally tiny so the starter stays far under the planner target. | `assembly_definition.yaml` | CALC-003 |

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Starter scene scope | One block, one subassembly, one evidence scene | Keeps the template obviously stubbed while staying schema-valid |
| CALC-002 | Deterministic weight | 125 mm^3 at 2.7 g/cm^3 = 0.3375 g, rounded to 0.34 g | Matches the priced YAML total after validation |
| CALC-003 | Deterministic cost | One CNC part at $1.00/unit = $1.00 total | Leaves the starter well under the planner target cap |

### CALC-001: Starter scene scope

#### Problem Statement

Keep the engineer starter workspace valid without implying that the solution is
already designed.

#### Assumptions

- `ASSUMP-001`: The benchmark files are read-only context.
- `ASSUMP-002`: A single neutral block is enough for a starter scene.

#### Derivation

- `starter_stub_block` is the only manufactured part.
- `starter_stub_assembly` contains exactly one part entry.
- `solution_plan_evidence_script.py` renders one box and nothing else.

#### Worst-Case Check

- If the stub is confused with a final solution, the labels and minimal
  geometry make the mismatch visible immediately.

#### Result

- The scene remains a valid starter template rather than a solved bridge, gate,
  or corridor design.

#### Design Impact

- Keep the starter template simple enough that later revisions can replace it
  without untangling hidden geometry.

#### Cross-References

- `engineering_plan.md#1-solution-overview`
- `assembly_definition.yaml`
- `solution_plan_evidence_script.py`

### CALC-002: Deterministic weight

#### Problem Statement

Compute the starter weight from the declared manufactured part volume.

#### Assumptions

- `ASSUMP-003`: `aluminum_6061` density is taken from the shared manufacturing
  config.

#### Derivation

- Part volume = 5 x 5 x 5 = 125 mm^3.
- 125 mm^3 = 0.125 cm^3.
- 0.125 cm^3 x 2.7 g/cm^3 = 0.3375 g.
- Rounded declared total weight = 0.34 g.

#### Worst-Case Check

- A small rounding difference still leaves the starter far below the planner
  target.

#### Result

- The declared weight is deterministic and tiny.

#### Design Impact

- Keep the stub part compact so the evidence scene stays lightweight.

#### Cross-References

- `assembly_definition.yaml#totals`
- `assembly_definition.yaml#manufactured_parts`
- `manufacturing_config.yaml`

### CALC-003: Deterministic cost

#### Problem Statement

Keep the starter cost obviously valid but not solution-like.

#### Assumptions

- `ASSUMP-004`: The declared unit cost is the planner estimate used by the
  validation helper.

#### Derivation

- One manufactured part is declared.
- The part has `estimated_unit_cost_usd: 1.0`.
- Total cost = 1 x 1.0 = $1.00.

#### Worst-Case Check

- Even if a downstream reviewer treats the stub as a real part, the declared
  cost still stays far below the planner target cap.

#### Result

- The starter template remains comfortably within budget.

#### Design Impact

- Keep the stub cost simple so the template does not carry fake design intent.

#### Cross-References

- `assembly_definition.yaml#totals`
- `engineering_plan.md#7-cost--weight-budget`
- `assembly_definition.yaml#manufactured_parts`

## 6. Critical Constraints / Operating Envelope

| Limit ID | Limit | Bound | Basis |
| -- | -- | -- | -- |
| LIMIT-001 | Solution scope | Exactly one starter block | `CALC-001` |
| LIMIT-002 | Scene readability | No exploded layout or hidden geometry | `CALC-001` |
| LIMIT-003 | Estimated total weight | 0.34 g | `CALC-002` |
| LIMIT-004 | Estimated total cost | $1.00 | `CALC-003` |

## 7. Cost & Weight Budget

| Item | Volume (cm^3) | Weight (g) | Cost ($) |
| -- | -- | -- | -- |
| `starter_stub_block` | 0.125 | 0.34 | 1.00 |
| **TOTAL** | 0.125 | 0.34 | 1.00 |

**Budget Margin**: the starter stays intentionally small so it is clearly a
template scaffold, not a real production design.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| The starter is mistaken for a solved mechanism | Medium | High | Keep the labels `starter_stub_block` and `starter_stub_assembly` explicit |
| The plan drifts away from the read-only benchmark context | Low | High | Treat `benchmark_definition.yaml` and `benchmark_assembly_definition.yaml` as fixed inputs |
| The evidence script no longer matches the YAML | Low | High | Keep the one-box script and the one-row inventory in lockstep |

### Starter Check

- Starter workspace uses a single neutral part: Yes
- Task-specific mechanism is already encoded here: No
- Benchmark-owned context is editable: No
