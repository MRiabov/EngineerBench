import uuid
from contextlib import suppress

import dspy
import structlog
from langchain_core.messages import AIMessage

from controller.agent.config import settings
from controller.agent.state import AgentState, AgentStatus
from controller.agent.tools import get_engineer_tools
from controller.observability.tracing import record_worker_events
from shared.enums import AgentName, ReviewDecision
from shared.models.schemas import ReviewResult
from shared.observability.schemas import ReviewDecisionEvent
from shared.type_checking import type_check

from .base import BaseNode, SharedNodeContext

logger = structlog.get_logger(__name__)


class PlanReviewerSignature(dspy.Signature):
    """DSPy signature for the engineer plan reviewer."""

    task = dspy.InputField()
    plan = dspy.InputField()
    todo = dspy.InputField()
    assembly_definition = dspy.InputField()
    benchmark_assembly_definition = dspy.InputField()
    plan_refusal = dspy.InputField(default="")
    objectives = dspy.InputField()
    journal = dspy.InputField()
    review: ReviewResult = dspy.OutputField()


@type_check
class PlanReviewerNode(BaseNode):
    """
    Engineer Plan Reviewer node: Evaluates the engineering plan before implementation.
    """

    async def __call__(self, state: AgentState) -> AgentState:
        # Read objectives and assembly_definition for context
        objectives = "# No benchmark_definition.yaml found."
        with suppress(Exception):
            objectives = await self._read_optional_workspace_file(
                "benchmark_definition.yaml", objectives
            )

        assembly_definition = "# No assembly_definition.yaml found."
        with suppress(Exception):
            assembly_definition = await self._read_optional_workspace_file(
                "assembly_definition.yaml", assembly_definition
            )
        benchmark_assembly_definition = await self._read_required_workspace_file(
            "benchmark_assembly_definition.yaml"
        )

        plan_refusal = ""
        with suppress(Exception):
            plan_refusal = await self._read_optional_workspace_file(
                "plan_refusal.md", plan_refusal
            )

        inputs = {
            "task": state.task,
            "plan": state.plan,
            "todo": state.todo,
            "assembly_definition": assembly_definition,
            "benchmark_assembly_definition": benchmark_assembly_definition,
            "plan_refusal": plan_refusal,
            "objectives": objectives,
            "journal": state.journal,
        }

        validate_files = [
            "engineering_plan.md",
            "todo.md",
            "assembly_definition.yaml",
            "benchmark_assembly_definition.yaml",
        ]

        prediction, _artifacts, journal_entry = await self._run_program(
            program_cls=dspy.ReAct,
            signature_cls=PlanReviewerSignature,
            state=state,
            inputs=inputs,
            tool_factory=get_engineer_tools,
            validate_files=validate_files,
            node_type=AgentName.ENGINEER_PLAN_REVIEWER,
        )

        if not prediction:
            return state.model_copy(
                update={
                    "status": AgentStatus.PLAN_REJECTED,
                    "feedback": f"Plan Reviewer failed to complete: {journal_entry}",
                    "journal": state.journal + journal_entry,
                    "turn_count": state.turn_count + 1,
                }
            )

        review = ReviewResult.model_validate(prediction.review)
        try:
            (
                review_decision_path,
                review_comments_path,
            ) = await self._persist_review_result(review, "engineering-plan-review")
        except Exception as exc:
            return state.model_copy(
                update={
                    "status": AgentStatus.FAILED,
                    "feedback": f"Plan Reviewer failed to persist review file: {exc}",
                    "journal": (
                        state.journal
                        + journal_entry
                        + f"\n[Plan Reviewer] Review persistence failed: {exc}"
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
            f"\nPlan Critic Decision: {decision.value}\nFeedback: {feedback}"
        )

        status_map = {
            ReviewDecision.APPROVED: AgentStatus.APPROVED,
            ReviewDecision.REJECTED: AgentStatus.PLAN_REJECTED,
            ReviewDecision.REJECT_PLAN: AgentStatus.PLAN_REJECTED,
            ReviewDecision.CONFIRM_PLAN_REFUSAL: AgentStatus.FAILED,
            ReviewDecision.REJECT_PLAN_REFUSAL: AgentStatus.PLAN_REJECTED,
        }
        if decision not in status_map:
            return state.model_copy(
                update={
                    "status": AgentStatus.FAILED,
                    "feedback": (
                        "Plan Reviewer returned unsupported structured decision: "
                        f"{decision}"
                    ),
                    "journal": (
                        state.journal
                        + journal_entry
                        + f"\n[Plan Reviewer] Unsupported decision: {decision}"
                    ),
                    "turn_count": state.turn_count + 1,
                }
            )

        # Emit ReviewDecisionEvent
        review_id = uuid.uuid4().hex
        await record_worker_events(
            episode_id=state.episode_id,
            events=[
                ReviewDecisionEvent(
                    decision=decision,
                    reason=feedback,
                    review_id=review_id,
                    evidence_stats={
                        "is_plan_review": True,
                        "review_decision_path": review_decision_path,
                        "review_comments_path": review_comments_path,
                    },
                    checklist=review.checklist,
                )
            ],
        )

        return state.model_copy(
            update={
                "status": status_map[decision],
                "feedback": feedback,
                "journal": state.journal + journal_entry,
                "messages": [
                    *state.messages,
                    AIMessage(content=f"Plan Review decision: {decision.value}"),
                ],
                "turn_count": state.turn_count + 1,
            }
        )


# Factory function for LangGraph
@type_check
async def engineer_plan_reviewer_node(state: AgentState) -> AgentState:
    session_id = state.session_id
    if not session_id:
        msg = "Missing required session_id for engineer_plan_reviewer_node"
        raise ValueError(msg)
    episode_id = state.episode_id
    ctx = SharedNodeContext.create(
        worker_light_url=settings.worker_light_url,
        session_id=session_id,
        episode_id=episode_id,
        agent_role=AgentName.ENGINEER_PLAN_REVIEWER,
    )
    node = PlanReviewerNode(context=ctx)
    return await node(state)
