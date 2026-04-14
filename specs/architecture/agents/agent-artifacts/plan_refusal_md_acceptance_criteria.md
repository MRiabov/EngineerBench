# plan_refusal.md Acceptance Criteria

## Role of the File

`plan_refusal.md` is the structured refusal proof for infeasible plans.
It is worth being a dedicated artifact because a coder must be able to reject an approved plan for concrete infeasibility without weakening the handoff contract or inventing an alternate pass.

## Hard Requirements

- The file names concrete evidence for the refusal.
- The file states the role-specific reason clearly.
- The file does not weaken the contract or invent alternate passes.
- The file matches the current revision and seeded artifacts.

## Quality Criteria

- The refusal is narrow, evidence-backed, and tied to the approved plan.
- The document explains why the plan is infeasible rather than why the implementation was merely inconvenient.
- The evidence is specific enough that a reviewer can confirm the refusal without reconstructing the whole workspace by hand.

## Reviewer Look-Fors: File Antipatterns to Look For

- Generic objections replace concrete infeasibility evidence.
- The refusal tries to reinterpret the plan instead of refusing the approved contract.
- The file is stale or refers to artifacts that are not part of the current revision.
- The refusal hides a coding failure behind a plan-level excuse.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/roles.md`
