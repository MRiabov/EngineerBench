import asyncio
import uuid

import pytest
from httpx import AsyncClient

from controller.api.routes.benchmark import BenchmarkGenerateRequest
from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    BenchmarkGenerateResponse,
    ConfirmRequest,
    EpisodeResponse,
)
from shared.enums import EpisodeStatus

# Adjust URL to your controller
CONTROLLER_URL = "http://localhost:18000"


async def _wait_for_benchmark_completion(
    client: AsyncClient,
    *,
    session_id: str,
    max_attempts: int = 60,
) -> EpisodeResponse:
    latest: EpisodeResponse | None = None
    confirmed = False

    for _ in range(max_attempts):
        status_resp = await client.get(f"/benchmark/{session_id}")
        if status_resp.status_code == 404:
            await asyncio.sleep(1)
            continue

        assert status_resp.status_code == 200, status_resp.text
        latest = EpisodeResponse.model_validate(status_resp.json())

        if latest.status == EpisodeStatus.PLANNED and not confirmed:
            confirm_resp = await client.post(
                f"/benchmark/{session_id}/confirm",
                json=ConfirmRequest(comment="Proceed").model_dump(),
            )
            assert confirm_resp.status_code in {200, 202}, confirm_resp.text
            confirmed = True
        elif latest.status == EpisodeStatus.COMPLETED:
            return latest
        elif latest.status == EpisodeStatus.FAILED:
            pytest.fail(f"Benchmark generation failed. Episode data: {latest}")

        await asyncio.sleep(1)

    assert latest is not None
    return latest


async def _wait_for_engineer_completion(
    client: AsyncClient,
    *,
    episode_id: str,
    expected_user_session_id: uuid.UUID,
    max_attempts: int = 60,
) -> EpisodeResponse:
    latest: EpisodeResponse | None = None

    for _ in range(max_attempts):
        ep_resp = await client.get(f"/api/episodes/{episode_id}")
        assert ep_resp.status_code == 200, ep_resp.text
        latest = EpisodeResponse.model_validate(ep_resp.json())
        assert latest.user_session_id == expected_user_session_id, (
            "user_session_id mismatch"
        )

        if latest.status == EpisodeStatus.COMPLETED:
            return latest
        if latest.status == EpisodeStatus.FAILED:
            pytest.fail(f"Engineer agent failed. Episode data: {latest}")

        await asyncio.sleep(1)

    assert latest is not None
    return latest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_workflow_end_to_end():
    """
    Test the full workflow:
    1. Trigger Benchmark Generator (via API)
    2. Wait for Benchmark to complete and produce assets
    3. Trigger Engineer Agent (via API) with the generated benchmark
    4. Wait for Engineer to complete

    We mock the LLM responses to ensure deterministic execution and avoid costs.
    """

    async with AsyncClient(base_url=CONTROLLER_URL, timeout=60.0) as client:
        # 1. Trigger Benchmark Generation
        prompt = "Create a simple box stacking benchmark."
        req = BenchmarkGenerateRequest(prompt=prompt)
        resp = await client.post("/benchmark/generate", json=req.model_dump())
        assert resp.status_code == 200, f"Failed to trigger benchmark: {resp.text}"
        benchmark_resp = BenchmarkGenerateResponse.model_validate(resp.json())
        session_id = benchmark_resp.session_id

        benchmark_episode = await _wait_for_benchmark_completion(
            client, session_id=str(session_id)
        )
        assert benchmark_episode.status == EpisodeStatus.COMPLETED, (
            f"Benchmark generation timed out. Last status: {benchmark_episode.status}"
        )

        engineer_task = (
            f"Solve this benchmark: {session_id}. Constraints: Use standard parts."
        )

        # 4. Trigger Engineer Agent
        # Generate a unique session ID for the engineer run
        engineer_session_id = f"INT-033-full-{uuid.uuid4().hex[:8]}"
        user_session_id = uuid.uuid4()

        req_run = AgentRunRequest(
            task=engineer_task,
            session_id=engineer_session_id,
            user_session_id=user_session_id,
        )

        run_resp = await client.post(
            "/api/agent/run", json=req_run.model_dump(mode="json")
        )
        assert run_resp.status_code == 202, (
            f"Failed to trigger engineer: {run_resp.text}"
        )
        agent_run_resp = AgentRunResponse.model_validate(run_resp.json())
        episode_id = agent_run_resp.episode_id

        engineer_episode = await _wait_for_engineer_completion(
            client,
            episode_id=str(episode_id),
            expected_user_session_id=user_session_id,
        )
        assert engineer_episode.status == EpisodeStatus.COMPLETED, (
            f"Engineer agent timed out. Last status: {engineer_episode.status}"
        )
