from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from controller.agent.benchmark.tools import _canonicalize_benchmark_constraints
from shared.current_role import current_role_agent_name
from shared.enums import AgentName
from shared.git_utils import commit_submission_attempt, repo_revision
from shared.models.schemas import PlannerSubmissionResult
from shared.script_contracts import plan_path_for_agent
from shared.workers.schema import PlanReviewManifest
from worker_heavy.utils.dfm import (
    load_planner_manufacturing_config_from_text,
)
from worker_heavy.utils.file_validation import validate_node_output


def _planner_agent(workspace: Path | None = None) -> AgentName | None:
    workspace = Path.cwd() if workspace is None else Path(workspace)
    try:
        agent_name = current_role_agent_name(workspace)
    except Exception:
        return None

    if agent_name in {
        AgentName.BENCHMARK_PLANNER,
        AgentName.ENGINEER_PLANNER,
    }:
        return agent_name
    return None


def _session_id() -> str:
    return os.getenv("SESSION_ID", "local-submit-plan")


def _derived_episode_id(session_id: str) -> str:
    try:
        return str(uuid.UUID(session_id))
    except Exception:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, session_id))


def _workspace_environment_version(workspace: Path) -> str | None:
    candidate = (
        workspace / "benchmark_assembly_definition.yaml"
        if (workspace / "benchmark_assembly_definition.yaml").exists()
        else workspace / "assembly_definition.yaml"
    )
    if not candidate.exists():
        return None
    try:
        import yaml

        data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    version = data.get("version")
    if version is None:
        return None
    version_text = str(version).strip()
    return version_text or None


def _required_files(agent_name: AgentName) -> tuple[str, ...]:
    if agent_name == AgentName.BENCHMARK_PLANNER:
        return (
            "todo.md",
            "benchmark_definition.yaml",
            "benchmark_assembly_definition.yaml",
            "manufacturing_config.yaml",
        )
    return (
        "todo.md",
        "benchmark_definition.yaml",
        "assembly_definition.yaml",
        "manufacturing_config.yaml",
    )


def _manifest_info(agent_name: AgentName) -> tuple[Path, AgentName]:
    if agent_name == AgentName.BENCHMARK_PLANNER:
        return (
            Path(".manifests/benchmark_plan_review_manifest.json"),
            AgentName.BENCHMARK_PLAN_REVIEWER,
        )
    return (
        Path(".manifests/engineering_plan_review_manifest.json"),
        AgentName.ENGINEER_PLAN_REVIEWER,
    )


def _planner_role_for_agent(agent_name: AgentName) -> AgentName | None:
    if agent_name == AgentName.BENCHMARK_PLANNER:
        return AgentName.BENCHMARK_PLANNER
    if agent_name == AgentName.ENGINEER_PLANNER:
        return AgentName.ENGINEER_PLANNER
    return None


def _read_workspace_files(workspace: Path, paths: tuple[str, ...]) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    missing: list[str] = []

    for rel_path in paths:
        file_path = workspace / rel_path
        if not file_path.exists():
            missing.append(rel_path)
            continue
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            missing.append(rel_path)
            continue
        artifacts[rel_path] = content

    if missing:
        raise ValueError("Missing required file(s): " + ", ".join(missing))
    return artifacts


def _planner_role_error(
    helper_name: str,
    agent_name: AgentName | None,
    allowed_roles: tuple[AgentName, ...],
) -> PlannerSubmissionResult | None:
    if agent_name is None:
        return PlannerSubmissionResult(
            ok=False,
            status="rejected",
            errors=["Unable to infer planner agent from .manifests/current_role.json"],
            node_type=AgentName.ENGINEER_PLANNER,
        )

    if agent_name in allowed_roles:
        return None

    allowed_roles_text = ", ".join(role.value for role in allowed_roles)
    return PlannerSubmissionResult(
        ok=False,
        status="rejected",
        errors=[
            f"{helper_name} requires current role one of {allowed_roles_text}; "
            f"found {agent_name.value}",
        ],
        node_type=agent_name,
    )


