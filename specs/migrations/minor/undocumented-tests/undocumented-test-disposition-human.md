---
title: Undocumented Integration Test Review
status: migration
agents_affected: []
added_at: '2026-03-31T12:24:08Z'
---

# Undocumented Integration Test Review

This is the readable companion to the action matrix in
[undocumented-test-disposition-actionable.md](./undocumented-test-disposition-actionable.md).
It explains why the undocumented integration inventory should be split across
promotion, merge, removal, and priority demotion.

The publication-shape prune already removed the support/eval tail from the
canonical catalog. What remains is a smaller set of core workflow contracts, a
set of fail-closed branches that should move to `INT-NEG-###`, and a set of
archival rows that should not come back into the publication bundle.

The main rule is simple: P0 should stay reserved for release blockers. A test
belongs there only when a failure means the product path is broken, unsafe, or
unusable. A lot of the undocumented inventory is valuable, but it is not P0.
Those checks belong in P1 or P2, or they should be merged into a broader
canonical contract so the suite stops paying for the same assertion multiple
times.

## What Should Leave P0

### Runner CLI and eval bootstrap

The runner-mode tests in the `run_evals.py` family are the most obvious source
of P0 pollution. The `--help` assertions, parser-default checks, sandbox flag
checks, and repeated level-filter parsing are all useful, but they are not
release blockers. They validate support tooling and command-line ergonomics,
which is exactly why they are better treated as archival or merge-only rows
after publication pruning.

That is why `UNDOC-001`, `UNDOC-004`, `UNDOC-005`, `UNDOC-008`, and
`UNDOC-015` should collapse into one lower-tier runner CLI contract. The same
logic applies to the workspace and environment setup checks: `UNDOC-002`,
`UNDOC-003`, `UNDOC-009`, `UNDOC-010`, `UNDOC-016`, and `UNDOC-017` are
important enough to keep, but they belong in P1 as a consolidated runner
bootstrap/workspace contract rather than as a pile of P0 helpers.

The headless-display and submit-helper tests are a separate case. `UNDOC-011`,
`UNDOC-012`, `UNDOC-013`, and `UNDOC-014` are really the same contract from
different angles: validate and submit must still work when the host display is
bad or absent. `UNDOC-014` is the only one that deserves to survive as the
canonical anchor, and the others should be merged into it if the branch stays
in the publication bundle.

### Seed maintenance and trace helpers

`UNDOC-018` through `UNDOC-022` are seed-maintenance and manifest-repair
utilities. They are not product-path gates. They should become a compact P2
contract around re-materializing workspaces, validating curated seed rows, and
repairing manifest hash drift.

The same applies to `UNDOC-023` and `UNDOC-024`. Those are trace-capture and
artifact-separation checks. They are useful for debugging, but they are not
release blockers. `UNDOC-025`, `UNDOC-026`, `UNDOC-027`, `UNDOC-028`, and
`UNDOC-029` are also support concerns: integration-mode smoke, template parity,
websocket transport, and a multitenancy reproduction. None of those justify a
P0 slot, and the publication bundle no longer needs to pretend they are core
product claims.

## What Should Be Promoted Instead of Repeated

### Core workflow contracts

The workflow-oriented tests starting at `UNDOC-030` are mostly the opposite of
the runner helpers. They cover real product boundaries: benchmark generation,
engineering execution, handover packaging, artifact persistence, and reviewer
evidence.

Most of them now map cleanly to the retained canonical IDs:

- `UNDOC-032` should become `INT-031`.
- `UNDOC-038` should become `INT-033`.
- `UNDOC-041` should become `INT-032`.
- `UNDOC-042` should become `INT-039`.
- `UNDOC-045` should become `INT-040`.
- `UNDOC-046` should become `INT-037`.
- `UNDOC-047` should become `INT-038`.
- `UNDOC-050` should become `INT-036`.
- `UNDOC-053` and `UNDOC-055` should become `INT-064`.
- `UNDOC-059` should become `INT-034`.
- `UNDOC-061` should become `INT-075`.
- `UNDOC-062` and `UNDOC-065` should fold into `INT-034` or the execution-reviewer handoff contract.
- `UNDOC-030`, `UNDOC-039`, `UNDOC-040`, `UNDOC-048`, and `UNDOC-049` are no longer publication targets after pruning and should stay out of the trimmed bundle unless a separate negative or archival track needs them.

