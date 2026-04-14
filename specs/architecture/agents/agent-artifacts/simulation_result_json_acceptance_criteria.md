# simulation_result.json Acceptance Criteria

## Role of the File

This file captures the latest-revision deterministic simulation evidence.
It is worth being a dedicated artifact because moving benchmarks and motion-sensitive solution reviews need a current, machine-readable record of the actual simulated outcome.

## Hard Requirements

- The file reflects the current revision only.
- The file is schema-valid and parseable.
- The file matches the seeded workspace state and motion contract.
- The file explains success or failure without relying on stale evidence.
- When benchmark payload simulation uses an observation window from `config/agents_config.yaml` (`benchmark_payload_observation.window_s`, default `1.5s`), the file records the configured window and whether any payload out-of-bounds occurred before or after it.

## Quality Criteria

- The file gives reviewers enough motion detail to understand what the simulation proved.
- The result is attributable to the current revision and not to a prior run.
- The record is specific enough to compare against renders, trajectory proofs, and validation output.
- The record distinguishes early payload failure from late payload drift when benchmark payload observation is windowed.

## Reviewer Look-Fors: File Antipatterns to Look For

- The simulation result comes from a stale bundle or a different revision.
- The file says the solution succeeded while the motion evidence or render bundle shows a mismatch.
- Motion-sensitive fields are missing, approximate, or left to inference.
- The record cannot explain why the run passed or failed without extra guesswork.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/simulation-and-rendering.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
