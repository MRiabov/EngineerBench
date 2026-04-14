import ast
import hashlib
import os
import uuid
from pathlib import Path

import httpx
import pytest
import yaml

from controller.api.schemas import AgentRunRequest, AgentRunResponse, EpisodeResponse
from shared.enums import AgentName, EpisodeStatus, ReviewDecision
from shared.workers.schema import PlanReviewManifest
from tests.integration.agent.helpers import (
    seed_benchmark_assembly_definition,
    seed_current_revision_render_preview,
    seed_execution_reviewer_handover,
    wait_for_episode_state,
    wait_for_episode_terminal,
)

CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")
pytestmark = pytest.mark.xdist_group(name="physics_sims")


def _has_expected_review_evidence(
    episode: EpisodeResponse, *, required_checklist_pairs: tuple[tuple[str, str], ...]
) -> bool:
    traces = episode.traces or []
    review_traces = [
        trace
        for trace in traces
        if trace.name == "review_decision" and trace.metadata_vars is not None
    ]
    return all(
        any(
            trace.metadata_vars.checklist.get(checklist_key) == expected_value
            for trace in review_traces
        )
        for checklist_key, expected_value in required_checklist_pairs
    )


def _parse_event_payload(trace) -> dict:
    if not trace.content:
        return {}
    try:
        payload = ast.literal_eval(trace.content)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_inspect_media_trace(trace) -> bool:
    return (
        trace.name in {"inspect_media", "inspect_media_tool"}
        and getattr(trace.trace_type, "value", str(trace.trace_type)) == "TOOL_START"
    )


def _expected_minimal_dofs_payload(trace) -> dict[str, object]:
    payload = _parse_event_payload(trace)
    assert payload, f"Expected event payload for trace {trace}"
    assert payload.get("dof_count_gt_3") is True, payload
    assert isinstance(payload.get("expected_minimal_engineering_dofs"), list), payload
    assert isinstance(payload.get("expected_minimal_dofs"), list), payload
    assert (
        payload["expected_minimal_engineering_dofs"] == payload["expected_minimal_dofs"]
    ), payload
    assert len(payload["expected_minimal_engineering_dofs"]) == 3, payload
    assert len(payload["expected_minimal_dofs"]) == 3, payload
    return payload


async def _wait_for_trace(
    episode_id: str,
    *,
    trace_name: str,
    predicate,
    attempts: int = 10,
) -> list:
    async with httpx.AsyncClient(timeout=30.0) as client:
        episode: EpisodeResponse = EpisodeResponse.model_validate(
            await wait_for_episode_state(
                client,
                episode_id,
                timeout_s=float(attempts),
                terminal_statuses={
                    EpisodeStatus.COMPLETED,
                    EpisodeStatus.FAILED,
                    EpisodeStatus.CANCELLED,
                    EpisodeStatus.PLANNED,
                },
                predicate=lambda episode: any(
                    trace.name == trace_name and predicate(trace)
                    for trace in (episode.traces or [])
                ),
            )
        )
    return [
        trace
        for trace in (episode.traces or [])
        if trace.name == trace_name and predicate(trace)
    ]


async def _run_and_wait(
    client: httpx.AsyncClient,
    *,
    agent_name: AgentName,
    session_id: str,
    task: str,
    start_node: AgentName | None = None,
    seed_benchmark_assembly: bool = True,
) -> EpisodeResponse:
    if seed_benchmark_assembly:
        await seed_benchmark_assembly_definition(
            client,
            session_id,
            benchmark_max_unit_cost_usd=250.0,
            benchmark_max_weight_g=2500.0,
            planner_target_max_unit_cost_usd=250.0,
            planner_target_max_weight_g=2500.0,
        )
    req = AgentRunRequest(
        task=task,
        session_id=session_id,
        agent_name=agent_name,
        start_node=start_node,
    )
    run_resp = await client.post(
        f"{CONTROLLER_URL}/api/agent/run",
        json=req.model_dump(mode="json"),
    )
    assert run_resp.status_code == 202, run_resp.text
    run = AgentRunResponse.model_validate(run_resp.json())

    return EpisodeResponse.model_validate(
        await wait_for_episode_terminal(
            client,
            str(run.episode_id),
            timeout_s=180.0,
            terminal_statuses={
                EpisodeStatus.COMPLETED,
                EpisodeStatus.FAILED,
                EpisodeStatus.CANCELLED,
                EpisodeStatus.PLANNED,
            },
        )
    )


