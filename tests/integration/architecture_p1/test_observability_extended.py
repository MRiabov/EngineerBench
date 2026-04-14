import os
import uuid

import httpx
import pytest

from controller.api.schemas import AgentRunRequest, AgentRunResponse, EpisodeResponse
from shared.enums import TraceType
from tests.integration.agent.helpers import (
    seed_benchmark_assembly_definition,
    wait_for_episode_terminal,
)

CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")

pytestmark = pytest.mark.xdist_group(name="physics_sims")


@pytest.mark.integration_p1
@pytest.mark.asyncio
@pytest.mark.int_id("INT-058")
async def test_int_058_cross_system_correlation():
    """INT-058: Verify cross-system correlation IDs."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        task = "Test cross-system correlation"
        session_id = f"INT-058-{uuid.uuid4().hex[:8]}"
        await seed_benchmark_assembly_definition(client, session_id)
        request = AgentRunRequest(task=task, session_id=session_id)
        resp = await client.post(
            f"{CONTROLLER_URL}/agent/run",
            json=request.model_dump(),
        )
        assert resp.status_code == 202
        episode_id = AgentRunResponse.model_validate(resp.json()).episode_id

        # 1. Verify Episode in DB
        status_resp = await client.get(f"{CONTROLLER_URL}/episodes/{episode_id}")
        assert status_resp.status_code == 200
        ep = EpisodeResponse.model_validate(status_resp.json())
        assert str(ep.id) == str(episode_id)

        ep = EpisodeResponse.model_validate(
            await wait_for_episode_terminal(
                client,
                str(episode_id),
                timeout_s=30.0,
                poll_s=1.0,
            )
        )

        # 3. Verify Correlation across traces
        traces = ep.traces or []
        assert len(traces) > 0
        langfuse_trace_id = traces[0].langfuse_trace_id
        assert langfuse_trace_id is not None

        # Check all traces for same LF ID
        for t in traces:
            if t.langfuse_trace_id:
                assert t.langfuse_trace_id == langfuse_trace_id

        # 4. Verify correlation in events (if we can hit event endpoint)
        event_traces = [t for t in traces if t.trace_type == TraceType.EVENT]
        # Events stored as traces should have metadata with episode_id
        for et in event_traces:
            if et.metadata:
                episode_id_from_metadata = et.metadata.additional_info.get("episode_id")
                if episode_id_from_metadata is not None:
                    assert str(episode_id_from_metadata) == str(episode_id)
