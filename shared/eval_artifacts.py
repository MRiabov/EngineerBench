from __future__ import annotations

from shared.enums import AgentName
from shared.script_contracts import (
    BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH,
    CURRENT_ROLE_MANIFEST_PATH,
    SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
)

_BENCHMARK_PLAN_BASE_FILES: tuple[str, ...] = (
    "benchmark_plan.md",
    "todo.md",
    "benchmark_definition.yaml",
    "benchmark_assembly_definition.yaml",
    BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH,
)

_ENGINEER_PLAN_BASE_FILES: tuple[str, ...] = (
    "engineering_plan.md",
    "todo.md",
    "benchmark_definition.yaml",
    "assembly_definition.yaml",
    "benchmark_plan.md",
    SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
)

SEED_STARTER_TEMPLATE_FILES: dict[AgentName, tuple[str, ...]] = {
    AgentName.BENCHMARK_PLANNER: _BENCHMARK_PLAN_BASE_FILES,
    AgentName.ENGINEER_PLANNER: (
        "engineering_plan.md",
        "todo.md",
        "assembly_definition.yaml",
        SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
    ),
    AgentName.BENCHMARK_CODER: (
        "benchmark_script.py",
        "todo.md",
        "journal.md",
    ),
    AgentName.ENGINEER_CODER: (
        "solution_script.py",
        "payload_trajectory_definition.yaml",
        "todo.md",
        "journal.md",
    ),
    AgentName.BENCHMARK_PLAN_REVIEWER: (
        "todo.md",
        "journal.md",
    ),
    AgentName.BENCHMARK_REVIEWER: (
        "todo.md",
        "journal.md",
    ),
    AgentName.ENGINEER_PLAN_REVIEWER: (
        "todo.md",
        "journal.md",
    ),
    AgentName.ENGINEER_EXECUTION_REVIEWER: (
        "todo.md",
        "journal.md",
    ),
}

SEED_TEMPLATE_EXCLUSION_FILES: dict[AgentName, tuple[str, ...]] = {
    agent_name: paths for agent_name, paths in SEED_STARTER_TEMPLATE_FILES.items()
}


def seed_starter_template_files_for_agent(agent_name: AgentName) -> tuple[str, ...]:
    return SEED_STARTER_TEMPLATE_FILES.get(agent_name, ())


def seed_template_exclusion_files_for_agent(agent_name: AgentName) -> tuple[str, ...]:
    return SEED_TEMPLATE_EXCLUSION_FILES.get(agent_name, ())


def plan_artifacts_for_agent(agent_name: AgentName) -> tuple[str, ...]:
    if agent_name in {
        AgentName.BENCHMARK_PLANNER,
        AgentName.BENCHMARK_PLAN_REVIEWER,
        AgentName.BENCHMARK_CODER,
        AgentName.BENCHMARK_REVIEWER,
    }:
        return _BENCHMARK_PLAN_BASE_FILES

    if agent_name in {
        AgentName.ENGINEER_PLANNER,
        AgentName.ENGINEER_PLAN_REVIEWER,
        AgentName.ENGINEER_CODER,
        AgentName.ENGINEER_EXECUTION_REVIEWER,
    }:
        return _ENGINEER_PLAN_BASE_FILES

    return ()


def workspace_artifacts_for_agent(agent_name: AgentName) -> tuple[str, ...]:
    """Return the base workspace contract including backend-owned metadata."""
    return (
        CURRENT_ROLE_MANIFEST_PATH.as_posix(),
        *plan_artifacts_for_agent(agent_name),
    )


__all__ = [
    "plan_artifacts_for_agent",
    "seed_template_exclusion_files_for_agent",
    "seed_starter_template_files_for_agent",
    "workspace_artifacts_for_agent",
]