async def _seed_plan_reviewer_handoff(
    client: httpx.AsyncClient, session_id: str
) -> None:
    for relative_path in (
        "engineering_plan.md",
        "todo.md",
        "assembly_definition.yaml",
        "benchmark_definition.yaml",
    ):
        content = Path(
            "tests/integration/mock_responses/INT-074/engineer_planner/entry_01/"
            + {
                "engineering_plan.md": "01__plan.md",
                "todo.md": "02__todo.md",
                "assembly_definition.yaml": "03__assembly_definition.yaml",
                "benchmark_definition.yaml": "04__benchmark_definition.yaml",
            }[relative_path]
        ).read_text(encoding="utf-8")
        await client.post(
            "http://127.0.0.1:18001/fs/write",
            json={
                "path": relative_path,
                "content": content,
                "overwrite": True,
            },
            headers={"X-Session-ID": session_id},
        )


async def _seed_engineer_plan_review_manifest(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    artifact_hashes: dict[str, str],
) -> None:
    manifest = PlanReviewManifest(
        status="ready_for_review",
        reviewer_stage=AgentName.ENGINEER_PLAN_REVIEWER,
        session_id=session_id,
        planner_node_type=AgentName.ENGINEER_PLANNER,
        artifact_hashes=artifact_hashes,
    )
    response = await client.post(
        "http://127.0.0.1:18001/fs/write",
        json={
            "path": ".manifests/engineering_plan_review_manifest.json",
            "content": manifest.model_dump_json(indent=2),
            "overwrite": True,
            "bypass_agent_permissions": True,
        },
        headers={"X-Session-ID": session_id, "X-System-FS-Bypass": "1"},
    )
    assert response.status_code == 200, response.text


