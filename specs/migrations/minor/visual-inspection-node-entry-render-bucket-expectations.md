---
title: Visual Inspection Node-Entry Render Bucket Expectations
status: migration
agents_affected:
  - benchmark_planner
  - benchmark_plan_reviewer
  - benchmark_coder
  - benchmark_reviewer
  - engineer_planner
  - engineer_plan_reviewer
  - engineer_coder
  - engineer_execution_reviewer
added_at: '2026-04-21T00:00:00Z'
---

# Visual Inspection Node-Entry Render Bucket Expectations

<!-- Migration tracker. No behavior change yet. -->

## Purpose

This migration makes the node-entry render-bucket contract explicit in
`config/agents_config.yaml` under each role's `visual_inspection` policy, and
teaches node-entry validation to fail closed against that declared bucket set.

The target architecture already says visual-inspection policy is config-driven,
and the render-bucket split is already documented in the architecture and seed
helpers. What is still missing is a canonical policy field that says which
persistent render buckets must already exist when a role enters a node.

This is a contract migration, not a render-bucket rename. The bucket names
already exist, and the current render-routing helpers already use the same
stage-prefix order. The missing piece is a typed policy field plus a node-entry
gate that reads it.

## Problem Statement

The current render-bucket contract is split across helper code, permissions,
and prose:

1. `worker_renderer/utils/rendering.py` and `scripts/internal/eval_seed_renders.py`
   already encode the stage-prefix bucket order.
2. `config/agents_config.yaml` already grants read/write access to render
   buckets, but the `visual_inspection` policy does not say which buckets must
   exist on node entry.
3. `controller/agent/node_entry_validation.py` can validate artifacts and
   handover manifests, but it has no typed bucket list to compare against the
   current workspace.
4. The result is an implicit contract: the runtime knows the bucket names, but
   the policy file does not say which persistent render buckets belong to the
   entered stage.
5. That makes stale or missing bucket state easy to miss, especially when a
   workspace is reused across stages that accumulate render evidence.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `config/agents_config.yaml` | `visual_inspection` only carries `required`, `min_images`, and `reminder_interval`. Bucket expectations are implicit in permissions and helper code. | The policy needs an explicit node-entry bucket list next to the existing visual-inspection knobs. |
| `shared/agents/config.py` | `VisualInspectionPolicy` does not model an entry bucket list, so the config schema cannot validate it. | The policy model must own the new field so config parsing stays typed and fail-closed. |
| `controller/agent/node_entry_validation.py` | Node-entry validation checks required artifacts and custom handover checks, but it cannot compare workspace render buckets against a role-specific policy list. | Entry validation needs to reject missing or unexpected persistent render buckets. |
| `tests/integration/architecture_p0/test_eval_seed_renders.py` | The seeded-render helper already asserts the stage-prefix render-bucket order in code. | The config field must match this existing order so seed refresh and node entry do not diverge. |
| `tests/integration/architecture_p0/test_node_entry_validation.py` | Has current-role and starter-template regressions, but no render-bucket expectation regression. | The new policy field needs a direct entry-validation test. |
| `tests/integration/architecture_p0/test_int_190_benchmark_coder_permissions.py` | Checks visual-inspection flags and filesystem scope. | It should also assert the explicit render-bucket list in the visual-inspection policy. |
| `specs/architecture/agents/handover-contracts.md` and `specs/architecture/evals-architecture.md` | They describe expected render state in prose, but not the new typed bucket list. | The docs need to name the new policy field so the config contract stays canonical. |

## Proposed Target State

1. Every `visual_inspection` policy in `config/agents_config.yaml` includes an
   `entry_expects_render_buckets` list.
2. The field is required and canonical. A missing or malformed list is a schema
   error, not an implied empty list.
3. The field describes the exact persistent render bucket set that should
   already exist when the node starts. It does not replace read permissions.
4. The current stage-prefix order is made explicit in config:
   - `benchmark_planner`: `[]`
   - `benchmark_plan_reviewer`, `benchmark_coder`, `benchmark_reviewer`,
     `engineer_planner`: `["benchmark_renders"]`
   - `engineer_plan_reviewer`, `engineer_coder`:
     `["benchmark_renders", "engineer_plan_renders"]`
   - `engineer_execution_reviewer`:
     `["benchmark_renders", "engineer_plan_renders", "final_solution_submission_renders"]`
