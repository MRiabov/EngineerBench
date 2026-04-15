from evals.logic.models import AgentEvalSpec
from shared.enums import AgentName, EvalMode
from shared.eval_artifacts import (
    workspace_artifacts_for_agent,
)
from shared.script_contracts import (
    BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH,
    SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
)

# Base planner artifact contract.
PLANNER_REQUIRED_FILES: dict[AgentName, tuple[str, ...]] = {
    AgentName.BENCHMARK_PLANNER: (
        "benchmark_plan.md",
        "todo.md",
        "benchmark_definition.yaml",
        "benchmark_assembly_definition.yaml",
        BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH,
    ),
    AgentName.ENGINEER_PLANNER: (
        "engineering_plan.md",
        "todo.md",
        "benchmark_definition.yaml",
        "assembly_definition.yaml",
        SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
    ),
}


def required_plan_artifacts_for_agent(agent_name: AgentName) -> tuple[str, ...]:
    """Return the eval-side planner-artifact contract for the requested role."""
    return workspace_artifacts_for_agent(agent_name)


AGENT_SPECS: dict[AgentName, AgentEvalSpec] = {
    AgentName.BENCHMARK_PLANNER: AgentEvalSpec(
        mode=EvalMode.BENCHMARK,
        request_agent_name=AgentName.BENCHMARK_PLANNER,
        required_trace_names=(AgentName.BENCHMARK_PLANNER,),
        start_node=AgentName.BENCHMARK_PLANNER,
    ),
    AgentName.BENCHMARK_CODER: AgentEvalSpec(
        mode=EvalMode.BENCHMARK,
        request_agent_name=AgentName.BENCHMARK_CODER,
        required_trace_names=(AgentName.BENCHMARK_CODER,),
        start_node=AgentName.BENCHMARK_CODER,
    ),
    AgentName.BENCHMARK_PLAN_REVIEWER: AgentEvalSpec(
        mode=EvalMode.BENCHMARK,
        request_agent_name=AgentName.BENCHMARK_PLANNER,
        required_trace_names=(AgentName.BENCHMARK_PLAN_REVIEWER,),
        start_node=AgentName.BENCHMARK_PLAN_REVIEWER,
        review_filename_prefix="benchmark-plan-review",
    ),
    AgentName.BENCHMARK_REVIEWER: AgentEvalSpec(
        mode=EvalMode.BENCHMARK,
        request_agent_name=AgentName.BENCHMARK_REVIEWER,
        required_trace_names=(AgentName.BENCHMARK_REVIEWER,),
        start_node=AgentName.BENCHMARK_REVIEWER,
        review_filename_prefix="benchmark-execution-review",
    ),
    AgentName.ENGINEER_PLANNER: AgentEvalSpec(
        mode=EvalMode.AGENT,
        request_agent_name=AgentName.ENGINEER_PLANNER,
        required_trace_names=(AgentName.ENGINEER_PLANNER,),
        start_node=AgentName.ENGINEER_PLANNER,
    ),
    AgentName.ENGINEER_CODER: AgentEvalSpec(
        mode=EvalMode.AGENT,
        request_agent_name=AgentName.ENGINEER_CODER,
        required_trace_names=(AgentName.ENGINEER_CODER,),
        start_node=AgentName.ENGINEER_CODER,
        required_reviewer_handover_manifest=(
            ".manifests/engineering_execution_handoff_manifest.json"
        ),
        required_reviewer_stage="engineering_execution_reviewer",
        materialize_reviewer_handover=True,
    ),
    AgentName.ENGINEER_PLAN_REVIEWER: AgentEvalSpec(
        mode=EvalMode.AGENT,
        request_agent_name=AgentName.ENGINEER_CODER,
        required_trace_names=(AgentName.ENGINEER_PLAN_REVIEWER,),
        start_node=AgentName.ENGINEER_PLAN_REVIEWER,
        review_filename_prefix="engineering-plan-review",
    ),
    AgentName.ENGINEER_EXECUTION_REVIEWER: AgentEvalSpec(
        mode=EvalMode.AGENT,
        request_agent_name=AgentName.ENGINEER_CODER,
        required_trace_names=(AgentName.ENGINEER_EXECUTION_REVIEWER,),
        start_node=AgentName.ENGINEER_EXECUTION_REVIEWER,
        review_filename_prefix="engineering-execution-review",
    ),
    AgentName.SKILL_AGENT: AgentEvalSpec(
        mode=EvalMode.AGENT,
        request_agent_name=AgentName.SKILL_AGENT,
        required_trace_names=(AgentName.SKILL_AGENT,),
    ),
    AgentName.GIT_AGENT: AgentEvalSpec(
        mode=EvalMode.GIT,
        request_agent_name=AgentName.GIT_AGENT,
    ),
}


JUDGE_REVIEWER_CHAIN: dict[AgentName, tuple[AgentName, ...]] = {
    AgentName.BENCHMARK_PLANNER: (AgentName.BENCHMARK_PLAN_REVIEWER,),
    AgentName.BENCHMARK_CODER: (AgentName.BENCHMARK_REVIEWER,),
    AgentName.ENGINEER_PLANNER: (AgentName.ENGINEER_PLAN_REVIEWER,),
    AgentName.ENGINEER_CODER: (AgentName.ENGINEER_EXECUTION_REVIEWER,),
}
