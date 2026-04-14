# benchmark_plan_evidence_script.py Acceptance Criteria

## Role of the File

This script is the inspectable source for the benchmark geometry evidence scene.
It is worth being a dedicated artifact because reviewers and downstream engineer intake need a legible, runnable preview of the benchmark plan intent, not just a YAML summary.

## Hard Requirements

- The script is grounded in the benchmark contract.
- The script preserves inventory labels and quantities exactly.
- The script does not drift into solution-side geometry or invented benchmark objects.
- The script is suitable for visual inspection and preview generation by downstream roles.

## Quality Criteria

- The evidence scene is simple enough to inspect but complete enough to reveal the benchmark geometry clearly.
- The script makes the benchmark intent legible without hiding the inventory in opaque helper logic.
- The same authored labels and counts appear in the plan, the draft YAML, and the evidence scene.

## Reviewer Look-Fors: File Antipatterns to Look For

- The script renames, drops, or duplicates benchmark-owned labels or quantities.
- Solution-side geometry appears in the benchmark evidence scene.
- The script is too opaque for review or reconstructs the contract differently from the YAML.
- The evidence scene no longer matches the current revision of the benchmark handoff package.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/roles.md`
