## 1. Learning Objective

Review a lower-bin redirection benchmark package with `upper_start_ledge`,
`deflector_ramp`, `direct_drop_shield`, and `lower_bin`.

## 2. Geometry

- `upper_start_ledge`: release ledge.
- `deflector_ramp`: redirection ramp.
- `direct_drop_shield`: dead-zone shield.
- `lower_bin`: final capture bin.

## 3. Objectives

- Verify the lower-bin path stays physically plausible.
- Reject any geometry that forces a direct drop through the dead zone.
- Keep the benchmark package internally consistent across geometry, validation,
  and simulation evidence.

## 4. Randomization

- The seeded ball radius stays within the declared envelope.
- The start pose remains deterministic for this review package.

## 5. Implementation Notes

- `benchmark_script.py`, `validation_results.json`, and
  `simulation_result.json` must agree on the latest benchmark revision.

- `benchmark_review_manifest.json` should remain consistent with the current
  render bundle if rendered evidence is present.

- Use Build123d primitives only.

- Keep the benchmark review package import-safe and deterministic.

- Reject the package if the redirection path is not credible for the seeded
  ball envelope.
