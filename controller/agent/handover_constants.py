from __future__ import annotations

from shared.script_contracts import (
    BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH,
    BENCHMARK_PLAN_PATH,
    BENCHMARK_SCRIPT_PATH,
    ENGINEERING_PLAN_PATH,
    PAYLOAD_TRAJECTORY_DEFINITION_PATH,
    SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
    SOLUTION_SCRIPT_PATH,
)

ENGINEER_BENCHMARK_CONTEXT_ARTIFACTS: tuple[str, ...] = (
    "benchmark_definition.yaml",
    "assembly_definition.yaml",
    "benchmark_assembly_definition.yaml",
    BENCHMARK_SCRIPT_PATH,
)

BENCHMARK_PLANNER_HANDOFF_ARTIFACTS: tuple[str, ...] = (
    BENCHMARK_PLAN_PATH,
    "benchmark_definition.yaml",
    "benchmark_assembly_definition.yaml",
    BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH,
)

BENCHMARK_CODER_HANDOFF_ARTIFACTS: tuple[str, ...] = BENCHMARK_PLANNER_HANDOFF_ARTIFACTS

ENGINEERING_EXECUTION_REVIEWER_HANDOFF_ARTIFACTS: tuple[str, ...] = (
    ENGINEERING_PLAN_PATH,
    "todo.md",
    "benchmark_definition.yaml",
    "assembly_definition.yaml",
    "benchmark_assembly_definition.yaml",
    BENCHMARK_SCRIPT_PATH,
    SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
    SOLUTION_SCRIPT_PATH,
)

ENGINEER_PLANNER_HANDOFF_ARTIFACTS: tuple[str, ...] = (
    ENGINEERING_PLAN_PATH,
    "benchmark_definition.yaml",
    "assembly_definition.yaml",
    "benchmark_assembly_definition.yaml",
    BENCHMARK_SCRIPT_PATH,
    SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
)

BENCHMARK_PLAN_REVIEW_MANIFEST = ".manifests/benchmark_plan_review_manifest.json"
ENGINEERING_PLAN_REVIEW_MANIFEST = ".manifests/engineering_plan_review_manifest.json"
BENCHMARK_REVIEW_MANIFEST = ".manifests/benchmark_review_manifest.json"
ENGINEERING_EXECUTION_HANDOFF_MANIFEST = (
    ".manifests/engineering_execution_handoff_manifest.json"
)

BENCHMARK_PLAN_REVIEWER_HANDOVER_CHECK = "benchmark_plan_reviewer_handover"
BENCHMARK_REVIEWER_HANDOVER_CHECK = "benchmark_reviewer_handover"
BENCHMARK_CODER_HANDOVER_CHECK = "benchmark_coder_handover"
ENGINEER_PLAN_REVIEWER_HANDOVER_CHECK = "engineer_plan_reviewer_handover"
ENGINEER_EXECUTION_REVIEWER_HANDOVER_CHECK = "engineer_execution_reviewer_handover"
ENGINEER_BENCHMARK_HANDOVER_CHECK = "engineer_benchmark_handover"
ENGINEER_PLANNER_EVIDENCE_LAYOUT_CHECK = "engineer_planner_evidence_layout_check"

SCHEMA_BACKED_HANDOFF_PATHS: tuple[str, ...] = (
    BENCHMARK_PLAN_PATH,
    ENGINEERING_PLAN_PATH,
    "todo.md",
    "plan_refusal.md",
    "benchmark_definition.yaml",
    "assembly_definition.yaml",
    PAYLOAD_TRAJECTORY_DEFINITION_PATH,
    "benchmark_assembly_definition.yaml",
    ".manifests/current_role.json",
    "benchmark_plan_evidence_script.py",
    "solution_plan_evidence_script.py",
    "renders/benchmark_renders/render_manifest.json",
    "renders/engineer_plan_renders/render_manifest.json",
    "renders/final_solution_submission_renders/render_manifest.json",
    BENCHMARK_SCRIPT_PATH,
    SOLUTION_SCRIPT_PATH,
    "validation_results.json",
    "simulation_result.json",
    BENCHMARK_PLAN_REVIEW_MANIFEST,
    ENGINEERING_PLAN_REVIEW_MANIFEST,
    BENCHMARK_REVIEW_MANIFEST,
    ENGINEERING_EXECUTION_HANDOFF_MANIFEST,
)


__all__ = [
    "BENCHMARK_CODER_HANDOFF_ARTIFACTS",
    "BENCHMARK_CODER_HANDOVER_CHECK",
    "BENCHMARK_PLANNER_HANDOFF_ARTIFACTS",
    "BENCHMARK_PLAN_REVIEWER_HANDOVER_CHECK",
    "BENCHMARK_PLAN_REVIEW_MANIFEST",
    "BENCHMARK_REVIEWER_HANDOVER_CHECK",
    "BENCHMARK_REVIEW_MANIFEST",
    "ENGINEERING_EXECUTION_HANDOFF_MANIFEST",
    "ENGINEERING_EXECUTION_REVIEWER_HANDOFF_ARTIFACTS",
    "ENGINEERING_PLAN_REVIEW_MANIFEST",
    "ENGINEER_BENCHMARK_CONTEXT_ARTIFACTS",
    "ENGINEER_BENCHMARK_HANDOVER_CHECK",
    "ENGINEER_EXECUTION_REVIEWER_HANDOVER_CHECK",
    "ENGINEER_PLANNER_EVIDENCE_LAYOUT_CHECK",
    "ENGINEER_PLANNER_HANDOFF_ARTIFACTS",
    "ENGINEER_PLAN_REVIEWER_HANDOVER_CHECK",
    "SCHEMA_BACKED_HANDOFF_PATHS",
]
