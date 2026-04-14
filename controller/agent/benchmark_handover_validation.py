from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from controller.clients.worker import WorkerClient
from shared.enums import AgentName, BenchmarkRefusalReason
from shared.models.schemas import (
    AssemblyDefinition,
    BenchmarkDefinition,
    PlannerSubmissionResult,
)
from shared.script_contracts import plan_artifact_candidates_for_agent
from shared.simulation.schemas import CustomObjectives, RandomizationStrategy
from worker_heavy.utils.file_validation import (
    validate_assembly_definition_yaml,
    validate_benchmark_assembly_motion_contract,
    validate_benchmark_definition_yaml,
    validate_node_output,
)


class BenchmarkPlanReviewerEvidence(BaseModel):
    """Structured evidence for benchmark plan solvability review."""

    session_id: str | None = None
    review_manifest_path: str | None = None
    review_manifest_revision: str | None = None
    review_manifest_script_sha256: str | None = None
    render_paths: list[str] = Field(default_factory=list)
    render_count: int = 0
    deterministic_errors: list[str] = Field(default_factory=list)
    refusal_reason: BenchmarkRefusalReason | None = None
    solvability_summary: str = ""
    latest_revision_verified: bool = False

    def to_prompt_text(self) -> str:
        """Render the evidence as compact JSON for prompt injection."""
        return self.model_dump_json(indent=2, exclude_none=True)


def extract_benchmark_refusal_reason(
    text: str | None,
) -> BenchmarkRefusalReason | None:
    """Return the first benchmark refusal token present in a text blob."""
    normalized = (text or "").upper()
    for reason in BenchmarkRefusalReason:
        if reason.value in normalized:
            return reason
    return None


def _validate_benchmark_motion_visibility(
    *,
    artifacts: dict[str, str],
    session_id: str | None = None,
) -> list[str]:
    """Validate benchmark motion facts from structured planner artifacts."""
    plan_refusal_text = artifacts.get("plan_refusal.md")
    if plan_refusal_text is not None:
        try:
            from worker_heavy.utils.file_validation import validate_plan_refusal

            is_valid_refusal, _ = validate_plan_refusal(plan_refusal_text)
            if is_valid_refusal:
                return []
        except Exception:
            pass

    plan_text = artifacts.get("benchmark_plan.md")
    todo_text = artifacts.get("todo.md")
    benchmark_definition_text = artifacts.get("benchmark_definition.yaml")
    benchmark_assembly_definition_text = artifacts.get(
        "benchmark_assembly_definition.yaml"
    )
    if (
        not benchmark_definition_text
        or not benchmark_assembly_definition_text
        or not plan_text
        or not todo_text
    ):
        return []

    is_valid, benchmark_definition_or_errors = validate_benchmark_definition_yaml(
        benchmark_definition_text,
        session_id=session_id,
    )
    if not is_valid:
        return [
            f"planner_semantic: {message}" for message in benchmark_definition_or_errors
        ]
    benchmark_definition = benchmark_definition_or_errors
    if not isinstance(benchmark_definition, BenchmarkDefinition):
        return [
            "planner_semantic: benchmark_definition.yaml did not parse as BenchmarkDefinition"
        ]

    is_valid, assembly_definition_or_errors = validate_assembly_definition_yaml(
        benchmark_assembly_definition_text,
        session_id=session_id,
    )
    if not is_valid:
        return [
            f"planner_semantic: {message}" for message in assembly_definition_or_errors
        ]
    assembly_definition = assembly_definition_or_errors
    if not isinstance(assembly_definition, AssemblyDefinition):
        return [
            "planner_semantic: benchmark_assembly_definition.yaml did not parse as AssemblyDefinition"
        ]

    return validate_benchmark_assembly_motion_contract(
        benchmark_definition=benchmark_definition,
        assembly_definition=assembly_definition,
        plan_text=plan_text,
        todo_text=todo_text,
        plan_refusal_text=plan_refusal_text,
    )


