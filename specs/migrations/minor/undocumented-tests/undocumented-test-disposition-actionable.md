---
title: Undocumented Integration Test Disposition
status: migration
agents_affected:
  - benchmark_planner
added_at: '2026-03-31T12:24:08Z'
---

# Undocumented Integration Test Disposition

This document is the execution plan for the `UNDOC-###` inventory in
[undocumented-test-list.md](./undocumented-test-list.md).

Disposition terms:

- `Promote` means the test should gain a canonical `@pytest.mark.int_id(...)`
  marker and a row in [integration-test-list.md](./integration-test-list.md).
- `Merge` means the assertions should be folded into a different canonical test
  or a smaller consolidated test and the standalone function should stop
  existing as separate coverage.
- `Remove` means the check is too implementation-specific, noisy, or duplicate
  to justify integration coverage.
- When a check is explicitly fail-closed, prefer a future `INT-NEG-###` row
  instead of keeping the failure path in the positive catalog.

Publication pruning already removed the support/eval tail from the published
catalog. Any row below that points at a pruned `INT-xxx` target is historical
lineage only, even if the action text still says Promote or Merge.

| UNDOC IDs | Source family | Action | Recommended tier | Target / note |
| -- | -- | -- | -- | -- |
| UNDOC-001, UNDOC-004, UNDOC-005, UNDOC-008, UNDOC-015 | `dataset/evals/run_evals.py` CLI surface and parser smoke checks | Merge | P2 | Collapse into one runner CLI contract. These are useful guardrails, but they are not release blockers and should not occupy P0 as separate tests. |
| UNDOC-002, UNDOC-003, UNDOC-009, UNDOC-010, UNDOC-016, UNDOC-017 | Eval bootstrap and workspace determinism | Promote | P1 | Keep these as canonical runner/workspace contracts. They are integration-relevant because they prove the eval profile ignores outer integration state and materializes deterministic workspaces. |
| UNDOC-011, UNDOC-012, UNDOC-013, UNDOC-014 | Headless validation and submit-helper fallback behavior | Promote + merge | P1 | Use `UNDOC-014` as the canonical headless fallback anchor and merge `UNDOC-011` through `UNDOC-013` into it. `UNDOC-014` is the one worth carrying as a canonical contract. |
| UNDOC-018, UNDOC-019, UNDOC-020, UNDOC-021, UNDOC-022 | Seed maintenance and manifest hash repair utilities | Merge | P2 | Fold into a single seed-maintenance contract. These checks protect tooling, not the product runtime path. |
| UNDOC-023, UNDOC-024, UNDOC-025 | Trace capture, artifact separation, and integration-mode smoke | Merge | P2 | Keep one trace-capture contract and one controller integration-mode smoke check if still needed. None of these are P0 release gates. |
| UNDOC-026, UNDOC-027 | Shared template parity | Merge | P2 | Fold into one template-sync contract. The current pair is duplicate fixture verification. |
| UNDOC-028 | Worker light websocket transport round trip | Promote | P2 | Keep as a single transport-boundary regression if websocket support is still a supported mode. It belongs below P0. |
| UNDOC-029 | Multitenancy repro | Remove or merge | P2 | Prefer removal unless the isolation behavior is still failing in practice. If kept, fold it into the session-isolation / concurrent-run coverage rather than keeping a separate reproduction test. |
| UNDOC-030, UNDOC-031 | Schemathesis fuzzing | Remove | P2 | The fuzzing family was pruned from the publication bundle; keep it only in a non-publication diagnostics track if needed. |
| UNDOC-032 | Benchmark planner -> CAD -> reviewer path | Promote | P1 | Promote directly to `INT-031`. This is canonical benchmark-generation coverage and should stay in the main integration catalog. |
| UNDOC-033 | Unsolvable benchmark bundle rejection | Remove | P1 | This is a fail-closed branch; document it in the negative catalog instead of the positive bundle. |
| UNDOC-034 | Invalid benchmark objective requests | Merge | P2 | Fold into the benchmark validation gate (`INT-008`) or the future negative catalog. The current function is a thin validation-only check. |
| UNDOC-035, UNDOC-036, UNDOC-037 | Dataset export round-trip and invalid lineage rejection | Remove | P1 | The dataset export family was pruned from the publication bundle; keep it only if a non-publication replay track still needs it. |
| UNDOC-038 | Engineering full loop | Promote | P1 | Promote directly to `INT-033`. This is real end-to-end engineer workflow coverage and belongs in canonical integration. |
| UNDOC-039 | Retry preserves benchmark linkage | Remove | P1 | Retry lineage was pruned from the publication bundle; if it must survive, document it in the negative catalog instead of the positive bundle. |
| UNDOC-040 | Failed episode replay bundle | Remove | P1 | Replayability of failed episodes was pruned from the publication bundle; archive only. |
| UNDOC-041 | Benchmark-to-engineer handoff package | Promote | P1 | Promote directly to `INT-032`. This is a real handoff bundle contract, not a helper test. |
| UNDOC-042, UNDOC-043, UNDOC-044 | Render artifact generation and media inspection | Promote + merge | P1 | Promote `UNDOC-042` to `INT-039`, merge `UNDOC-043` into it as the objective-box assertion, and merge `UNDOC-044` into the reviewer-media-inspection coverage. |
| UNDOC-045 | Asset persistence linkage | Promote | P1 | Promote directly to `INT-040`. The DB/S3 linkage contract is a canonical integration boundary. |
| UNDOC-046 | MJCF joint mapping | Promote | P1 | Promote directly to `INT-037`. This belongs with the core export/simulate path. |
| UNDOC-047 | Controller function family coverage | Promote | P1 | Promote directly to `INT-038`. This is still a real runtime-mode contract. |
| UNDOC-048 | Temporal recovery path | Remove | P1 | Temporal recovery was pruned from the publication bundle; archive only. |
| UNDOC-049 | Async callbacks / webhook completion | Remove | P1 | Async callback coverage was pruned from the publication bundle; archive only. |
| UNDOC-050, UNDOC-051, UNDOC-052 | Manufacturing workbench methods, unknown material rejection, and quantity economics | Merge | P1 | Keep one supported-methods contract (`INT-036`) and one negative material contract. Merge `UNDOC-052` into the pricing contract (`INT-010`) if the quantity economics assertion still matters. |
| UNDOC-053, UNDOC-055 | COTS provenance and round-trip enrichment | Promote | P1 | Promote both to the canonical COTS reproducibility contract (`INT-064`). These are straight coverage gaps, not separate feature flags. |
| UNDOC-054, UNDOC-056 | COTS / manufacturing fail-closed branches | Merge | P1 | Keep the fail-closed behavior, but move it into the canonical validation path or the future negative catalog. These are negative cases, not primary release gates. |
| UNDOC-057, UNDOC-058 | Render validation seed brightness checks | Remove | P2 | The render-validation seed brightness checks were pruned from the publication bundle; archive only. |
| UNDOC-059 | Reviewer evidence completeness | Promote | P1 | Promote directly to `INT-034`. This is the canonical reviewer evidence contract. |
| UNDOC-060 | Canonical DOF evidence keys | Merge | P1 | Fold into the existing DOF reviewer gates (`INT-074` and `INT-075`) rather than keeping a separate evidence-only test. |
| UNDOC-061 | Over-actuated DOF rejection after render inspection | Promote | P1 | Promote directly to `INT-075`. The render-inspection-before-rejection path is the useful regression. |
| UNDOC-062, UNDOC-065 | Preview evidence path acceptance | Merge | P1 | Fold into the reviewer evidence contract (`INT-034`) or the execution-reviewer handoff contract. These are acceptance subcases, not standalone flows. |
| UNDOC-063 | Benchmark plan rejection with latest revision evidence | Remove | P1 | This reviewer rejection branch was pruned from the publication bundle; keep it only if a negative row is explicitly added later. |
| UNDOC-064 | Approval requires media inspection | Remove | P1 | This reviewer-quality branch was pruned from the publication bundle; keep it only if a negative row is explicitly added later. |
| UNDOC-066, UNDOC-067, UNDOC-068, UNDOC-069, UNDOC-070, UNDOC-071, UNDOC-072 | Evaluation and dataset materialization regressions | Remove | P2 | The P2 eval family was pruned from the publication bundle; archive only. |
