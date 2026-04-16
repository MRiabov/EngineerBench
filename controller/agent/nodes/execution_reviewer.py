import json
import uuid
from contextlib import suppress
from typing import Literal

import dspy
import structlog
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from controller.agent.config import settings
from controller.agent.render_validation import validate_render_images_non_black
from controller.agent.state import AgentState, AgentStatus
from controller.agent.tools import get_engineer_tools
from controller.observability.tracing import record_worker_events
from shared.enums import AgentName, ReviewDecision
from shared.models.schemas import ReviewResult
from shared.models.simulation import SimulationResult
from shared.observability.schemas import ReviewDecisionEvent
from shared.script_contracts import (
    BENCHMARK_SCRIPT_PATH,
    PAYLOAD_TRAJECTORY_DEFINITION_PATH,
    SOLUTION_SCRIPT_PATH,
)
from shared.type_checking import type_check

from ..review_handover import validate_reviewer_handover
from .base import BaseNode, SharedNodeContext

logger = structlog.get_logger(__name__)


class ExecutionReviewerSignature(dspy.Signature):
    """DSPy signature for the engineer execution reviewer."""

    task = dspy.InputField()
    plan = dspy.InputField()
    todo = dspy.InputField()
    render_paths = dspy.InputField(default="")
    assembly_definition = dspy.InputField()
    benchmark_assembly_definition = dspy.InputField()
    plan_refusal = dspy.InputField(default="")
    objectives = dspy.InputField()
    validation_results = dspy.InputField()
    journal = dspy.InputField()
    review: ReviewResult = dspy.OutputField()


class SimulationReviewOutcome(BaseModel):
    """Structured result of execution review simulation pre-check."""

    ran: bool
    success: bool
    summary: str
    source: Literal["simulation", "precheck"]


