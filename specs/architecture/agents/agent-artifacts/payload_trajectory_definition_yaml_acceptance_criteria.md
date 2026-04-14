# payload_trajectory_definition.yaml Acceptance Criteria

## Role of the File

`payload_trajectory_definition.yaml` is the engineer-owned higher-resolution path and contact proof.
It refines the coarse motion forecast rather than replacing it, and it should support backend-specific contact evidence and preview overlays.
It is worth being a dedicated artifact because reviewers need a strict motion proof, not just a planner summary.

## Hard Requirements

- The file schema-validates and parses cleanly.
- The file contains no template placeholders or empty stub values.
- `backend` and `initial_pose` are present and consistent with the implementation backend.
- `moving_part_names` match the approved coarse motion forecast.
- `sample_stride_s` does not exceed the coarse motion forecast stride and stays within the motion cadence budget from `config/agents_config.yaml`.
- Ordered motion anchors include explicit positions, explicit `rot_deg` orientation, and tolerance data when an envelope is intentional.
- The first anchor lies within `benchmark_definition.objectives.build_zone` and explicitly sets `build_zone_valid: true`.
- `initial_pose` matches the first anchor pose and reference point.
- The file proves the terminal goal-zone entry or contact in the last anchor or `terminal_event`, not both.
- If `terminal_event` is used, its `zone_name` is `goal_zone`, its `contact_surfaces` are populated, and its position lies within the goal zone.
- The file remains swept-clearance safe against fixed geometry for every admitted rotation at each checked step.
- The file remains consistent with `benchmark_definition.yaml`, the approved coarse forecast, and any benchmark motion evidence in the workspace.

## Quality Criteria

- The path is precise enough to support contact proof while still remaining readable and reviewable.
- The motion trace tells the same story as the plan math and the coarse forecast.
- The proof is explicit about the safe start, the waypoint order, and the terminal goal contact.
- The admissible rotation domain is explicit instead of implied.

## Reviewer Look-Fors: File Antipatterns to Look For

- The file merely copies the coarse forecast without adding the required precision or terminal proof.
- The build-safe start or goal-contact finish semantics are contradicted or loosened.
- The moving part names, cadence, or terminal event drift from the approved motion contract.
- A step omits rotation metadata or leaves the swept-clearance domain under-proven.
- The path is physically implausible, impossible, or inconsistent with the benchmark evidence.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/simulation-and-rendering.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/definitions-of-success-and-failure.md`
