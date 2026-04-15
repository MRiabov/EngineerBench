from contextlib import suppress

import dspy
import structlog
from langchain_core.messages import AIMessage

from controller.agent.config import settings
from controller.agent.state import AgentState, AgentStatus
from controller.agent.tools import get_engineer_planner_tools
from controller.observability.tracing import record_worker_events
from shared.enums import AgentName
from shared.observability.schemas import SubmissionValidationEvent
from shared.script_contracts import SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH
from shared.type_checking import type_check

from .base import BaseNode, SharedNodeContext

logger = structlog.get_logger(__name__)


class PlannerSignature(dspy.Signature):
    """DSPy signature for the engineer planner."""

    task = dspy.InputField()
    objectives = dspy.InputField()
    benchmark_assembly_definition = dspy.InputField()
    skills = dspy.InputField()
    feedback = dspy.InputField()
    summary = dspy.OutputField(desc="A summary of the plan created")


@type_check
class PlannerNode(BaseNode):
    """
    Planner node: Analyzes the task and creates engineering_plan.md and todo.md using tools.
    Refactored to use DSPy ReAct with remote worker execution.
    """

    async def __call__(self, state: AgentState) -> AgentState:
        """Execute the planner node logic."""
        # T006: Read skills
        skills_context = self._get_skills_context()

        # Read objectives for context
        objectives = "# No benchmark_definition.yaml found."
        with suppress(Exception):
            objectives = await self._read_optional_workspace_file(
                "benchmark_definition.yaml", objectives
            )
        benchmark_assembly_definition = await self._read_required_workspace_file(
            "benchmark_assembly_definition.yaml"
        )

        inputs = {
            "task": state.task,
            "objectives": objectives,
            "benchmark_assembly_definition": benchmark_assembly_definition,
            "skills": skills_context,
            "feedback": (
                state.feedback
                if state.status == AgentStatus.PLAN_REJECTED
                else "New planning. No rejection feedback."
            ),
        }
        validate_files = [
            "engineering_plan.md",
            "todo.md",
            "benchmark_definition.yaml",
            "assembly_definition.yaml",
            "benchmark_assembly_definition.yaml",
            SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
        ]

        prediction, artifacts, journal_entry = await self._run_program(
            dspy.ReAct,
            PlannerSignature,
            state,
            inputs,
            get_engineer_planner_tools,
            validate_files,
            AgentName.ENGINEER_PLANNER,
        )

        if not prediction:
            return state.model_copy(
                update={
                    "status": AgentStatus.FAILED,
                    "journal": state.journal + journal_entry,
                    "turn_count": state.turn_count + 1,
                }
            )

        submission, submit_err = await self._get_latest_submit_plan_result(
            AgentName.ENGINEER_PLANNER
        )
        submit_tool_name = self._planner_submission_tool_name(
            AgentName.ENGINEER_PLANNER
        )
        if submission is None or not submission.ok or submission.status != "submitted":
            submit_errors = (
                [submit_err]
                if submit_err
                else (
                    submission.errors if submission else [f"{submit_tool_name} failed"]
                )
            )
            return state.model_copy(
                update={
                    "status": AgentStatus.FAILED,
                    "journal": (
                        state.journal
                        + f"\n[Planner] {submit_tool_name} validation failed: "
                        + "; ".join([e for e in submit_errors if e])
                        + journal_entry
                    ),
                    "turn_count": state.turn_count + 1,
                }
            )

        # Success

        await record_worker_events(
            episode_id=state.episode_id,
            events=[
                SubmissionValidationEvent(
                    artifacts_present=list(artifacts.keys()),
                    verification_passed=True,
                    reasoning_trace_quality=1.0,
                    errors=[],
                )
            ],
        )

        summary = getattr(prediction, "summary", "No summary provided.")
        return state.model_copy(
            update={
                "plan": artifacts.get("engineering_plan.md", ""),
                "todo": artifacts.get("todo.md", ""),
                "status": AgentStatus.EXECUTING,
                "journal": state.journal + f"\n[Planner] {summary}" + journal_entry,
                "messages": [
                    *state.messages,
                    AIMessage(content=f"Plan summary: {summary}"),
                ],
                "turn_count": state.turn_count + 1,
            }
        )


# Factory function for LangGraph
@type_check
async def planner_node(state: AgentState) -> AgentState:
    session_id = state.session_id
    if not session_id:
        msg = "Missing required session_id for planner_node"
        raise ValueError(msg)
    episode_id = state.episode_id
    ctx = SharedNodeContext.create(
        worker_light_url=settings.worker_light_url,
        session_id=session_id,
        episode_id=episode_id,
        agent_role=AgentName.ENGINEER_PLANNER,
    )
    node = PlannerNode(context=ctx)
    return await node(state)
