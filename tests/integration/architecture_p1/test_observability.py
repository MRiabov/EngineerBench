import asyncio
import os
import uuid

import httpx
import pytest

from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    EpisodeResponse,
    FeedbackRequest,
)
from shared.enums import EpisodeStatus
from tests.integration.agent.helpers import (
    seed_benchmark_assembly_definition,
    seed_engineer_planner_handover,
)

CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")


@pytest.mark.integration_p1
@pytest.mark.asyncio
@pytest.mark.int_id("INT-059")
async def test_int_059_langfuse_trace_linkage():
    """INT-059: Verify Langfuse trace linkage in live runs."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # 1. Run an episode
        # We use a simple task that might trigger some traces
        task = "Write a hello world python script"
        session_id = f"INT-059-{uuid.uuid4().hex[:8]}"
        await seed_engineer_planner_handover(
            client,
            session_id=session_id,
            int_id="INT-059",
        )
        await seed_benchmark_assembly_definition(client, session_id)
        request = AgentRunRequest(
            task=task,
            session_id=session_id,
        )
        resp = await client.post(
            f"{CONTROLLER_URL}/agent/run",
            json=request.model_dump(),
        )
        assert resp.status_code == 202
        run_data = AgentRunResponse.model_validate(resp.json())
        episode_id = run_data.episode_id

        # 2. Wait for it to complete (or at least have some traces)
        # We'll poll for a bit
        max_retries = 150
        for _ in range(max_retries):
            status_resp = await client.get(f"{CONTROLLER_URL}/episodes/{episode_id}")
            assert status_resp.status_code == 200
            ep_data = EpisodeResponse.model_validate(status_resp.json())
            if ep_data.status in [EpisodeStatus.COMPLETED, EpisodeStatus.FAILED]:
                break
            await asyncio.sleep(2)

        # Even if it didn't complete, it should have traces
        status_resp = await client.get(f"{CONTROLLER_URL}/episodes/{episode_id}")
        ep_data = EpisodeResponse.model_validate(status_resp.json())
        traces = ep_data.traces or []
        assert len(traces) > 0

        # 3. Verify langfuse_trace_id consistency
        # The first trace (LOG) should always have a langfuse_trace_id generated
        # Subsequent traces will have it IF langfuse is configured.

        # In this integration environment, we check if at least one trace has it
        # and if multiple traces have it, they must be the same.
        langfuse_ids = [t.langfuse_trace_id for t in traces if t.langfuse_trace_id]

        assert len(langfuse_ids) > 0, (
            "At least the initial trace must have a langfuse_trace_id"
        )

        # All traces that have a langfuse_trace_id should have the SAME one
        first_id = langfuse_ids[0]
        for lf_id in langfuse_ids:
            assert lf_id == first_id, (
                f"Inconsistent langfuse_trace_id: {lf_id} != {first_id}"
            )

        # Check that it's a valid 32-char hex (as per implementation in tasks.py)
        assert len(first_id) == 32
        int(first_id, 16)  # Should not raise ValueError


@pytest.mark.integration_p1
@pytest.mark.asyncio
@pytest.mark.int_id("INT-060")
async def test_int_060_langfuse_feedback_contract():
    """INT-060: Verify Langfuse feedback forwarding contract."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # 1. Create an episode and get a trace with langfuse_id
        task = "Test feedback"
        session_id = f"INT-060-{uuid.uuid4().hex[:8]}"
        await seed_engineer_planner_handover(
            client,
            session_id=session_id,
            int_id="INT-060",
        )
        await seed_benchmark_assembly_definition(client, session_id)
        request = AgentRunRequest(
            task=task,
            session_id=session_id,
        )
        resp = await client.post(
            f"{CONTROLLER_URL}/agent/run",
            json=request.model_dump(),
        )
        run_data = AgentRunResponse.model_validate(resp.json())
        episode_id = run_data.episode_id

        # Wait for at least one trace
        await asyncio.sleep(2)
        status_resp = await client.get(f"{CONTROLLER_URL}/episodes/{episode_id}")
        ep_data = EpisodeResponse.model_validate(status_resp.json())
        traces = ep_data.traces or []
        assert len(traces) > 0

        trace = traces[0]
        trace_id = trace.id

        # 2. Test feedback with langfuse_trace_id
        feedback_request = FeedbackRequest(score=1, comment="Great trace!")
        feedback_resp = await client.post(
            f"{CONTROLLER_URL}/episodes/{episode_id}/traces/{trace_id}/feedback",
            json=feedback_request.model_dump(),
        )

        # If Langfuse is not configured in the test environment, it should return 503
        # If it IS configured, it should return 202 (Accepted)
        assert feedback_resp.status_code in [202, 503]

        if feedback_resp.status_code == 202:
            # Verify local persistence
            status_resp = await client.get(f"{CONTROLLER_URL}/episodes/{episode_id}")
            updated_episode = EpisodeResponse.model_validate(status_resp.json())
            updated_trace = next(
                t for t in (updated_episode.traces or []) if t.id == trace_id
            )
            assert updated_trace.feedback_score == 1
            assert updated_trace.feedback_comment == "Great trace!"

        # 3. Test with missing langfuse_trace_id (if we can find/create one)
        # We'd need DB setup to insert a trace without LF ID.
        # However, we can test with a non-existent trace_id or episode_id

        # Test 404 for non-existent trace
        bad_feedback_request = FeedbackRequest(score=0)
        bad_feedback_resp = await client.post(
            f"{CONTROLLER_URL}/episodes/{episode_id}/traces/999999/feedback",
            json=bad_feedback_request.model_dump(),
        )
        assert bad_feedback_resp.status_code == 404

        # Test 404 for non-existent episode
        bad_episode_id = str(uuid.uuid4())
        bad_feedback_resp = await client.post(
            f"{CONTROLLER_URL}/episodes/{bad_episode_id}/traces/{trace_id}/feedback",
            json=bad_feedback_request.model_dump(),
        )
        assert bad_feedback_resp.status_code == 404

        invalid_feedback_resp = await client.post(
            f"{CONTROLLER_URL}/episodes/{episode_id}/traces/{trace_id}/feedback",
            json={"score": 2},
        )
        assert invalid_feedback_resp.status_code == 422
