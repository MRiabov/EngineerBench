# benchmark_definition.yaml Acceptance Criteria

## Role of the File

`benchmark_definition.yaml` is the benchmark-owned contract for task geometry, objective zones, randomization, environment assumptions, and customer caps.
It is worth being a first-class agent artifact because downstream roles, validators, and eval seeds all need the same exact geometry and bounds, not a paraphrase.

## Hard Requirements

- The file schema-validates before execution continues.
- Goal-zone, forbid-zone, and build-zone geometry are exact and internally consistent; each objective zone must span at least 3 mm on its largest axis or validation fails closed.
- The payload has a top-level `start_position`, stable labels, and a `material_id` that resolves to a known material from `manufacturing_config.yaml`.
- The payload’s declared start pose is collision-free against benchmark-owned fixture geometry; startup overlap is a hard validation failure.
- The line from `payload.start_position_mm` to the bottom center of
  `objectives.goal_zone_mm` is steep enough for gravity-driven motion: the
  spawn-to-goal angle must meet the configured
  `benchmark_solvability.minimum_payload_to_goal_angle_deg` threshold, and
  the goal/build/forbid zones themselves must each remain above the 3 mm
  objective-zone sanity floor.
- The payload contract stays explicit enough for the runtime to apply the benchmark-payload observation window from `config/agents_config.yaml` (`benchmark_payload_observation.window_s`, default `1.5s`) without guessing hidden benchmark behavior.
- Deprecated aliases `moved_part`, `moving_part`, and `moved_object` are not valid forward-contract names for this artifact.
- Static and runtime randomization ranges are exact, bounded, and materialized at seed time.
- Benchmark caps, estimate fields, and other numeric fields are exact, not deferred to later inference.
- Any benchmark-owned moving fixture is declared explicitly and remains motion-visible to downstream roles.
- The file contains no placeholders, invented identifiers, or unstated benchmark fixtures.

## Quality Criteria

- The contract creates a real challenge without hidden contradictions or degenerate geometry.
- The randomization is bounded enough to remain reproducible and broad enough to exercise robustness.
- Exact identifiers are repeated across the handoff package so later roles do not have to guess names or counts.
- The geometry and cap data are legible enough that reviewers can reason about benchmark validity and challenge level without reconstructing intent from scratch.

## Reviewer Look-Fors: File Antipatterns to Look For

- Goal, forbid, and build geometry intersect the payload at spawn or after stated randomization, and any objective zone smaller than 3 mm on its largest axis is rejected before review.
- Benchmark-owned fixture geometry intersects the payload at its declared start_position before runtime jitter is applied.
- The benchmark definition omits or contradicts the payload start pose / goal objective needed for the observation-window contract.
- `payload.material_id` is missing, empty, or unknown to `manufacturing_config.yaml`.
- Runtime or static randomization pushes the object out of bounds or into an impossible start state.
- The benchmark definition relies on late rescue behavior to stay valid instead of declaring a clear start pose and goal objective.
- The payload spawn-to-goal line is too shallow relative to the goal-zone bottom center for gravity-driven motion.
- Hidden benchmark motion or unsupported fixture declarations appear in the file.
- Cap, estimate, or label drift appears across the handoff package.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/definitions-of-success-and-failure.md`
- `specs/architecture/evals-architecture.md`