The important distinction is that these are not random assertions. They prove
that the system still moves across controller, worker, Temporal, and storage
boundaries. They belong in the canonical catalog even if they do not belong in
P0.

### Negative cases

Several tests are really negative or fail-closed cases. They should not stay in
the positive catalog just because they currently live there.

Examples:

- `UNDOC-033` is a solvability rejection path and belongs in the negative
  catalog.
- `UNDOC-034`, `UNDOC-037`, `UNDOC-051`, `UNDOC-054`, `UNDOC-056`,
  `UNDOC-057`, `UNDOC-063`, and `UNDOC-064` are fail-closed branches that are
  better suited to `INT-NEG-###` or to a merged validation contract.
- The older positive rows that used to stand in for those branches (`INT-203`,
  `INT-204`, `INT-205`, and `INT-206`) are already pruned from the publication
  bundle.

The reason is structural, not stylistic. Positive catalog rows should stay
focused on the happy-path contract. When the important behavior is "reject,
deny, or fail closed", the negative namespace keeps the suite easier to read and
reduces pressure to turn every rejection into a P0 success test.

## What Should Be Merged

Some tests are simply narrower views of a broader contract and should not keep
their own standalone coverage.

- `UNDOC-031` is a duplicate fuzzing path and should fold into `UNDOC-030` if
  the fuzzing track is kept internally.
- `UNDOC-036` should fold into the dataset export round-trip contract created
  for `UNDOC-035` if that family survives outside the publication bundle.
- `UNDOC-043` and `UNDOC-044` are subcases of render/reviewer evidence
  handling, not separate features.
- `UNDOC-050`, `UNDOC-051`, and `UNDOC-052` are all manufacturing economics
  variants and should live under the supported workbench and pricing contracts.
- `UNDOC-060`, `UNDOC-062`, and `UNDOC-065` are evidence-shape regressions that
  belong inside the reviewer-gate contracts rather than as separate tests.

The same pattern appears in the lighter-weight helper families:

- `UNDOC-001`, `UNDOC-004`, `UNDOC-005`, `UNDOC-008`, and `UNDOC-015` should
  become one runner CLI contract.
- `UNDOC-018` through `UNDOC-022` should become one seed-maintenance contract.
- `UNDOC-023` through `UNDOC-027` should be collapsed to the minimum useful
  trace/template smoke coverage.

This is the fastest way to cut noise without losing signal.

## What Can Be Removed

`UNDOC-006`, `UNDOC-029`, and any helper-only assertion that does not cross a
real runtime boundary are candidates for removal if the merged canonical test
already covers the same behavior.

The publication-pruned P2 eval rows `UNDOC-066` through `UNDOC-072` are also
removal candidates unless a non-publication analytics track explicitly asks
for them.

That is especially true when the test is:

- asserting a string shape instead of a runtime contract,
- inspecting a helper function that is already indirectly exercised elsewhere,
- or verifying a reproduction that no longer corresponds to an active bug.

If a test can be removed without losing observable boundary coverage, that is
preferable to keeping it around as a low-value P0 residue.

## Bottom Line

### Observability and reviewer evidence

`UNDOC-053` through `UNDOC-056` are still real integration checks, but they are
observability and storage-durability contracts, not user-facing launch gates.
The lifecycle and upload logging behavior is worth keeping canonical, yet the
failure-injection variant is the one most likely to slide down into P1 if the
same retry path is already covered elsewhere.

`UNDOC-059` through `UNDOC-065` are the same story with reviewer evidence. The
canonical evidence contract matters because the reviewer path depends on it,
but the individual media-inspection and preview-evidence variants are narrower
than the parent gate. They should be merged upward instead of keeping separate
P0 rows.

The inventory should converge to three shapes:

1. Core product gates that stay in P0 or P1 after pruning.
2. Explicit negative paths that move to `INT-NEG-###`.
3. Archival support and eval rows that stay out of the publication bundle.

That keeps the integration catalog honest and brings the P0 suite back to
being the smallest genuinely release-blocking set.