async def _read_session_file(
    client: httpx.AsyncClient, session_id: str, path: str
) -> str:
    response = await client.post(
        "http://127.0.0.1:18001/fs/read",
        json={"path": path, "bypass_agent_permissions": False},
        headers={"X-Session-ID": session_id},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "content" in payload, payload
    return payload["content"]


async def _wait_for_review_evidence(
    client: httpx.AsyncClient,
    *,
    episode_id: str,
    required_checklist_pairs: tuple[tuple[str, str], ...],
    attempts: int = 10,
) -> EpisodeResponse:
    return EpisodeResponse.model_validate(
        await wait_for_episode_state(
            client,
            episode_id,
            timeout_s=float(attempts),
            terminal_statuses={
                EpisodeStatus.COMPLETED,
                EpisodeStatus.FAILED,
                EpisodeStatus.CANCELLED,
                EpisodeStatus.PLANNED,
            },
            predicate=lambda episode: _has_expected_review_evidence(
                episode,
                required_checklist_pairs=required_checklist_pairs,
            ),
        )
    )


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_074_engineering_dof_minimization_review_gate():
    """
    INT-074: Plan/execution reviewers must flag excessive DOFs (`len(dofs) > 3`)
    unless explicit accepted justification is present.
    """
    async with httpx.AsyncClient(timeout=300.0) as client:
        plan_session = f"INT-074-{uuid.uuid4().hex[:8]}"
        await seed_benchmark_assembly_definition(
            client,
            plan_session,
            benchmark_max_unit_cost_usd=250.0,
            benchmark_max_weight_g=2500.0,
            planner_target_max_unit_cost_usd=250.0,
            planner_target_max_weight_g=2500.0,
        )
        benchmark_script_content = Path(
            "tests/integration/mock_responses/INT-010/benchmark_coder/entry_01/01__benchmark_script.py"
        ).read_text(encoding="utf-8")
        await client.post(
            "http://127.0.0.1:18001/fs/write",
            json={
                "path": "benchmark_script.py",
                "content": benchmark_script_content,
                "overwrite": True,
            },
            headers={"X-Session-ID": plan_session},
        )
        await _seed_plan_reviewer_handoff(client, plan_session)
        benchmark_definition_content = await _read_session_file(
            client, plan_session, "benchmark_definition.yaml"
        )
        benchmark_assembly_content = await _read_session_file(
            client, plan_session, "benchmark_assembly_definition.yaml"
        )
        plan_content = await _read_session_file(
            client, plan_session, "engineering_plan.md"
        )
        todo_content = await _read_session_file(client, plan_session, "todo.md")
        assembly_definition_content = await _read_session_file(
            client, plan_session, "assembly_definition.yaml"
        )
        await _seed_engineer_plan_review_manifest(
            client,
            plan_session,
            artifact_hashes={
                "engineering_plan.md": hashlib.sha256(
                    plan_content.encode("utf-8")
                ).hexdigest(),
                "todo.md": hashlib.sha256(todo_content.encode("utf-8")).hexdigest(),
                "benchmark_definition.yaml": hashlib.sha256(
                    benchmark_definition_content.encode("utf-8")
                ).hexdigest(),
                "assembly_definition.yaml": hashlib.sha256(
                    assembly_definition_content.encode("utf-8")
                ).hexdigest(),
                "benchmark_assembly_definition.yaml": hashlib.sha256(
                    benchmark_assembly_content.encode("utf-8")
                ).hexdigest(),
            },
        )
        await seed_current_revision_render_preview(client, session_id=plan_session)
        planner_episode = await _run_and_wait(
            client,
            agent_name=AgentName.ENGINEER_PLANNER,
            session_id=plan_session,
            task="INT-074 plan reviewer DOF minimization gate",
        )
        assert planner_episode.status in {
            EpisodeStatus.COMPLETED,
            EpisodeStatus.FAILED,
            EpisodeStatus.CANCELLED,
            EpisodeStatus.PLANNED,
        }, planner_episode

        await seed_current_revision_render_preview(client, session_id=plan_session)
        plan_episode = await _run_and_wait(
            client,
            agent_name=AgentName.ENGINEER_PLAN_REVIEWER,
            session_id=plan_session,
            task="INT-074 plan reviewer DOF minimization gate",
            start_node=AgentName.ENGINEER_PLAN_REVIEWER,
        )
        assert _has_expected_review_evidence(
            plan_episode,
            required_checklist_pairs=(("dof_minimality", "fail"),),
        ), plan_episode
        plan_review_traces = [
            trace
            for trace in plan_episode.traces
            if trace.name == "review_decision" and trace.metadata_vars is not None
        ]
        assert plan_review_traces, "Expected plan review_decision trace"
        latest_plan_review_trace = max(plan_review_traces, key=lambda trace: trace.id)
        inspect_media_traces = [
            trace for trace in plan_episode.traces if _is_inspect_media_trace(trace)
        ]
        assert inspect_media_traces, (
            "Plan reviewer rejection must call inspect_media()."
        )
        assert any(
            trace.id < latest_plan_review_trace.id for trace in inspect_media_traces
        ), "inspect_media must occur before the final plan review decision."
        plan_dof_event_traces = [
            trace
            for trace in plan_episode.traces
            if trace.name == "excessive_dof_detected"
        ]
        assert plan_dof_event_traces, "Expected excessive_dof_detected trace"
        plan_dof_event = next(
            trace
            for trace in plan_dof_event_traces
            if _parse_event_payload(trace).get("reviewer_stage")
            == "engineering_plan_reviewer"
        )
        plan_dof_payload = _expected_minimal_dofs_payload(plan_dof_event)
        assert plan_dof_payload["part_id"] == "over_actuated_link", plan_dof_payload
        assert plan_dof_payload["expected_minimal_engineering_dofs"] == [
            "tx",
            "ty",
            "tz",
        ], plan_dof_payload
        assert any(trace.id < plan_dof_event.id for trace in inspect_media_traces), (
            "inspect_media must occur before the excessive_dof_detected decision."
        )
        assert plan_episode.status != EpisodeStatus.COMPLETED
        plan_decision_path = "reviews/engineering-plan-review-decision-round-1.yaml"
        plan_comments_path = "reviews/engineering-plan-review-comments-round-1.yaml"
        plan_comments_resp = await client.get(
            f"{CONTROLLER_URL}/episodes/{plan_episode.id}/assets/{plan_comments_path}"
        )
        assert plan_comments_resp.status_code == 200, plan_comments_resp.text
        plan_comments = yaml.safe_load(plan_comments_resp.text)
        assert plan_comments["summary"].startswith("REJECTED:"), plan_comments
        assert plan_comments["checklist"]["dof_minimality"] == "fail", plan_comments
        plan_decision_resp = await client.get(
            f"{CONTROLLER_URL}/episodes/{plan_episode.id}/assets/{plan_decision_path}"
        )
        assert plan_decision_resp.status_code == 200, plan_decision_resp.text

        # Justified-motion path: the approved plan must persist the canonical
        # DOF checklist key.
        justified_session = f"INT-075-{uuid.uuid4().hex[:8]}"
        await seed_execution_reviewer_handover(
            client,
            session_id=justified_session,
            int_id="INT-075",
        )
        justified_episode = await _run_and_wait(
            client,
            agent_name=AgentName.ENGINEER_CODER,
            session_id=justified_session,
            task="INT-074 justified-motion acceptance gate",
        )
        justified_episode = await _wait_for_review_evidence(
            client,
            episode_id=str(justified_episode.id),
            required_checklist_pairs=(
                ("dof_minimality", "pass"),
                ("dof_deviation_justified", "pass"),
            ),
        )
        assert _has_expected_review_evidence(
            justified_episode,
            required_checklist_pairs=(
                ("dof_minimality", "pass"),
                ("dof_deviation_justified", "pass"),
            ),
        ), justified_episode
        justified_review_traces = [
            t
            for t in justified_episode.traces
            if t.name == "review_decision"
            and t.metadata_vars is not None
            and t.metadata_vars.decision == ReviewDecision.APPROVED
        ]
        assert justified_review_traces, (
            "Expected approved review_decision trace for justified DOF path"
        )
        assert any(
            trace.metadata_vars.checklist.get("dof_minimality") == "pass"
            for trace in justified_review_traces
        ), "Expected canonical dof_minimality checklist key in approved plan trace"

        justified_plan_comments_path = (
            "reviews/engineering-plan-review-comments-round-1.yaml"
        )
        comments_resp = await client.get(
            f"{CONTROLLER_URL}/episodes/{justified_episode.id}/assets/"
            f"{justified_plan_comments_path}"
        )
        assert comments_resp.status_code == 200, comments_resp.text
        comments = yaml.safe_load(comments_resp.text)
        assert comments["summary"].startswith("APPROVED:"), comments
        assert comments["checklist"]["dof_minimality"] == "pass", comments
        execution_comments_path = (
            "reviews/engineering-execution-review-comments-round-1.yaml"
        )
        execution_comments_resp = await client.get(
            f"{CONTROLLER_URL}/episodes/{justified_episode.id}/assets/"
            f"{execution_comments_path}"
        )
        assert execution_comments_resp.status_code == 200, execution_comments_resp.text
        execution_comments = yaml.safe_load(execution_comments_resp.text)
        assert execution_comments["checklist"]["dof_deviation_justified"] == "pass", (
            execution_comments
        )

        # Regression: the justification marker must be explicit and standalone.
        strict_marker_session = f"INT-075-{uuid.uuid4().hex[:8]}"
        await seed_benchmark_assembly_definition(
            client,
            strict_marker_session,
            benchmark_max_unit_cost_usd=250.0,
            benchmark_max_weight_g=2500.0,
            planner_target_max_unit_cost_usd=250.0,
            planner_target_max_weight_g=2500.0,
        )
        await seed_current_revision_render_preview(
            client, session_id=strict_marker_session
        )
        benchmark_definition_content = Path(
            "tests/integration/mock_responses/INT-075/"
            "engineer_planner/entry_01/04__benchmark_definition.yaml"
        ).read_text(encoding="utf-8")
        todo_content = Path(
            "tests/integration/mock_responses/INT-075/"
            "engineer_planner/entry_01/02__todo.md"
        ).read_text(encoding="utf-8")
        assembly_definition_content = Path(
            "tests/integration/mock_responses/INT-075/"
            "engineer_coder/entry_01/01__assembly_definition.yaml"
        ).read_text(encoding="utf-8")
        await client.post(
            "http://127.0.0.1:18001/fs/write",
            json={
                "path": "benchmark_definition.yaml",
                "content": benchmark_definition_content,
                "overwrite": True,
            },
            headers={"X-Session-ID": strict_marker_session},
        )
        await client.post(
            "http://127.0.0.1:18001/fs/write",
            json={
                "path": "todo.md",
                "content": todo_content,
                "overwrite": True,
            },
            headers={"X-Session-ID": strict_marker_session},
        )
        await client.post(
            "http://127.0.0.1:18001/fs/write",
            json={
                "path": "assembly_definition.yaml",
                "content": assembly_definition_content,
                "overwrite": True,
            },
            headers={"X-Session-ID": strict_marker_session},
        )
        await client.post(
            "http://127.0.0.1:18001/fs/write",
            json={
                "path": "engineering_plan.md",
                "content": (
                    "## 1. Solution Overview\n\n"
                    "INT-075 strict-marker regression. This prose mentions "
                    "DOF_JUSTIFICATION:planner_link only as a token example and "
                    "does not include a standalone justification marker.\n\n"
                    "## 2. Parts List\n\n"
                    "- planner_link\n\n"
                    "## 3. Assembly Strategy\n\n"
                    "1. Baseline assembly.\n\n"
                    "## 4. Assumption Register\n"
                    "- Assumption: The planner relies on source-backed inputs that must be traceable.\n"
                    "\n"
                    "## 5. Detailed Calculations\n"
                    "| ID | Problem / Decision | Result | Impact |\n"
                    "| -- | -- | -- | -- |\n"
                    "| CALC-001 | Example calculation supporting the plan | \`N/A\` | Replace this placeholder with the actual derived limit. |\n"
                    "\n### CALC-001: Example calculation supporting the plan\n"
                    "\n#### Problem Statement\n"
                    "\nThe plan needs a traceable calculation instead of a freeform claim.\n"
                    "\n#### Assumptions\n"
                    "\n- \`ASSUMP-001\`: The input values are taken from the benchmark or assembly definition.\n"
                    "\n#### Derivation\n"
                    "\n- Compute the binding quantity from the declared inputs.\n"
                    "\n#### Worst-Case Check\n"
                    "\n- The derived limit must hold under the worst-case allowed inputs.\n"
                    "\n#### Result\n"
                    "\n- The design remains valid only if the derived limit is respected.\n"
                    "\n#### Design Impact\n"
                    "\n- Update the design or inputs if the calculation changes.\n"
                    "\n#### Cross-References\n"
                    "\n- \`engineering_plan.md#3-assembly-strategy\`\n"
                    "\n"
                    "## 6. Critical Constraints / Operating Envelope\n"
                    "- Constraint: The mechanism must remain inside the derived operating limits.\n"
                    "\n"
                    "## 7. Cost & Weight Budget\n"
                    "\n"
                    "- Within planner caps.\n\n"
                    "## 8. Risk Assessment\n\n"
                    "- Over-actuation drift risk.\n"
                ),
                "overwrite": True,
            },
            headers={"X-Session-ID": strict_marker_session},
        )
        benchmark_assembly_content = await _read_session_file(
            client, strict_marker_session, "benchmark_assembly_definition.yaml"
        )
        await _seed_engineer_plan_review_manifest(
            client,
            strict_marker_session,
            artifact_hashes={
                "engineering_plan.md": hashlib.sha256(
                    b"## 1. Solution Overview\n\n"
                    b"INT-075 strict-marker regression. This prose mentions "
                    b"DOF_JUSTIFICATION:planner_link only as a token example "
                    b"and does not include a standalone justification marker.\n\n"
                    b"## 2. Parts List\n\n"
                    b"- planner_link\n\n"
                    b"## 3. Assembly Strategy\n\n"
                    b"1. Baseline assembly.\n\n"
                    b"## 4. Assumption Register\n"
                    b"- Assumption: The planner relies on source-backed inputs that must be traceable.\n"
                    b"\n"
                    b"## 5. Detailed Calculations\n"
                    b"| ID | Problem / Decision | Result | Impact |\n"
                    b"| -- | -- | -- | -- |\n"
                    b"| CALC-001 | Example calculation supporting the plan | `N/A` | Replace this placeholder with the actual derived limit. |\n"
                    b"\n### CALC-001: Example calculation supporting the plan\n"
                    b"\n#### Problem Statement\n"
                    b"\nThe plan needs a traceable calculation instead of a freeform claim.\n"
                    b"\n#### Assumptions\n"
                    b"\n- `ASSUMP-001`: The input values are taken from the benchmark or assembly definition.\n"
                    b"\n#### Derivation\n"
                    b"\n- Compute the binding quantity from the declared inputs.\n"
                    b"\n#### Worst-Case Check\n"
                    b"\n- The derived limit must hold under the worst-case allowed inputs.\n"
                    b"\n#### Result\n"
                    b"\n- The design remains valid only if the derived limit is respected.\n"
                    b"\n#### Design Impact\n"
                    b"\n- Update the design or inputs if the calculation changes.\n"
                    b"\n#### Cross-References\n"
                    b"\n- `engineering_plan.md#3-assembly-strategy`\n"
                    b"\n"
                    b"## 6. Critical Constraints / Operating Envelope\n"
                    b"- Constraint: The mechanism must remain inside the derived operating limits.\n"
                    b"\n"
                    b"## 7. Cost & Weight Budget\n"
                    b"\n"
                    b"- Within planner caps.\n\n"
                    b"## 8. Risk Assessment\n\n"
                    b"- Over-actuation drift risk.\n"
                ).hexdigest(),
                "todo.md": hashlib.sha256(todo_content.encode("utf-8")).hexdigest(),
                "benchmark_definition.yaml": hashlib.sha256(
                    benchmark_definition_content.encode("utf-8")
                ).hexdigest(),
                "assembly_definition.yaml": hashlib.sha256(
                    assembly_definition_content.encode("utf-8")
                ).hexdigest(),
                "benchmark_assembly_definition.yaml": hashlib.sha256(
                    benchmark_assembly_content.encode("utf-8")
                ).hexdigest(),
            },
        )
        strict_marker_episode = await _run_and_wait(
            client,
            agent_name=AgentName.ENGINEER_PLAN_REVIEWER,
            session_id=strict_marker_session,
            task="INT-075 strict marker regression",
            start_node=AgentName.ENGINEER_PLAN_REVIEWER,
            seed_benchmark_assembly=False,
        )
        assert _has_expected_review_evidence(
            strict_marker_episode,
            required_checklist_pairs=(("dof_minimality", "fail"),),
        ), strict_marker_episode
        strict_marker_review_traces = [
            trace
            for trace in strict_marker_episode.traces
            if trace.name == "review_decision" and trace.metadata_vars is not None
        ]
        assert strict_marker_review_traces, "Expected strict-marker review_decision"
        strict_marker_decision = max(
            strict_marker_review_traces, key=lambda trace: trace.id
        )
        assert (
            strict_marker_decision.metadata_vars.checklist.get("dof_minimality")
            == "fail"
        ), strict_marker_decision.metadata_vars.checklist

        # Regression: malformed assembly YAML must fail closed instead of
        # falling through to the LLM path.
        malformed_session = f"INT-075-{uuid.uuid4().hex[:8]}"
        await seed_benchmark_assembly_definition(
            client,
            malformed_session,
            benchmark_max_unit_cost_usd=250.0,
            benchmark_max_weight_g=2500.0,
            planner_target_max_unit_cost_usd=250.0,
            planner_target_max_weight_g=2500.0,
        )
        await seed_current_revision_render_preview(client, session_id=malformed_session)
        benchmark_definition_content = Path(
            "tests/integration/mock_responses/INT-075/"
            "engineer_planner/entry_01/04__benchmark_definition.yaml"
        ).read_text(encoding="utf-8")
        todo_content = Path(
            "tests/integration/mock_responses/INT-075/"
            "engineer_planner/entry_01/02__todo.md"
        ).read_text(encoding="utf-8")
        plan_content = Path(
            "tests/integration/mock_responses/INT-075/"
            "engineer_planner/entry_01/01__plan.md"
        ).read_text(encoding="utf-8")
        await client.post(
            "http://127.0.0.1:18001/fs/write",
            json={
                "path": "benchmark_definition.yaml",
                "content": benchmark_definition_content,
                "overwrite": True,
            },
            headers={"X-Session-ID": malformed_session},
        )
        await client.post(
            "http://127.0.0.1:18001/fs/write",
            json={
                "path": "todo.md",
                "content": todo_content,
                "overwrite": True,
            },
            headers={"X-Session-ID": malformed_session},
        )
        await client.post(
            "http://127.0.0.1:18001/fs/write",
            json={
                "path": "engineering_plan.md",
                "content": plan_content,
                "overwrite": True,
            },
            headers={"X-Session-ID": malformed_session},
        )
        await client.post(
            "http://127.0.0.1:18001/fs/write",
            json={
                "path": "assembly_definition.yaml",
                "content": "version: '1.0'\nconstraints: [\n",
                "overwrite": True,
            },
            headers={"X-Session-ID": malformed_session},
        )
        benchmark_assembly_content = await _read_session_file(
            client, malformed_session, "benchmark_assembly_definition.yaml"
        )
        await _seed_engineer_plan_review_manifest(
            client,
            malformed_session,
            artifact_hashes={
                "engineering_plan.md": hashlib.sha256(
                    plan_content.encode("utf-8")
                ).hexdigest(),
                "todo.md": hashlib.sha256(todo_content.encode("utf-8")).hexdigest(),
                "benchmark_definition.yaml": hashlib.sha256(
                    benchmark_definition_content.encode("utf-8")
                ).hexdigest(),
                "assembly_definition.yaml": hashlib.sha256(
                    b"version: '1.0'\nconstraints: [\n"
                ).hexdigest(),
                "benchmark_assembly_definition.yaml": hashlib.sha256(
                    benchmark_assembly_content.encode("utf-8")
                ).hexdigest(),
            },
        )
        malformed_episode = await _run_and_wait(
            client,
            agent_name=AgentName.ENGINEER_PLAN_REVIEWER,
            session_id=malformed_session,
            task="INT-075 malformed assembly regression",
            start_node=AgentName.ENGINEER_PLAN_REVIEWER,
            seed_benchmark_assembly=False,
        )
        assert malformed_episode.status == EpisodeStatus.FAILED, malformed_episode
        assert any(
            trace.name == "node_entry_validation_failed"
            and "planner handoff cross-validation parse failure"
            in (trace.content or "")
            for trace in (malformed_episode.traces or [])
        ), malformed_episode.traces
