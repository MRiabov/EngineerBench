## 1. Solution Overview

- Keep the fixture valid for planner validation.

## 2. Parts List

- `fixture_body`: a single cube-shaped part.

## 3. Assembly Strategy

1. Define the body as one simple manufactured part.
2. Keep the final assembly aligned with that single part.

## 4. Assumption Register

- The fixture part is rigid.
- The reference material is aluminum 6061.

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Choose a minimal valid mass/cost estimate for the fixture body. | The estimate stays well below the planner caps. | The row remains valid under budget checks. |

### CALC-001: Fixture budget check

#### Problem Statement

Keep the fixture assembly definition within planner limits.

#### Assumptions

- One manufactured part.
- Simplified cube geometry.

#### Derivation

- Estimated unit cost: 10 USD.
- Estimated weight: 100 g.

#### Worst-Case Check

- Both values remain below the target caps.

#### Result

- The fixture passes the budget gate.

#### Design Impact

- No additional structure is needed for this smoke-test row.

#### Cross-References

- `assembly_definition.yaml`

## 6. Critical Constraints / Operating Envelope

- Stay within the planner target caps.

## 7. Cost & Weight Budget

- Cost: 10 USD.
- Weight: 100 g.

## 8. Risk Assessment

- Low risk: the fixture intentionally uses the simplest valid structure.
