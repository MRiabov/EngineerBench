from __future__ import annotations

from collections.abc import Iterable

from evals.logic.cli_args import parse_cli_int_set, parse_cli_list_values
from evals.logic.models import EvalDatasetItem
from evals.logic.specs import AGENT_SPECS
from shared.enums import AgentName


def resolve_agents(agent_args: Iterable[str]) -> list[AgentName]:
    parsed = parse_cli_list_values(agent_args)
    if not parsed:
        raise SystemExit("No valid --agent values were parsed.")

    if any(agent_arg.lower() == "all" for agent_arg in parsed):
        return list(AGENT_SPECS.keys())

    agents: list[AgentName] = []
    seen: set[AgentName] = set()
    for agent_arg in parsed:
        try:
            agent = AgentName(agent_arg)
        except ValueError as exc:
            available = ", ".join(sorted(agent.value for agent in AGENT_SPECS))
            raise SystemExit(
                f"Unknown agent '{agent_arg}'. Available: {available}"
            ) from exc

        if agent not in AGENT_SPECS:
            raise SystemExit(f"Agent '{agent.value}' is not configured in AGENT_SPECS.")
        if agent in seen:
            continue
        seen.add(agent)
        agents.append(agent)

    return agents


def parse_task_id_filters(raw_task_id_filters: Iterable[str] | None) -> set[str]:
    if not raw_task_id_filters:
        return set()
    return set(parse_cli_list_values(raw_task_id_filters))


def parse_level_filters(raw_level_filters: Iterable[str] | None) -> set[int]:
    if not raw_level_filters:
        return set()
    return parse_cli_int_set(
        raw_level_filters,
        minimum=0,
        maximum=5,
        label="complexity level",
    )


def filter_eval_rows(
    rows: list[EvalDatasetItem],
    *,
    task_ids: set[str] | None = None,
    levels: set[int] | None = None,
    limit: int = 0,
) -> list[EvalDatasetItem]:
    selected: list[EvalDatasetItem] = []
    for row in rows:
        if task_ids and row.id not in task_ids:
            continue
        if levels and row.complexity_level not in levels:
            continue
        selected.append(row)
        if limit > 0 and len(selected) >= limit:
            break
    return selected