def validate_benchmark_planner_handoff_payload(
    *,
    artifacts: dict[str, str],
    session_id: str | None = None,
    custom_objectives: CustomObjectives | None = None,
    submission: PlannerSubmissionResult | None = None,
    submission_error: str | None = None,
    plan_output: Any | None = None,
    require_submission: bool = False,
    require_structured_plan: bool = False,
) -> list[str]:
    """Validate a benchmark planner handoff payload across entry and exit paths."""
    errors: list[str] = []

    if artifacts:
        is_valid, structural_errors = validate_node_output(
            AgentName.BENCHMARK_PLANNER, artifacts
        )
        if not is_valid:
            errors.extend([f"planner_structural: {msg}" for msg in structural_errors])

    motion_errors = _validate_benchmark_motion_visibility(
        artifacts=artifacts,
        session_id=session_id,
    )
    errors.extend([f"planner_semantic: {message}" for message in motion_errors])

    objectives_text = artifacts.get("benchmark_definition.yaml")
    if objectives_text:
        try:
            is_valid, objectives_or_errors = validate_benchmark_definition_yaml(
                objectives_text,
                session_id=session_id,
            )
            if not is_valid:
                errors.extend(
                    [f"planner_semantic: {message}" for message in objectives_or_errors]
                )
                objectives = None
            else:
                objectives = objectives_or_errors
            if custom_objectives and objectives is not None:
                if custom_objectives.max_unit_cost is not None:
                    observed = objectives.constraints.max_unit_cost
                    expected = custom_objectives.max_unit_cost
                    if observed is None or abs(observed - expected) > 1e-6:
                        errors.append(
                            "planner_semantic: objectives.constraints.max_unit_cost "
                            f"({observed}) does not match custom objective ({expected})"
                        )
                if custom_objectives.max_weight is not None:
                    observed = objectives.constraints.max_weight_g
                    expected = custom_objectives.max_weight
                    if observed is None or abs(observed - expected) > 1e-6:
                        errors.append(
                            "planner_semantic: objectives.constraints.max_weight_g "
                            f"({observed}) does not match custom objective ({expected})"
                        )
                if custom_objectives.target_quantity is not None:
                    observed = objectives.constraints.target_quantity
                    expected = custom_objectives.target_quantity
                    if observed != expected:
                        errors.append(
                            "planner_semantic: objectives.constraints.target_quantity "
                            f"({observed}) does not match custom objective ({expected})"
                        )
        except Exception as exc:
            errors.append(
                f"planner_semantic: Failed to parse benchmark_definition.yaml ({exc})"
            )

        if require_submission:
            if submission is not None:
                if not submission.ok or submission.status != "submitted":
                    errors.append(
                        "planner_submission: submit_benchmark_plan() did not return submitted"
                    )
                if submission.node_type != AgentName.BENCHMARK_PLANNER:
                    errors.append(
                        "planner_submission: submission node_type is not benchmark_planner"
                    )
                if submission.errors:
                    errors.extend(
                        [f"planner_submission: {msg}" for msg in submission.errors]
                    )
            elif submission_error:
                errors.append(f"planner_submission: {submission_error}")

    if require_structured_plan:
        if plan_output is None:
            errors.append(
                "planner_execution: missing structured planner output. "
                "Retry planner and call submit_benchmark_plan() before handoff."
            )
        elif isinstance(plan_output, dict):
            is_plan_valid = False
            try:
                RandomizationStrategy.model_validate(plan_output)
                is_plan_valid = True
            except Exception:
                pass
            if not is_plan_valid:
                errors.append(
                    "planner_execution: planner output does not match RandomizationStrategy"
                )
        elif not isinstance(plan_output, RandomizationStrategy):
            errors.append(
                "planner_execution: planner output has unexpected type; "
                "expected RandomizationStrategy"
            )

    return errors