@type_check
class ExecutionReviewerNode(BaseNode):
    """
    Engineer Execution Reviewer node: Evaluates the implementation after simulation.
    """

    async def _enforce_render_inspection_gate(
        self, review: ReviewResult
    ) -> ReviewResult:
        if review.decision != ReviewDecision.APPROVED:
            return review
        render_paths = await self._list_current_revision_render_paths()
        if not render_paths:
            return review
        render_error = await validate_render_images_non_black(self.ctx.worker_client)
        if render_error is not None:
            fixes = list(review.required_fixes or [])
            fixes.append("Replace black or empty render images with visible renders.")
            return review.model_copy(
                update={
                    "decision": ReviewDecision.REJECTED,
                    "reason": (
                        "Approval blocked: render media exists but at least one "
                        "RGB render is black/empty."
                    ),
                    "required_fixes": fixes,
                }
            )
        inspected_render_count = self._count_inspected_render_media_paths(render_paths)
        if inspected_render_count > 0:
            return review
        fixes = list(review.required_fixes or [])
        fixes.append(
            "Inspect at least one current-revision render via inspect_media(path) "
            "before approving."
        )
        return review.model_copy(
            update={
                "decision": ReviewDecision.REJECTED,
                "reason": (
                    "Approval blocked: current-revision renders exist but the "
                    "reviewer did not inspect any of them with inspect_media(path)."
                ),
                "required_fixes": fixes,
            }
        )

    async def _read_validation_results_text(self) -> str:
        try:
            return await self._read_optional_workspace_file(
                "validation_results.json",
                "# No validation_results.json found.",
            )
        except Exception:
            return "# Failed to read validation_results.json."

    async def __call__(self, state: AgentState) -> AgentState:
        db_callback = self.ctx.get_database_recorder(state.episode_id)
        node_output_data = state.task or "Execution reviewer started."
        node_output_obj = None
        await db_callback.record_node_start(
            AgentName.ENGINEER_EXECUTION_REVIEWER,
            input_data=state.task or state.journal,
        )
        try:
            assembly_definition = "# No assembly_definition.yaml found."
            with suppress(Exception):
                assembly_definition = await self._read_optional_workspace_file(
                    "assembly_definition.yaml", assembly_definition
                )
            benchmark_assembly_definition = await self._read_required_workspace_file(
                "benchmark_assembly_definition.yaml"
            )
            benchmark_plan_review_manifest = (
                "# No benchmark_plan_review_manifest.json found."
            )
            with suppress(Exception):
                if await self.ctx.worker_client.exists(
                    ".manifests/benchmark_plan_review_manifest.json"
                ):
                    benchmark_plan_review_manifest = (
                        await self._read_optional_workspace_file(
                            ".manifests/benchmark_plan_review_manifest.json",
                            benchmark_plan_review_manifest,
                        )
                    )
            payload_trajectory_definition = (
                "# No payload_trajectory_definition.yaml found."
            )
            with suppress(Exception):
                payload_trajectory_definition = (
                    await self._read_optional_workspace_file(
                        PAYLOAD_TRAJECTORY_DEFINITION_PATH,
                        payload_trajectory_definition,
                    )
                )

            render_paths = await self._list_current_revision_render_paths()
            if not render_paths:
                for preview_path in (
                    "renders/render_e45_a45.png",
                    "renders/dof_review_preview.png",
                ):
                    with suppress(Exception):
                        if await self.ctx.worker_client.exists(preview_path):
                            render_paths.append(preview_path)
            render_paths = list(dict.fromkeys(render_paths))
            render_paths_text = (
                "\n".join(render_paths)
                if render_paths
                else "# No current-revision renders found."
            )

            submit_err = await self._ensure_submit_for_review_succeeded()
            if submit_err:
                node_output_data = submit_err
                return state.model_copy(
                    update={
                        "status": AgentStatus.CODE_REJECTED,
                        "feedback": submit_err,
                        "journal": state.journal
                        + f"\n[Execution Reviewer] {submit_err}",
                        "turn_count": state.turn_count + 1,
                    }
                )

            simulation_outcome = await self._run_simulation_review_step()
            simulation_journal = f"\n[Simulation] {simulation_outcome.summary}"
            if not simulation_outcome.success:
                node_output_data = simulation_outcome.summary
                return state.model_copy(
                    update={
                        "status": AgentStatus.CODE_REJECTED,
                        "feedback": simulation_outcome.summary,
                        "journal": state.journal + simulation_journal,
                        "turn_count": state.turn_count + 1,
                    }
                )

            # Read objectives if possible for context
            objectives = "# No benchmark_definition.yaml found."
            with suppress(Exception):
                objectives = await self._read_optional_workspace_file(
                    "benchmark_definition.yaml",
                    objectives,
                )

            validation_results = await self._read_validation_results_text()

            assembly_definition = "# No assembly_definition.yaml found."
            with suppress(Exception):
                assembly_definition = await self._read_optional_workspace_file(
                    "assembly_definition.yaml",
                    assembly_definition,
                )

            plan_refusal = ""
            with suppress(Exception):
                plan_refusal = await self._read_optional_workspace_file(
                    "plan_refusal.md",
                    plan_refusal,
                )

            inputs = {
                "task": state.task,
                "plan": state.plan,
                "todo": state.todo,
                "render_paths": render_paths_text,
                "assembly_definition": assembly_definition,
                "benchmark_assembly_definition": benchmark_assembly_definition,
                "benchmark_plan_review_manifest": benchmark_plan_review_manifest,
                "payload_trajectory_definition": payload_trajectory_definition,
                "plan_refusal": plan_refusal,
                "objectives": objectives,
                "validation_results": validation_results,
                "journal": state.journal + simulation_journal,
            }

            # Validate existence of key reports
            validate_files = [
                "simulation_result.json",
                "validation_results.json",
                BENCHMARK_SCRIPT_PATH,
                PAYLOAD_TRAJECTORY_DEFINITION_PATH,
                "assembly_definition.yaml",
                "benchmark_assembly_definition.yaml",
            ]

            prediction, _artifacts, journal_entry = await self._run_program(
                program_cls=dspy.ReAct,
                signature_cls=ExecutionReviewerSignature,
                state=state,
                inputs=inputs,
                tool_factory=get_engineer_tools,
                validate_files=validate_files,
                node_type=AgentName.ENGINEER_EXECUTION_REVIEWER,
                record_node_lifecycle=False,
            )
            node_output_data = str(prediction)
            node_output_obj = prediction

            if not prediction:
                node_output_data = (
                    f"Execution Reviewer failed to complete: {journal_entry}"
                )
                return state.model_copy(
                    update={
                        "status": AgentStatus.CODE_REJECTED,
                        "feedback": (
                            f"Execution Reviewer failed to complete: {journal_entry}"
                        ),
                        "journal": state.journal + simulation_journal + journal_entry,
                        "turn_count": state.turn_count + 1,
                    }
                )

            review = ReviewResult.model_validate(prediction.review)
            review = await self._enforce_render_inspection_gate(review)
            try:
                (
                    review_decision_path,
                    review_comments_path,
                ) = await self._persist_review_result(
                    review, "engineering-execution-review"
                )
            except Exception as exc:
                node_output_data = (
                    f"Execution Reviewer failed to persist review file: {exc}"
                )
                return state.model_copy(
                    update={
                        "status": AgentStatus.FAILED,
                        "feedback": node_output_data,
                        "journal": (
                            state.journal
                            + simulation_journal
                            + journal_entry
                            + f"\n[Execution Reviewer] Review persistence failed: {exc}"
                        ),
                        "turn_count": state.turn_count + 1,
                    }
                )
            decision = review.decision
            feedback = review.reason
            if review.required_fixes:
                feedback += "\nRequired Fixes:\n" + "\n".join(
                    [f"- {f}" for f in review.required_fixes]
                )

            journal_entry += (
                f"\nCritic Decision: {decision.value}\nFeedback: {feedback}"
            )

            status_map = {
                ReviewDecision.APPROVED: AgentStatus.APPROVED,
                ReviewDecision.REJECTED: AgentStatus.CODE_REJECTED,
                ReviewDecision.REJECT_PLAN: AgentStatus.PLAN_REJECTED,
                ReviewDecision.REJECT_CODE: AgentStatus.CODE_REJECTED,
                ReviewDecision.CONFIRM_PLAN_REFUSAL: AgentStatus.FAILED,
                ReviewDecision.REJECT_PLAN_REFUSAL: AgentStatus.CODE_REJECTED,
            }
            if decision not in status_map:
                node_output_data = (
                    "Execution Reviewer returned unsupported structured "
                    f"decision: {decision}"
                )
                return state.model_copy(
                    update={
                        "status": AgentStatus.FAILED,
                        "feedback": node_output_data,
                        "journal": (
                            state.journal
                            + simulation_journal
                            + journal_entry
                            + f"\n[Execution Reviewer] Unsupported decision: {decision}"
                        ),
                        "turn_count": state.turn_count + 1,
                    }
                )

            # Emit ReviewDecisionEvent for observability
            review_id = uuid.uuid4().hex
            await record_worker_events(
                episode_id=state.episode_id,
                events=[
                    ReviewDecisionEvent(
                        decision=decision,
                        reason=feedback,
                        review_id=review_id,
                        evidence_stats={
                            "has_sim_report": True,
                            "has_mfg_report": True,
                            "review_decision_path": review_decision_path,
                            "review_comments_path": review_comments_path,
                        },
                        checklist=review.checklist,
                    )
                ],
            )

            node_output_data = f"Review decision: {decision.value}"
            node_output_obj = review
            return state.model_copy(
                update={
                    "status": status_map[decision],
                    "feedback": feedback,
                    "journal": state.journal + simulation_journal + journal_entry,
                    "messages": [
                        *state.messages,
                        AIMessage(content=f"Review decision: {decision.value}"),
                    ],
                    "turn_count": state.turn_count + 1,
                }
            )
        finally:
            await db_callback.record_node_end(
                AgentName.ENGINEER_EXECUTION_REVIEWER,
                output_data=node_output_data,
                output_obj=node_output_obj,
            )

    async def _run_simulation_review_step(self) -> SimulationReviewOutcome:
        if not await self.ctx.worker_client.exists("simulation_result.json"):
            return SimulationReviewOutcome(
                ran=False,
                success=False,
                summary=(
                    "simulation_result.json missing; execution review requires "
                    "a valid latest-revision handoff package."
                ),
                source="precheck",
            )

        try:
            sim_raw = await self.ctx.worker_client.read_file("simulation_result.json")
            sim_result = SimulationResult.model_validate_json(sim_raw)
        except Exception as e:
            logger.warning(
                "execution_reviewer_simulation_artifact_invalid", error=str(e)
            )
            return SimulationReviewOutcome(
                ran=False,
                success=False,
                summary=f"simulation_result.json invalid: {e}",
                source="precheck",
            )

        if sim_result.success:
            return SimulationReviewOutcome(
                ran=False,
                success=True,
                summary=sim_result.summary.strip() or "Goal achieved.",
                source="precheck",
            )

        return SimulationReviewOutcome(
            ran=False,
            success=False,
            summary=sim_result.summary.strip() or "Simulation failed.",
            source="precheck",
        )

    async def _persist_simulation_artifacts(self, sim_result) -> None:
        """Persist real simulation outputs for downstream asset/tracing sync."""
        try:
            sim_payload = {
                "success": bool(getattr(sim_result, "success", False)),
                "summary": str(getattr(sim_result, "message", "") or ""),
                "confidence": str(getattr(sim_result, "confidence", "") or ""),
            }
            await self.ctx.worker_client.write_file(
                "simulation_result.json",
                json.dumps(sim_payload),
                overwrite=True,
                bypass_agent_permissions=True,
            )
        except Exception as e:
            logger.warning(
                "execution_reviewer_persist_simulation_artifacts_failed", error=str(e)
            )

    async def _ensure_submit_for_review_succeeded(self) -> str | None:
        handoff_err = await validate_reviewer_handover(
            self.ctx.worker_client,
            manifest_path=".manifests/engineering_execution_handoff_manifest.json",
            expected_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        if not handoff_err:
            return None

        if not await self.ctx.worker_client.exists(SOLUTION_SCRIPT_PATH):
            return f"Execution review blocked: {SOLUTION_SCRIPT_PATH} missing."

        # System-side handoff materialization path. This avoids agent-permission
        # writes to protected manifest files while keeping submission strict.
        try:
            validate_result = await self.ctx.worker_client.validate(
                SOLUTION_SCRIPT_PATH
            )
        except Exception as exc:
            return f"Execution review blocked: validate failed: {exc}"
        if not validate_result.success:
            return (
                "Execution review blocked: validate failed: "
                f"{validate_result.message or 'unknown validation failure'}"
            )

        try:
            simulate_result = await self.ctx.worker_client.simulate(
                SOLUTION_SCRIPT_PATH
            )
            await self._persist_simulation_artifacts(simulate_result)
        except Exception as exc:
            return f"Execution review blocked: simulate failed: {exc}"
        if not simulate_result.success:
            return (
                "Execution review blocked: simulate failed: "
                f"{simulate_result.message or 'unknown simulation failure'}"
            )

        try:
            verify_result = await self.ctx.worker_client.verify(
                SOLUTION_SCRIPT_PATH,
                num_scenes=1 if settings.is_integration_test else None,
                duration=1.0 if settings.is_integration_test else None,
                smoke_test_mode=settings.is_integration_test,
            )
        except Exception as exc:
            return f"Execution review blocked: verify failed: {exc}"
        if not verify_result.success:
            return (
                "Execution review blocked: verify failed: "
                f"{verify_result.message or 'unknown verification failure'}"
            )

        try:
            episode_id = self.ctx.episode_id
            submit_result = await self.ctx.worker_client.submit(
                SOLUTION_SCRIPT_PATH,
                reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
                episode_id=episode_id,
            )
        except Exception as exc:
            return f"Execution review blocked: submit_for_review failed: {exc}"
        if not submit_result.success:
            return (
                "Execution review blocked: submit_for_review failed: "
                f"{submit_result.message or 'unknown submit failure'}"
            )

        post_submit_err = await validate_reviewer_handover(
            self.ctx.worker_client,
            manifest_path=".manifests/engineering_execution_handoff_manifest.json",
            expected_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        if post_submit_err:
            return f"Execution review blocked: {post_submit_err}"
        return None


# Factory function for LangGraph
@type_check
async def engineer_execution_reviewer_node(state: AgentState) -> AgentState:
    session_id = state.session_id
    if not session_id:
        msg = "Missing required session_id for engineer_execution_reviewer_node"
        raise ValueError(msg)
    episode_id = state.episode_id
    ctx = SharedNodeContext.create(
        worker_light_url=settings.worker_light_url,
        session_id=session_id,
        episode_id=episode_id,
        agent_role=AgentName.ENGINEER_EXECUTION_REVIEWER,
    )
    node = ExecutionReviewerNode(context=ctx)
    return await node(state)
