---
title: Integration Test Negative-Path Migration Matrix
status: migration
agents_affected: []
added_at: '2026-03-31T07:10:09Z'
---

# Integration Test Negative-Path Migration Matrix

This document maps the fail-closed cases that should leave the positive
catalog after the publication-shape prune. The positive
`specs/integration-test-list.md` rows have already shed their support/eval
tail, so the negative-path split below is the authoritative home for
deterministic rejection, refusal, fail-closed, and crash-containment
coverage.

Heuristic used here:

- `@pytest.mark.allow_backend_errors(...)` is treated as a strong negative-path
  signal unless the test is clearly a success-path contract or a special
  boundary case.
- `INT-xxx` stays success-oriented.
- `INT-NEG-###` is the target for deterministic rejection, refusal, fail-closed,
  and crash-containment coverage.

The suggested `INT-NEG` numbers below are provisional and ordered to minimize
churn when the suite is split.

## Recommended migrations

### `tests/integration/architecture_p0/test_planner_gates.py`

| Proposed ID | Current test | Why it moves |
| -- | -- | -- |
| `INT-NEG-001` | `test_int_005_mandatory_artifacts_gate` | Mandatory artifact rejection is fail-closed coverage, not a success path. |
| `INT-NEG-002` | `test_int_006_plan_structure_validation` | Invalid `plan.md` structure is a deterministic negative case. |
| `INT-NEG-003` | `test_int_007_todo_integrity` | Invalid todo markup and incomplete items are rejection coverage. |
| `INT-NEG-004` | `test_int_008_objectives_validation` | Template placeholders, schema drift, and extra fields are negative-path validation. |
| `INT-NEG-005` | `test_int_009_cost_estimation_validation` | Placeholder/schema failures belong in the negative suite. |
| `INT-NEG-006` | `test_int_011_planner_caps_enforcement` | Planner-cap overflow is explicit fail-closed validation. |
| `INT-NEG-007` | `test_int_015_engineer_handover_immutability` | Handover mutation detection is an integrity rejection. |
| `INT-NEG-008` | `test_int_018_submit_handoff_rejects_forbidden_environment_drilling` | Forbidden drilling is a direct handoff refusal. |
| `INT-NEG-009` | `test_int_010_submit_handoff_rejects_missing_benchmark_drilling_cost` | Missing drilling-cost accounting is a rejection path. |
| `INT-NEG-010` | `test_int_023_submit_handoff_rejects_forbidden_benchmark_attachment_joint` | Non-attachable benchmark joints are a fail-closed gate. |
| `INT-NEG-011` | `test_int_010_planner_pricing_script_integration` | Over-cap pricing should live with negative pricing gates. |
| `INT-NEG-012` | `test_int_010_handoff_rejects_low_quantity_that_only_passes_at_volume` | Requested-quantity manufacturability failure is negative-path coverage. |
| `INT-NEG-013` | `test_int_018_validate_and_price_integration_gate` | Missing/stale validate-and-price state is a gating failure. |

### `tests/integration/architecture_p0/test_node_entry_validation.py`

| Proposed ID | Current test | Why it moves |
| -- | -- | -- |
| `INT-NEG-014` | `test_int_184_seeded_workspace_rejects_mismatched_benchmark_caps` | Seeded workspace cap mismatch is a validation failure. |
| `INT-NEG-015` | `test_int_184_engineer_fail_fast_and_skip_target_node` | Invalid entry must fail fast and skip target-node execution. |

### `tests/integration/architecture_p0/test_cots_reviewer.py`

| Proposed ID | Current test | Why it moves |
| -- | -- | -- |
| `INT-NEG-016` | `test_int_016_reviewer_decision_schema_gate` | Malformed review decisions are schema rejection coverage. |
| `INT-NEG-017` | `test_int_017_plan_refusal_loop` | Plan refusal and FAILED-state propagation are negative-path behavior. |