def _submit_plan(workspace: Path | None = None) -> PlannerSubmissionResult:
    workspace = Path.cwd() if workspace is None else Path(workspace)
    agent_name = _planner_agent(workspace)
    session_id = _session_id()

    if agent_name is None:
        return PlannerSubmissionResult(
            ok=False,
            status="rejected",
            errors=["Unable to infer planner agent from .manifests/current_role.json"],
            node_type=AgentName.ENGINEER_PLANNER,
        )

    plan_path = plan_path_for_agent(agent_name)
    required_files = [plan_path.name, *_required_files(agent_name)]
    try:
        artifacts = _read_workspace_files(workspace, tuple(required_files))
    except Exception as exc:
        return PlannerSubmissionResult(
            ok=False,
            status="rejected",
            errors=[str(exc)],
            node_type=agent_name,
        )

    if agent_name == AgentName.BENCHMARK_PLANNER:
        canonical_benchmark_definition, canonicalization_errors = (
            _canonicalize_benchmark_constraints(artifacts["benchmark_definition.yaml"])
        )
        if canonicalization_errors:
            return PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=canonicalization_errors,
                node_type=agent_name,
            )

        artifacts["benchmark_definition.yaml"] = canonical_benchmark_definition
        workspace.joinpath("benchmark_definition.yaml").write_text(
            canonical_benchmark_definition,
            encoding="utf-8",
        )

    try:
        manufacturing_config_text = artifacts["manufacturing_config.yaml"]
        manufacturing_config = load_planner_manufacturing_config_from_text(
            manufacturing_config_text
        )
    except Exception as exc:
        return PlannerSubmissionResult(
            ok=False,
            status="rejected",
            errors=[f"failed to load manufacturing_config.yaml: {exc}"],
            node_type=agent_name,
        )

    artifacts["manufacturing_config.yaml"] = manufacturing_config_text

    is_valid, errors = validate_node_output(
        agent_name,
        artifacts,
        session_id=session_id,
        manufacturing_config=manufacturing_config,
    )
    if not is_valid:
        return PlannerSubmissionResult(
            ok=False,
            status="rejected",
            errors=errors,
            node_type=agent_name,
        )

    manifest_path, reviewer_stage = _manifest_info(agent_name)
    manifest_path = workspace / manifest_path
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = PlanReviewManifest(
        status="ready_for_review",
        reviewer_stage=reviewer_stage,
        session_id=session_id,
        planner_node_type=agent_name,
        episode_id=os.getenv("EPISODE_ID") or _derived_episode_id(session_id),
        worker_session_id=session_id,
        benchmark_revision=repo_revision(workspace),
        environment_version=_workspace_environment_version(workspace),
        artifact_hashes={
            rel_path: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for rel_path, content in artifacts.items()
        },
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    visible_manifest_path = workspace / (
        "benchmark_plan_review_manifest.json"
        if agent_name == AgentName.BENCHMARK_PLANNER
        else "engineering_plan_review_manifest.json"
    )
    visible_manifest_path.write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )

    return PlannerSubmissionResult(
        ok=True,
        status="submitted",
        errors=[],
        node_type=agent_name,
    )


def submit_benchmark_plan(workspace: Path | None = None) -> PlannerSubmissionResult:
    workspace = Path.cwd() if workspace is None else Path(workspace)
    role_error = _planner_role_error(
        "submit_benchmark_plan",
        _planner_agent(workspace),
        (AgentName.BENCHMARK_PLANNER,),
    )
    if role_error is not None:
        return role_error
    return _submit_plan(workspace)


def submit_engineering_plan(workspace: Path | None = None) -> PlannerSubmissionResult:
    workspace = Path.cwd() if workspace is None else Path(workspace)
    role_error = _planner_role_error(
        "submit_engineering_plan",
        _planner_agent(workspace),
        (AgentName.ENGINEER_PLANNER,),
    )
    if role_error is not None:
        return role_error
    return _submit_plan(workspace)


def main() -> int:
    workspace = Path.cwd()
    helper_name = "submit_plan"
    try:
        agent_name = _planner_agent(workspace)
        if agent_name == AgentName.BENCHMARK_PLANNER:
            helper_name = "submit_benchmark_plan"
            result = submit_benchmark_plan(workspace)
        elif agent_name == AgentName.ENGINEER_PLANNER:
            helper_name = "submit_engineering_plan"
            result = submit_engineering_plan(workspace)
        else:
            helper_name = "submit_plan"
            result = PlannerSubmissionResult(
                ok=False,
                status="rejected",
                errors=[
                    "Unable to infer planner agent from .manifests/current_role.json"
                ],
                node_type=AgentName.ENGINEER_PLANNER,
            )
    except Exception as exc:
        result = PlannerSubmissionResult(
            ok=False,
            status="rejected",
            errors=[f"{helper_name} execution failed: {exc}"],
            node_type=_planner_agent() or AgentName.ENGINEER_PLANNER,
        )
        commit_message = f"{helper_name}: {result.node_type.value} rejected"
        commit_submission_attempt(workspace, commit_message)
        print(result.model_dump_json(indent=2))
        return 1
    commit_message = f"{helper_name}: {result.node_type.value} {result.status}"
    commit_submission_attempt(workspace, commit_message)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
