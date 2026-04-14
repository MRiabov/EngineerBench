## 1. Solution Overview

- Keep the engineering plan simple and deterministic so the downstream coder
  can execute without re-planning.

## 2. Parts List

- One passive support body
- One guide or capture feature

## 3. Assembly Strategy

1. Keep the build inside the seeded build zone.
2. Preserve the benchmark geometry as read-only context.
3. Avoid extra motion or unnecessary complexity.

## 4. Assumption Register

- Assumption: The planner relies on source-backed inputs that must be traceable.

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Example calculation supporting the plan | `N/A` | Replace this placeholder with the actual derived limit. |

### CALC-001: Example calculation supporting the plan

#### Problem Statement

The plan needs a traceable calculation instead of a freeform claim.

#### Assumptions

- `ASSUMP-001`: The input values are taken from the benchmark or assembly definition.

#### Derivation

- Compute the binding quantity from the declared inputs.

#### Worst-Case Check

- The derived limit must hold under the worst-case allowed inputs.

#### Result

- The design remains valid only if the derived limit is respected.

#### Design Impact

- Update the design or inputs if the calculation changes.

#### Cross-References

- `engineering_plan.md#3-assembly-strategy`

## 6. Critical Constraints / Operating Envelope

- Constraint: The mechanism must remain inside the derived operating limits.

## 7. Cost & Weight Budget

- Estimated unit cost: $30
- Estimated weight: 300g

## 8. Risk Assessment

- Low complexity, with the main risk being overbuilding the support geometry.