### `tests/integration/architecture_p0/test_int_187_heavy_crash_containment.py`

| Proposed ID | Current test | Why it moves |
| -- | -- | -- |
| `INT-NEG-018` | `test_int_187_heavy_worker_crash_containment_boundary` | Child-process crash containment is explicitly fail-closed behavior. |

### `tests/electronics/test_integration_electronics.py`

| Proposed ID | Current test | Why it moves |
| -- | -- | -- |
| `INT-NEG-019` | `test_int_120_circuit_validation_pre_gate` | Circuit-validation failure should be isolated as a negative case. |
| `INT-NEG-020` | `test_int_121_short_circuit_detection` | Short-circuit detection is a rejection path. |
| `INT-NEG-021` | `test_int_122_overcurrent_supply_detection` | Overcurrent detection is a rejection path. |
| `INT-NEG-022` | `test_int_124_open_circuit_detection` | Floating-node detection is a rejection path. |
| `INT-NEG-023` | `test_int_126_wire_tear_failure` | Wire-tear failure is negative-path simulation coverage. |

This file is lower-confidence as a migration target because it still relies on
internal imports and `monkeypatch`; the negative rows are still valid
classifications, but the preferred follow-up is to rewrite the coverage as
HTTP-only black-box integration.

### `tests/integration/architecture_p0/test_int_008_objectives_validation.py`

| Proposed ID | Current test | Why it moves |
| -- | -- | -- |
| `INT-NEG-024` | `test_int_008_objectives_semantic_validation_rejects_goal_forbid_overlap` | Objective overlap is a deterministic contradiction. |
| `INT-NEG-025` | `test_int_008_objectives_semantic_validation_rejects_runtime_envelope_forbid_zone_collision` | Runtime envelope intersecting a forbid zone is fail-closed validation. |
| `INT-NEG-026` | `test_int_008_objectives_semantic_validation_rejects_goal_zone_outside_build_zone` | Goal-zone placement outside build zone is rejection coverage. |
| `INT-NEG-027` | `test_int_008_objectives_semantic_validation_rejects_build_zone_outside_simulation_bounds` | Build-zone outside simulation bounds is a negative gate. |
| `INT-NEG-028` | `test_int_008_objectives_semantic_validation_rejects_runtime_envelope_exceeding_build_zone` | Runtime envelope overflow is a fail-closed objective check. |
| `INT-NEG-029` | `test_int_008_objectives_semantic_validation_rejects_negative_runtime_jitter_and_radius` | Negative motion ranges are invalid inputs. |
| `INT-NEG-030` | `test_int_008_attachment_policy_rejects_legacy_attachment_method` | Legacy attachment methods are explicit rejection coverage. |
| `INT-NEG-031` | `test_int_008_requires_non_empty_benchmark_parts` | Missing benchmark parts are a required-contract failure. |
| `INT-NEG-032` | `test_int_008_submit_requires_explicit_reviewer_stage` | Omitted reviewer stage is a direct submit-time failure. |
| `INT-NEG-033` | `test_int_008_missing_interaction_permission_fails_closed_at_handoff` | Missing interaction permission is a fail-closed handoff gate. |
| `INT-NEG-034` | `test_int_008_objectives_semantic_validation_rejects_runtime_envelope_forbid_collision` | Runtime-envelope collisions are rejection coverage. |
| `INT-NEG-035` | `test_int_008_objectives_semantic_validation_rejects_negative_runtime_ranges` | Negative runtime ranges are invalid objective values. |
| `INT-NEG-036` | `test_int_008_drilling_contract_rejects_exceeding_hole_count` | Drill-policy overflow is explicit negative-path coverage. |
| `INT-NEG-037` | `test_int_008_drilling_contract_rejects_diameter_out_of_range` | Out-of-range drill diameter is a rejection case. |
| `INT-NEG-038` | `test_int_008_drilling_contract_rejects_depth_exceeding_max` | Excessive drill depth is a rejection case. |
| `INT-NEG-039` | `test_int_008_no_attachment_policy_defaults_to_non_drillable` | Missing attachment policy must fail closed by default. |

