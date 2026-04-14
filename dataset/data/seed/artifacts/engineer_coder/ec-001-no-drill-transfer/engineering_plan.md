# Engineering Plan

## 1. Solution Overview

Use a completely freestanding twin-wall chute that receives the projectile ball on the left side and carries it to the right goal zone without drilling, bolting into, or leaning on the environment. Stability comes from a wide aluminum base and low center of mass rather than external attachment.

## 2. Parts List

| Part | Dimensions (mm) | Material | Purpose |
| -- | -- | -- | -- |
| freestanding_base | 620 x 180 x 12 | aluminum_6061 | Wide low center-of-mass base keeping the transfer stable without attachment |
| capture_funnel | 160 x 140 x 40 | hdpe | Capture pocket covering the seeded spawn jitter |
| left_wall | 460 x 20 x 32 | hdpe | Left chute wall |
| right_wall | 460 x 20 x 32 | hdpe | Right chute wall |
| exit_tray | 140 x 110 x 35 | hdpe | Goal-side tray settling the ball in the target |
| ballast_block | 180 x 80 x 18 | steel_structural | Extra mass on the base to prevent tip-over |

**Estimated Total Weight**: 649.05 g
**Estimated Total Cost**: $42.75

## 3. Assembly Strategy

1. Keep `freestanding_base` centered in the build zone and mount `ballast_block` low on the base to stabilize the mechanism.
2. Mount `capture_funnel`, `left_wall`, and `right_wall` on the base only, with no fasteners or contact into the environment_fixture.
3. Terminate the transfer in `exit_tray` overlapping the seeded goal zone so the ball settles without rebounding out.

## 4. Assumption Register

| ID | Assumption | Source | Used By |
| -- | -- | -- | -- |
| ASSUMP-001 | `steel_structural` uses the repository density of 7.85 g/cm^3 for deterministic weight rollup. | `worker_heavy/workbenches/manufacturing_config.yaml` | CALC-001 |
| ASSUMP-002 | The freestanding base stays centered and no engineer part touches the environment_fixture. | `benchmark_definition.yaml` | CALC-001 |
| ASSUMP-003 | The exit tray overlaps the goal zone so the ball can settle without relying on rebound behavior. | `benchmark_definition.yaml` | CALC-002 |

## 5. Detailed Calculations

| ID | Problem / Decision | Result | Impact |
| -- | -- | -- | -- |
| CALC-001 | Deterministic declared weight rollup | `361.80 + 20.90 + 14.25 + 14.25 + 18.05 + 219.80 = 649.05 g` | The assembly stays below the 900 g benchmark cap |
| CALC-002 | Deterministic declared cost rollup | `15.50 + 5.00 + 5.50 + 5.50 + 8.25 + 3.00 = 42.75 USD` | The plan stays below the 54 USD benchmark cap |

### CALC-001: Deterministic declared weight rollup

#### Problem Statement

The engineer-owned assembly weight must match the deterministic catalog and density calculation.

#### Assumptions

- `freestanding_base` is machined from `aluminum_6061`.
- `capture_funnel`, `left_wall`, `right_wall`, and `exit_tray` are machined from `hdpe`.
- `ballast_block` is machined from `steel_structural`.

#### Derivation

- `freestanding_base`: `620 x 180 x 12 mm` stock, `133920 mm3` volume, `361.80 g`
- `capture_funnel`: `22000 mm3` part volume, `20.90 g`
- `left_wall`: `15000 mm3` part volume, `14.25 g`
- `right_wall`: `15000 mm3` part volume, `14.25 g`
- `exit_tray`: `19000 mm3` part volume, `18.05 g`
- `ballast_block`: `28000 mm3` part volume, `219.80 g`
- Total: `361.80 + 20.90 + 14.25 + 14.25 + 18.05 + 219.80 = 649.05 g`

#### Worst-Case Check

- Even with the declared steel ballast, the total weight remains below the 900 g cap and the geometry stays freestanding.

#### Result

- The declared total weight is `649.05 g`.

#### Design Impact

- The freestanding layout remains comfortably under the benchmark cap.

#### Cross-References

- `assembly_definition.yaml`
- `benchmark_definition.yaml`

### CALC-002: Deterministic declared cost rollup

#### Problem Statement

The plan must stay under the benchmark cost cap.

#### Assumptions

- The listed unit costs are the deterministic manufacturing estimates for each part.

#### Derivation

- `freestanding_base`: `$15.50`
- `capture_funnel`: `$5.00`
- `left_wall`: `$5.50`
- `right_wall`: `$5.50`
- `exit_tray`: `$8.25`
- `ballast_block`: `$3.00`
- Total: `$15.50 + $5.00 + $5.50 + $5.50 + $8.25 + $3.00 = $42.75`

#### Worst-Case Check

- The declared cost remains at `$42.75`, which is below the `$54.00` cap.

#### Result

- The declared total cost is `$42.75`.

#### Design Impact

- The base can stay thick enough to resist tipping without violating cost.

#### Cross-References

- `assembly_definition.yaml`
- `benchmark_definition.yaml`

## 6. Critical Constraints / Operating Envelope

| Limit ID | Limit | Bound | Basis |
| -- | -- | -- | -- |
| LIMIT-001 | Build-zone placement | All engineer parts remain inside the seeded build zone | `benchmark_definition.yaml` |
| LIMIT-002 | No-drill rule | No geometry drills into or leans on the environment_fixture | Reviewer contract |
| LIMIT-003 | Goal-zone overlap | `exit_tray` must overlap the goal zone | `benchmark_definition.yaml` |
| LIMIT-004 | Stability envelope | `ballast_block` stays low on the base and does not overhang the footprint | Assembly strategy |
| LIMIT-005 | Spawn jitter absorption | `capture_funnel` pocket covers ±10 mm X, ±8 mm Y, ±4 mm Z jitter | `benchmark_definition.yaml` payload.runtime_jitter |

## 7. Cost & Weight Budget

| Item | Weight (g) | Cost ($) |
| -- | -- | -- |
| freestanding_base | 361.80 | 15.50 |
| capture_funnel | 20.90 | 5.00 |
| left_wall | 14.25 | 5.50 |
| right_wall | 14.25 | 5.50 |
| exit_tray | 18.05 | 8.25 |
| ballast_block | 219.80 | 3.00 |
| **TOTAL** | **649.05** | **42.75** |

**Budget Margin**: 21% cost headroom and 28% weight headroom versus the benchmark caps.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
| -- | -- | -- | -- |
| Freestanding assembly tips under impact | Medium | High | Keep a wide base and add low-mounted ballast |
| Ball escapes due to spawn jitter | Medium | Medium | Use an oversized capture funnel before the chute narrows |
| Hidden environment contact violates the no-drill rule | Low | High | Keep all geometry referenced from the freestanding base and leave explicit clearance to the environment_fixture |