async def validate_benchmark_planner_handoff_artifacts(
    client: WorkerClient,
    *,
    custom_objectives: CustomObjectives | None = None,
    submission: PlannerSubmissionResult | None = None,
    submission_error: str | None = None,
    plan_output: Any | None = None,
    require_submission: bool = False,
    require_structured_plan: bool = False,
) -> list[str]:
    """Validate the planner-to-coder handoff package from the worker session."""
    errors: list[str] = []
    artifacts: dict[str, str] = {}

    plan_artifact_name = plan_artifact_candidates_for_agent(
        AgentName.BENCHMARK_PLANNER
    )[0]
    if not await client.exists(plan_artifact_name):
        errors.append(f"Missing planner artifact: {plan_artifact_name}")
    else:
        artifacts[plan_artifact_name] = await client.read_file(plan_artifact_name)

    for rel_path in (
        "todo.md",
        "benchmark_definition.yaml",
        "benchmark_assembly_definition.yaml",
    ):
        if not await client.exists(rel_path):
            errors.append(f"Missing planner artifact: {rel_path}")
            continue
        artifacts[rel_path] = await client.read_file(rel_path)

    validation_messages = validate_benchmark_planner_handoff_payload(
        artifacts=artifacts,
        session_id=client.session_id,
        custom_objectives=custom_objectives,
        submission=submission,
        submission_error=submission_error,
        plan_output=plan_output,
        require_submission=require_submission,
        require_structured_plan=require_structured_plan,
    )
    ignored_missing_files = {
        "benchmark_plan_evidence_script.py",
        "renders/benchmark_renders/render_manifest.json",
    }
    validation_messages = [
        message
        for message in validation_messages
        if not (
            "Missing required file:" in message
            and any(path in message for path in ignored_missing_files)
        )
    ]
    errors.extend(validation_messages)
    return errors


def extract_custom_objectives_from_state(state: Any) -> CustomObjectives | None:
    """Best-effort extractor for custom objectives from a graph state or mapping."""
    session = (
        state.get("session")
        if isinstance(state, dict)
        else getattr(state, "session", None)
    )
    raw = (
        session.get("custom_objectives")
        if isinstance(session, dict)
        else getattr(session, "custom_objectives", None)
    )
    if raw is None or isinstance(raw, CustomObjectives):
        return raw
    try:
        return CustomObjectives.model_validate(raw)
    except Exception:
        return None


def _is_static_preview_render(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in {".png", ".jpg", ".jpeg"}


def build_benchmark_plan_reviewer_evidence(
    *,
    artifacts: dict[str, str],
    benchmark_definition: BenchmarkDefinition | None = None,
    session_id: str | None = None,
    render_paths: list[str] | None = None,
    review_manifest_path: str | None = None,
    review_manifest_revision: str | None = None,
    review_manifest_script_sha256: str | None = None,
    latest_revision_verified: bool = False,
) -> BenchmarkPlanReviewerEvidence:
    """Summarize benchmark plan review evidence using deterministic validators."""
    validation_errors = validate_benchmark_planner_handoff_payload(
        artifacts=artifacts,
        session_id=session_id,
        require_submission=False,
        require_structured_plan=False,
    )
    normalized_render_paths = sorted(
        {
            path.strip()
            for path in (render_paths or [])
            if path and _is_static_preview_render(path)
        }
    )
    joined_errors = "; ".join(validation_errors)
    refusal_reason = extract_benchmark_refusal_reason(joined_errors)
    if validation_errors:
        solvability_summary = "deterministic solvability checks failed: " + "; ".join(
            validation_errors
        )
    elif normalized_render_paths:
        solvability_summary = (
            "deterministic solvability checks passed; inspect the latest revision "
            "render evidence before approving or rejecting."
        )
    else:
        solvability_summary = (
            "deterministic solvability checks passed and no render images were "
            "recorded for the latest revision."
        )

    return BenchmarkPlanReviewerEvidence(
        session_id=session_id,
        review_manifest_path=review_manifest_path,
        review_manifest_revision=review_manifest_revision,
        review_manifest_script_sha256=review_manifest_script_sha256,
        render_paths=normalized_render_paths,
        render_count=len(normalized_render_paths),
        deterministic_errors=list(dict.fromkeys(validation_errors)),
        refusal_reason=refusal_reason,
        solvability_summary=solvability_summary,
        latest_revision_verified=latest_revision_verified,
    )
