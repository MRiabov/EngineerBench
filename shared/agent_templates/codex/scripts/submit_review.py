from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from shared.current_role import current_role_agent_name
from shared.enums import AgentName
from shared.git_utils import commit_submission_attempt
from shared.models.schemas import ReviewComments, ReviewFrontmatter

_REVIEW_PREFIX_BY_AGENT: dict[AgentName, str] = {
    AgentName.BENCHMARK_PLAN_REVIEWER: "benchmark-plan-review",
    AgentName.BENCHMARK_REVIEWER: "benchmark-execution-review",
    AgentName.ENGINEER_PLAN_REVIEWER: "engineering-plan-review",
    AgentName.ENGINEER_EXECUTION_REVIEWER: "engineering-execution-review",
}

_MANIFEST_BY_AGENT: dict[AgentName, str] = {
    AgentName.BENCHMARK_PLAN_REVIEWER: ".manifests/benchmark_plan_review_manifest.json",
    AgentName.BENCHMARK_REVIEWER: ".manifests/benchmark_review_manifest.json",
    AgentName.ENGINEER_PLAN_REVIEWER: ".manifests/engineering_plan_review_manifest.json",
    AgentName.ENGINEER_EXECUTION_REVIEWER: ".manifests/engineering_execution_handoff_manifest.json",
}


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _reviewer_agent(workspace: Path) -> AgentName | None:
    try:
        agent = current_role_agent_name(workspace)
    except Exception:
        return None

    if agent in _REVIEW_PREFIX_BY_AGENT:
        return agent
    return None


def _review_prefix(agent_name: AgentName) -> str:
    return _REVIEW_PREFIX_BY_AGENT[agent_name]


def _review_dir(workspace: Path) -> Path:
    return workspace / "reviews"


def _round_from_match(match: re.Match[str]) -> int:
    return int(match.group(1))