5. Node-entry validation compares the workspace against that exact list and
   fails closed when an expected persistent bucket is missing, when an
   unexpected persistent bucket is present, or when the bucket's bundle-local
   `render_manifest.json` is absent or invalid.
6. The helper surfaces that already use the same stage-prefix order remain
   aligned with the policy field; this migration does not change the bucket
   names or the render generation model.

## Required Work

### 1. Extend the visual-inspection policy schema

- Add `entry_expects_render_buckets` to `VisualInspectionPolicy` in
  `shared/agents/config.py`.
- Parse it as a canonical list of bucket names under `renders/`.
- Reject missing, malformed, or unknown bucket names so the policy cannot
  silently degrade to an empty expectation.

### 2. Populate the policy in config

- Add `entry_expects_render_buckets` under every `visual_inspection` block in
  `config/agents_config.yaml`.
- Use the stage-prefix mapping already reflected by the seeded-render helper.
- Keep `benchmark_planner` explicitly empty and keep the later-stage lists
  cumulative.

### 3. Enforce the exact bucket contract at node entry

- Update `controller/agent/node_entry_validation.py` so each node contract
  carries the expected render-bucket list from the role policy.
- Compare the current workspace against the exact persistent bucket set for the
  entered role.
- Fail closed if a required bucket is missing, if an unexpected persistent
  bucket is present, or if an expected bucket does not contain a valid render
  bundle manifest.

### 4. Keep helper surfaces aligned

- Keep the existing render-routing helpers and seeded-render refresh order
  aligned with the same stage-prefix contract.
- Do not introduce a second bucket mapping source.
- Treat the config field as the canonical policy entry, and use the helpers as
  consumers of that contract.

### 5. Refresh tests and docs

- Add coverage that asserts the explicit config field exists and matches the
  stage-prefix mapping.
- Add a node-entry regression that fails when an expected bucket is missing or
  stale.
- Update the handover and eval architecture docs so they name
  `entry_expects_render_buckets` instead of describing the bucket contract only
  in prose.

## Non-Goals

- Do not rename `benchmark_renders`, `engineer_plan_renders`, or
  `final_solution_submission_renders`.
- Do not change `renders/current-episode/`.
- Do not change `inspect_media(...)`, `visual_inspection.min_images`, or the
  reminder cadence.
- Do not change the seeded-render stage order or the existing render-routing
  helpers.
- Do not infer bucket expectations from filesystem permissions alone.

## Sequencing

The safe order is:

1. Add the schema field and config entries.
2. Teach node-entry validation to consume the field.
3. Refresh the render-bucket regression tests.
4. Update the docs once the contract is stable.

## Acceptance Criteria

1. Every `visual_inspection` block has an explicit `entry_expects_render_buckets`
   list.
2. The node-entry gate rejects a workspace when a required persistent bucket is
   missing, stale, or invalid.
3. The stage-prefix mapping in config matches the existing render-refresh order
   used by seeded renders.
4. `benchmark_planner` remains the only role with an empty expected-bucket
   list.
5. The integration suite proves that render-bucket expectations are coming from
   the config policy, not from permissions or prompt prose.

## Migration Checklist

### Policy schema

- [x] Add `entry_expects_render_buckets` to `VisualInspectionPolicy`.
- [x] Make the field required and canonical in config parsing.

### Config population

- [x] Add the explicit bucket list to every `visual_inspection` block in
  `config/agents_config.yaml`.
- [x] Keep the stage-prefix bucket order unchanged.

### Validation

- [x] Teach node-entry validation to compare the exact persistent bucket set
  against the role policy.
- [x] Fail closed on missing, unexpected, or malformed bucket bundles.

### Tests and docs

- [x] Add config-level regression coverage for the explicit bucket lists.
- [x] Add node-entry regressions for missing and stale bucket bundles.
- [x] Update the relevant architecture docs to name the new field.

## File-Level Change Set

The implementation should touch the smallest set of files that actually enforce
the new contract:

- `config/agents_config.yaml`
- `shared/agents/config.py`
- `controller/agent/node_entry_validation.py`
- `tests/integration/architecture_p0/test_eval_seed_renders.py`
- `tests/integration/architecture_p0/test_node_entry_validation.py`
- `tests/integration/architecture_p0/test_int_190_benchmark_coder_permissions.py`
- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/tools.md`
- `specs/architecture/evals-architecture.md`
