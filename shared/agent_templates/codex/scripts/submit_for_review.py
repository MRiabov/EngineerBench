from __future__ import annotations

import json
import os
import sys
import traceback
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from typing import Any

from build123d import Compound

from shared.current_role import current_role_agent_name
from shared.enums import AgentName
from shared.script_contracts import (
    authored_script_path_for_agent,
    role_family_for_agent,
)
from shared.workers.persistence import record_validation_result
from utils.submission import (
    simulate_benchmark,
    simulate_engineering,
    validate_benchmark,
    validate_engineering,
)
from worker_heavy.utils.handover import submit_for_review as _handover_submit_for_review


def _submission_agent(workspace: Path) -> AgentName | None:
    try:
        agent = current_role_agent_name(workspace)
    except Exception:
        return None

    if agent in {
        AgentName.BENCHMARK_CODER,
        AgentName.BENCHMARK_REVIEWER,
        AgentName.ENGINEER_CODER,
        AgentName.ENGINEER_EXECUTION_REVIEWER,
    }:
        return agent
    return None


def _reviewer_stage_for_agent(agent_name: AgentName) -> AgentName:
    stage_map = {
        AgentName.BENCHMARK_CODER: AgentName.BENCHMARK_REVIEWER,
        AgentName.BENCHMARK_REVIEWER: AgentName.BENCHMARK_REVIEWER,
        AgentName.ENGINEER_CODER: AgentName.ENGINEER_EXECUTION_REVIEWER,
        AgentName.ENGINEER_EXECUTION_REVIEWER: AgentName.ENGINEER_EXECUTION_REVIEWER,
    }
    try:
        return stage_map[agent_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported submission agent: {agent_name}") from exc


def _manifest_path_for_agent(agent_name: AgentName) -> Path:
    if agent_name in {
        AgentName.BENCHMARK_CODER,
        AgentName.BENCHMARK_REVIEWER,
    }:
        return Path(".manifests/benchmark_review_manifest.json")
    if agent_name in {
        AgentName.ENGINEER_CODER,
        AgentName.ENGINEER_EXECUTION_REVIEWER,
    }:
        return Path(".manifests/engineering_execution_handoff_manifest.json")
    raise ValueError(f"Unsupported submission agent: {agent_name}")


def _script_path_for_agent(agent_name: AgentName) -> Path:
    return authored_script_path_for_agent(agent_name)


def _role_family_for_submission(agent_name: AgentName) -> str:
    family = role_family_for_agent(agent_name)
    if family is None:
        raise ValueError(f"Unsupported submission agent: {agent_name}")
    return family


def _load_solution(script_path: Path) -> Compound:
    module = import_module(script_path.stem)
    solution = getattr(module, "build", None)
    if not callable(solution):
        raise ValueError(f"{script_path} must define build()")
    solution = solution()
    if not isinstance(solution, Compound):
        raise TypeError(
            f"{script_path} must export a build123d.Compound; got {type(solution).__name__}"
        )
    return solution


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)


def _submission_log_path(workspace: Path) -> Path:
    return workspace / "logs" / "submit_for_review.log"


@contextmanager
def _capture_submission_output(log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_handle:
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()
        saved_stdout_fd = os.dup(stdout_fd)
        saved_stderr_fd = os.dup(stderr_fd)
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        try:
            os.dup2(log_handle.fileno(), stdout_fd)
            os.dup2(log_handle.fileno(), stderr_fd)
            yield
        finally:
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass
            os.dup2(saved_stdout_fd, stdout_fd)
            os.dup2(saved_stderr_fd, stderr_fd)
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)


def main() -> int:
    workspace = Path.cwd()
    workspace_str = str(workspace)
    if workspace_str not in sys.path:
        sys.path.insert(0, workspace_str)
    session_id = os.getenv("SESSION_ID")
    episode_id = os.getenv("EPISODE_ID") or None
    agent_name = _submission_agent(workspace)
    log_path = _submission_log_path(workspace)
    payload: dict[str, Any]
    exit_code = 1

    if agent_name is None:
        payload = {
            "ok": False,
            "status": "rejected",
            "stage": "load",
            "message": (
                "Unable to infer submission agent from .manifests/current_role.json"
            ),
            "log_path": str(log_path.relative_to(workspace)),
        }
    else:
        rejection: dict[str, Any] | None = None
        validation_ok = False
        simulation_success = False
        family = _role_family_for_submission(agent_name)
        manifest_path = workspace / _manifest_path_for_agent(agent_name)

        with _capture_submission_output(log_path):
            try:
                solution = _load_solution(
                    script_path := _script_path_for_agent(agent_name)
                )
            except Exception as exc:
                traceback.print_exc()
                rejection = {
                    "ok": False,
                    "status": "rejected",
                    "stage": "load",
                    "message": str(exc),
                }
            else:
                if family == "benchmark":
                    validation_ok, validation_message = validate_benchmark(
                        solution,
                        output_dir=str(workspace),
                        session_id=session_id,
                    )
                else:
                    validation_ok, validation_message = validate_engineering(
                        solution,
                        output_dir=str(workspace),
                        session_id=session_id,
                    )
                record_validation_result(
                    workspace,
                    validation_ok,
                    validation_message,
                    script_path=script_path,
                    session_id=session_id,
                )
                if not validation_ok:
                    rejection = {
                        "ok": False,
                        "status": "rejected",
                        "stage": "validation",
                        "message": validation_message,
                    }
                else:
                    if family == "benchmark":
                        simulation_result = simulate_benchmark(
                            solution,
                            output_dir=str(workspace),
                            session_id=session_id,
                        )
                    else:
                        simulation_result = simulate_engineering(
                            solution,
                            output_dir=str(workspace),
                            session_id=session_id,
                        )
                    simulation_success = simulation_result.success

                    if not simulation_success:
                        rejection = {
                            "ok": False,
                            "status": "rejected",
                            "stage": "simulation",
                            "message": simulation_result.summary,
                        }
                    else:
                        submitted = _handover_submit_for_review(
                            solution,
                            cwd=workspace,
                            session_id=session_id,
                            reviewer_stage=_reviewer_stage_for_agent(agent_name),
                            episode_id=episode_id,
                            script_path=script_path,
                        )
                        if not submitted:
                            rejection = {
                                "ok": False,
                                "status": "rejected",
                                "stage": "handover",
                                "message": "submit_for_review returned false",
                            }

        log_path_rel = str(log_path.relative_to(workspace))
        if rejection is not None:
            rejection["log_path"] = log_path_rel
            payload = rejection
        else:
            payload = {
                "ok": True,
                "status": "submitted",
                "stage": _reviewer_stage_for_agent(agent_name),
                "manifest_path": str(manifest_path.relative_to(workspace))
                if manifest_path.exists()
                else None,
                "validation_success": validation_ok,
                "simulation_success": simulation_success,
                "log_path": log_path_rel,
            }
            exit_code = 0

    _print_json(payload)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