### `tests/integration/architecture_p1/test_benchmark_workflow.py`

| Proposed ID | Current test | Why it moves |
| -- | -- | -- |
| `INT-NEG-040` | `test_benchmark_workflow_rejects_hidden_motion_handoff` | Hidden benchmark motion is a fail-closed refusal. |
| `INT-NEG-041` | `test_benchmark_workflow_rejects_unsupported_motion_handoff` | Unsupported motion tokens are rejection coverage. |
| `INT-NEG-042` | `test_benchmark_request_validation_rejects_invalid_objectives` | Invalid request objectives belong in the negative suite. |
| `INT-NEG-043` | `retry lineage / benchmark reuse` | Failed-run retry lineage is a negative-path UX contract. |

## Keep in `INT-xxx`

These are the main success-path or special-boundary exceptions that should stay
out of the negative bucket for now:

- `tests/integration/architecture_p1/test_benchmark_workflow.py::test_benchmark_planner_cad_reviewer_path`
- `tests/integration/architecture_p1/test_handover.py::test_benchmark_to_engineer_handoff`
- `tests/integration/architecture_p1/test_engineering_loop.py::test_engineering_full_loop`
- `tests/integration/architecture_p1/test_infrastructure.py::test_render_artifact_generation_int_039`
- `tests/integration/architecture_p1/test_infrastructure.py::test_render_artifact_generation_int_039_simulation_video_shows_objective_boxes`
- `tests/integration/architecture_p1/test_infrastructure.py::test_asset_persistence_linkage_int_040`
- `tests/integration/architecture_p1/test_infrastructure.py::test_mjcf_joint_mapping_int_037`
- `tests/integration/architecture_p1/test_infrastructure.py::test_controller_function_family_int_038`
- `tests/integration/architecture_p1/test_reviewer_evidence.py::test_reviewer_evidence_completeness`
- `tests/integration/architecture_p1/test_reviewer_evidence.py::test_engineer_execution_reviewer_handover_accepts_preview_evidence_paths`
- `tests/integration/architecture_p1/test_reviewer_evidence.py::test_reviewer_approval_requires_media_inspection`
- `tests/integration/architecture_p0/test_planner_gates.py::test_int_010_validate_and_price_adds_benchmark_drilling_cost`
- `tests/integration/architecture_p0/test_planner_gates.py::test_int_010_submit_handoff_accepts_cheaper_workspace_drilling_override`
- `tests/integration/architecture_p0/test_planner_gates.py::test_int_019_single_part_benchmark_submit_succeeds_without_cost_gate`
- `tests/integration/architecture_p0/test_planner_gates.py::test_int_018_benchmark_submit_accepts_yaml_motion_without_literal_tokens`
- `tests/integration/architecture_p0/test_int_018_multipart_dfm_gate.py::test_int_018_simulate_does_not_dfm_reject_simple_multipart_benchmark`
- `tests/integration/architecture_p0/test_int_018_multipart_dfm_gate.py::test_int_018_simulation_bounds_ignore_fixed_benchmark_fixtures`
- `tests/integration/architecture_p0/test_missing_p0.py::test_int_005_trace_realtime_broadcast`

## Special handling

- `tests/integration/architecture_p1/test_api_fuzzing.py::test_api_fuzzing` is
  negative-adjacent fuzzing, but it is a broad schema sweep rather than a single
  deterministic rejection scenario. Keep it separate unless the suite gets a
  dedicated fuzz bucket or a dedicated `INT-NEG` policy for generative probing.
- The publication-pruned benchmark workflow and retry-lineage candidates above
  are placeholders until the negative catalog is populated for them. The long-
  term cleanup is to replace any internal-import or `monkeypatch` coverage with
  HTTP-only black-box integration.