def _parse_yaml_mapping(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"invalid YAML in {path.as_posix()}: {exc}"
    if not isinstance(data, dict):
        return None, f"unexpected YAML structure in {path}: expected mapping"
    return data, None


def _validate_review_markdown(
    path: Path,
) -> tuple[ReviewFrontmatter | None, str | None]:
    content = path.read_text(encoding="utf-8")
    match = re.search(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
    if match is None:
        return None, f"missing YAML frontmatter in {path}"
    try:
        data = yaml.safe_load(match.group(1))
    except Exception as exc:
        return None, f"invalid frontmatter YAML in {path}: {exc}"
    if not isinstance(data, dict):
        return None, f"unexpected frontmatter structure in {path}: expected mapping"
    try:
        return ReviewFrontmatter.model_validate(data), None
    except Exception as exc:
        return None, f"invalid review frontmatter in {path}: {exc}"


def _validate_yaml_review_pair(
    decision_path: Path, comments_path: Path
) -> tuple[ReviewFrontmatter | None, ReviewComments | None, str | None]:
    decision_data, decision_error = _parse_yaml_mapping(decision_path)
    if decision_error is not None:
        return None, None, decision_error
    comments_data, comments_error = _parse_yaml_mapping(comments_path)
    if comments_error is not None:
        return None, None, comments_error
    try:
        decision = ReviewFrontmatter.model_validate(decision_data)
    except Exception as exc:
        return None, None, f"invalid review decision payload in {decision_path}: {exc}"
    try:
        comments = ReviewComments.model_validate(comments_data)
    except Exception as exc:
        return (
            decision,
            None,
            f"invalid review comments payload in {comments_path}: {exc}",
        )
    return decision, comments, None


def _latest_review_rounds(
    review_dir: Path, prefix: str
) -> tuple[tuple[int, Path] | None, tuple[int, Path] | None, tuple[int, Path] | None]:
    decision_pattern = re.compile(rf"^{re.escape(prefix)}-decision-round-(\d+)\.yaml$")
    comments_pattern = re.compile(rf"^{re.escape(prefix)}-comments-round-(\d+)\.yaml$")
    markdown_pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)\.md$")

    latest_decision: tuple[int, Path] | None = None
    latest_comments: tuple[int, Path] | None = None
    latest_markdown: tuple[int, Path] | None = None
    for entry in review_dir.iterdir():
        if entry.is_dir():
            continue
        if match := decision_pattern.fullmatch(entry.name):
            current = (_round_from_match(match), entry)
            if latest_decision is None or current[0] > latest_decision[0]:
                latest_decision = current
            continue
        if match := comments_pattern.fullmatch(entry.name):
            current = (_round_from_match(match), entry)
            if latest_comments is None or current[0] > latest_comments[0]:
                latest_comments = current
            continue
        if match := markdown_pattern.fullmatch(entry.name):
            current = (_round_from_match(match), entry)
            if latest_markdown is None or current[0] > latest_markdown[0]:
                latest_markdown = current

    return latest_decision, latest_comments, latest_markdown


def main() -> int:
    workspace = Path.cwd()
    agent_name = _reviewer_agent(workspace)
    payload: dict[str, Any]
    exit_code = 1
    commit_message = "submit_review: unknown rejected"

    if agent_name is None:
        payload = {
            "ok": False,
            "status": "rejected",
            "stage": "load",
            "message": (
                "Unable to infer reviewer agent from .manifests/current_role.json"
            ),
        }
    else:
        review_dir = _review_dir(workspace)
        if not review_dir.exists():
            payload = {
                "ok": False,
                "status": "rejected",
                "stage": "load",
                "message": "reviews/ directory not found",
            }
            commit_message = f"submit_review: {agent_name.value} rejected"
        else:
            prefix = _review_prefix(agent_name)
            latest_decision, _latest_comments, latest_markdown = _latest_review_rounds(
                review_dir, prefix
            )

            if latest_decision is not None and (
                latest_markdown is None or latest_decision[0] >= latest_markdown[0]
            ):
                round_number = latest_decision[0]
                comments_path = (
                    review_dir / f"{prefix}-comments-round-{round_number}.yaml"
                )
                if not comments_path.exists():
                    payload = {
                        "ok": False,
                        "status": "rejected",
                        "stage": "validation",
                        "message": (
                            f"Missing comments file for {prefix} round {round_number}: "
                            f"{comments_path.name}"
                        ),
                    }
                    commit_message = f"submit_review: {agent_name.value} rejected"
                else:
                    decision, comments, error = _validate_yaml_review_pair(
                        latest_decision[1], comments_path
                    )
                    if error is not None:
                        payload = {
                            "ok": False,
                            "status": "rejected",
                            "stage": "validation",
                            "message": error,
                        }
                        commit_message = f"submit_review: {agent_name.value} rejected"
                    else:
                        payload = {
                            "ok": True,
                            "status": "submitted",
                            "stage": agent_name.value,
                            "review_kind": "yaml_pair",
                            "round": round_number,
                            "decision_path": str(
                                latest_decision[1].relative_to(workspace)
                            ),
                            "comments_path": str(comments_path.relative_to(workspace)),
                            "decision": decision.model_dump(mode="json"),
                            "comments": comments.model_dump(mode="json"),
                        }
                        commit_message = f"submit_review: {agent_name.value} submitted"
                        exit_code = 0
            elif latest_markdown is not None:
                round_number = latest_markdown[0]
                frontmatter, error = _validate_review_markdown(latest_markdown[1])
                if error is not None:
                    payload = {
                        "ok": False,
                        "status": "rejected",
                        "stage": "validation",
                        "message": error,
                    }
                    commit_message = f"submit_review: {agent_name.value} rejected"
                else:
                    payload = {
                        "ok": True,
                        "status": "submitted",
                        "stage": agent_name.value,
                        "review_kind": "markdown",
                        "round": round_number,
                        "review_path": str(latest_markdown[1].relative_to(workspace)),
                        "frontmatter": frontmatter.model_dump(mode="json"),
                    }
                    commit_message = f"submit_review: {agent_name.value} submitted"
                    exit_code = 0
            else:
                payload = {
                    "ok": False,
                    "status": "rejected",
                    "stage": "validation",
                    "message": (
                        f"No review artifact matching {prefix}-decision-round-<n>.yaml, "
                        f"{prefix}-comments-round-<n>.yaml, or {prefix}-<n>.md"
                    ),
                }
                commit_message = f"submit_review: {agent_name.value} rejected"

    if agent_name is None:
        commit_message = "submit_review: unknown rejected"
    commit_submission_attempt(workspace, commit_message)
    _print_json(payload)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
