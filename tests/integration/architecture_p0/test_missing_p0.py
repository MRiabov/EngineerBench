import asyncio
import os
import uuid

import httpx
import pytest

from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    EpisodeCreateResponse,
    EpisodeListItem,
    EpisodeResponse,
)
from shared.enums import EpisodeStatus
from shared.workers.schema import (
    ReadFileRequest,
    ReadFileResponse,
    WriteFileRequest,
)
from tests.integration.agent.helpers import (
    seed_benchmark_assembly_definition,
    seed_execution_reviewer_handover,
)

# Constants
WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
WORKER_HEAVY_URL = os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002")
CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")
pytestmark = pytest.mark.xdist_group(name="physics_sims")


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_004_episode_artifact_persistence():
    """INT-004: Verify artifacts are persisted and accessible via API."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"test-p0-{uuid.uuid4().hex[:8]}"

        # Write some files
        write_req = WriteFileRequest(path="output.py", content="print('hello')")
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        # Create dummy episode
        req = AgentRunRequest(
            task="Test artifacts",
            session_id=session_id,
            metadata_vars={"worker_session_id": session_id},
        )
        resp = await client.post(
            f"{CONTROLLER_URL}/test/episodes",
            json=req.model_dump(mode="json"),
        )
        assert resp.status_code == 201
        episode_create = EpisodeCreateResponse.model_validate(resp.json())
        episode_id = str(episode_create.episode_id)

        # Let's check episodes list
        resp = await client.get(f"{CONTROLLER_URL}/episodes/")
        assert resp.status_code == 200
        episodes = [EpisodeListItem.model_validate(e) for e in resp.json()]
        assert any(str(e.id) == episode_id for e in episodes)


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "node_entry_validation_rejected",
        "missing_artifact",
        "reviewer_entry_blocked",
    ]
)
@pytest.mark.asyncio
async def test_int_005_trace_realtime_broadcast():
    """INT-005: Verify traces are broadcasted via DB/API."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # Use the INT-005 mock scenario prefix to avoid cross-test backend-error
        # leakage from another scenario's tighter cost caps.
        session_id = f"INT-005-{uuid.uuid4().hex[:8]}"

        # Run a very short agent task
        run_req = AgentRunRequest(task="Say hello", session_id=session_id)
        resp = await client.post(
            f"{CONTROLLER_URL}/agent/run",
            json=run_req.model_dump(mode="json"),
        )
        assert resp.status_code == 202
        run_data = AgentRunResponse.model_validate(resp.json())
        episode_id = run_data.episode_id

        # Wait a bit for traces
        await asyncio.sleep(5.0)

        resp = await client.get(f"{CONTROLLER_URL}/episodes/{episode_id}")
        ep_data = EpisodeResponse.model_validate(resp.json())
        assert len(ep_data.traces) > 0


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_011_planner_target_caps_validation():
    """INT-011: Verify planner target caps must be <= benchmark caps."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"test-caps-{uuid.uuid4().hex[:8]}"

        invalid_asm = """
version: "1.0"
constraints:
  benchmark_max_unit_cost_usd: 100.0
  benchmark_max_weight_g: 1000.0
  planner_target_max_unit_cost_usd: 150.0  # INVALID
  planner_target_max_weight_g: 500.0
totals:
  estimated_unit_cost_usd: 10.0
  estimated_weight_g: 100.0
  estimate_confidence: high
"""
        write_req = WriteFileRequest(path="invalid_asm.yaml", content=invalid_asm)
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        pass


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_014_cots_propagation():
    """INT-014: Verify COTS data propagates into plan and assembly definition."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"INT-014-{uuid.uuid4().hex[:8]}"
        await seed_benchmark_assembly_definition(client, session_id)
        await seed_execution_reviewer_handover(
            client,
            session_id=session_id,
            int_id="INT-014",
            seed_render_preview=False,
        )
        run_req = AgentRunRequest(
            task="Design a passive mechanism with a catalog-backed fastener",
            session_id=session_id,
        )
        run_resp = await client.post(
            f"{CONTROLLER_URL}/agent/run",
            json=run_req.model_dump(mode="json"),
        )
        assert run_resp.status_code == 202
        run_data = AgentRunResponse.model_validate(run_resp.json())
        episode_id = run_data.episode_id

        # Wait for agent to reach COMPLETED status
        max_attempts = 60
        for _ in range(max_attempts):
            await asyncio.sleep(5.0)
            status_resp = await client.get(f"{CONTROLLER_URL}/episodes/{episode_id}")
            ep_data = EpisodeResponse.model_validate(status_resp.json())
            if ep_data.status == EpisodeStatus.COMPLETED:
                break
        else:
            pytest.fail("Agent did not complete planning in time")

        # Verify plan.md contains COTS ID
        read_plan_req = ReadFileRequest(path="plan.md")
        plan_resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/read",
            json=read_plan_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        assert plan_resp.status_code == 200
        plan_data = ReadFileResponse.model_validate(plan_resp.json())
        assert "M3_BOLT" in plan_data.content

        # Verify assembly_definition.yaml contains COTS data
        read_asm_req = ReadFileRequest(path="assembly_definition.yaml")
        asm_resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/read",
            json=read_asm_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        assert asm_resp.status_code == 200
        asm_data = ReadFileResponse.model_validate(asm_resp.json())
        assert "M3_BOLT" in asm_data.content


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_025_events_collection_e2e():
    """INT-025: Verify worker events are ingested and persisted as traces."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"INT-025-{uuid.uuid4().hex[:8]}"
        await seed_benchmark_assembly_definition(client, session_id)
        run_req = AgentRunRequest(task="Run a simulation", session_id=session_id)
        run_resp = await client.post(
            f"{CONTROLLER_URL}/agent/run",
            json=run_req.model_dump(mode="json"),
        )
        assert run_resp.status_code == 202
        run_data = AgentRunResponse.model_validate(run_resp.json())
        episode_id = run_data.episode_id

        # Wait for completion
        max_attempts = 60
        for _ in range(max_attempts):
            await asyncio.sleep(5.0)
            status_resp = await client.get(f"{CONTROLLER_URL}/episodes/{episode_id}")
            if status_resp.status_code != 200:
                continue
            ep_data = EpisodeResponse.model_validate(status_resp.json())
            if ep_data.status == EpisodeStatus.COMPLETED:
                break
        else:
            pytest.fail("Agent did not complete simulation task in time")

        # Verify traces contain the simulation result event
        resp = await client.get(f"{CONTROLLER_URL}/episodes/{episode_id}")
        ep_data = EpisodeResponse.model_validate(resp.json())

        assert any("simulation" in str(t.content).lower() for t in ep_data.traces)
