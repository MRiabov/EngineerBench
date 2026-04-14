## 1. Learning Objective

Review a lower-bin redirection benchmark package that steepens the deflector
and raises the dead-zone shield until the capture path starts to look
unreachable.

## 2. Geometry

- `upper_start_ledge`: release ledge.
- `deflector_ramp`: aggressive redirection ramp.
- `direct_drop_shield`: dead-zone shield.
- `lower_bin`: final capture bin.

## 3. Objectives

- Verify the lower-bin path stays physically plausible.
- Reject any geometry that forces a direct drop through the dead zone.
- Keep the benchmark package internally consistent across geometry, validation,
  and simulation evidence.

## 4. Review Artifacts

- `benchmark_script.py`, `validation_results.json`, and
  `simulation_result.json` must agree on the latest benchmark revision.
- `benchmark_review_manifest.json` should remain consistent with the current
  render bundle if rendered evidence is present.

## 5. Implementation Notes

- Use Build123d primitives only.
- Keep the benchmark review package import-safe and deterministic.
- Reject the package if the redirection path is not credible for the seeded
  ball envelope.
