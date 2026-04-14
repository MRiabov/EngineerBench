# Motion Trajectory Contract

Motion and payload trajectories must always be described and justified with formulas, not merely described in prose.

Use this reference to structure any motion or payload trajectory derivation.

For the file-level acceptance criteria that sit underneath the planner handoff, also read `specs/architecture/agents/agent-artifacts/README.md` and the matching contracts for `engineering_plan.md`, `todo.md`, `assembly_definition.yaml`, `solution_plan_evidence_script.py`, and `payload_trajectory_definition.yaml`.

## Scope

- Keep `assembly_definition.yaml.motion_forecast` sparse and ordered.
- Do not turn the planner contract into a timestep replay.
- Use this document for the calculation structure that makes each anchor reviewable.

## Required Inputs

- Source geometry and any fixed datums
- The moving part chain, joint axes, or passive transfer surfaces
- The payload reference point used for the forecast
- Build zone and goal zone limits
- Runtime jitter and contact uncertainty
- Friction, mass, inertia, actuator limits, or other physics inputs when they affect the claim

## Required Calculations

1. State the coordinate frame and reference point used for the derivation.
2. Derive the nominal payload path from the actual mechanism geometry.
3. Show how each anchor in `motion_forecast` follows from formulas, not prose.
4. Compute the first-anchor build-zone check.
5. Compute the terminal goal-zone proof.
6. Derive timing estimates and contact-order windows for each anchor.
7. Check clearance, load, acceleration, and dwell constraints when they affect feasibility.
8. Justify each tolerance band against runtime jitter and contact uncertainty.
9. List assumptions, approximation limits, and failure cases.

## Acceptance Standard

- Every binding numeric claim in the motion forecast must be traceable to the calculations above.
- If a required input is missing, stop and surface the missing value instead of estimating it.
- Prose-only trajectory estimates are not sufficient.
- The refined path, if present, must remain consistent with the coarse planner forecast.
