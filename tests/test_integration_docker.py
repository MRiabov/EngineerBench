import asyncio
import os
import time

import httpx
import pytest

from controller.api.schemas import AgentRunResponse, EpisodeResponse
from controller.api.tasks import AgentRunRequest
from shared.enums import EpisodeStatus, ResponseStatus
from shared.workers.schema import ReadFileRequest, ReadFileResponse
from tests.integration.contracts import HealthResponse

CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://localhost:18000")
WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://localhost:18001")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_services_health():
    """Verify both controller and worker are healthy."""
    async with httpx.AsyncClient() as client:
        # Check Controller
        try:
            resp = await client.get(f"{CONTROLLER_URL}/api/health", timeout=10.0)
            assert resp.status_code == 200
            health = HealthResponse.model_validate(resp.json())
            assert health.status in [ResponseStatus.HEALTHY, ResponseStatus.OK]
        except Exception as e:
            pytest.fail(f"Controller at {CONTROLLER_URL} is not reachable: {e}")

        # Check Worker
        try:
            resp = await client.get(f"{WORKER_LIGHT_URL}/health", timeout=10.0)
            assert resp.status_code == 200
            health = HealthResponse.model_validate(resp.json())
            assert health.status in [ResponseStatus.HEALTHY, ResponseStatus.OK]
        except Exception as e:
            pytest.fail(f"Worker at {WORKER_LIGHT_URL} is not reachable: {e}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_controller_to_worker_agent_run():
    """Verify controller can trigger an agent run which talks to the worker."""
    async with httpx.AsyncClient() as client:
        session_id = f"test-agent-{int(time.time())}"
        run_req = AgentRunRequest(
            task=(
                "Write a file named 'hello_integration.txt' "
                "with content 'integration test'"
            ),
            session_id=session_id,
        )

        # Trigger agent run
        resp = await client.post(
            f"{CONTROLLER_URL}/api/agent/run",
            json=run_req.model_dump(mode="json"),
            timeout=10.0,
        )
        assert resp.status_code == 202
        agent_run_resp = AgentRunResponse.model_validate(resp.json())
        assert agent_run_resp.status == ResponseStatus.ACCEPTED
        episode_id = agent_run_resp.episode_id

        # Wait for completion
        max_retries = 30
        completed = False
        for _ in range(max_retries):
            status_resp = await client.get(
                f"{CONTROLLER_URL}/api/episodes/{episode_id}"
            )
            if status_resp.status_code == 200:
                ep_data = EpisodeResponse.model_validate(status_resp.json())
                if ep_data.status == EpisodeStatus.COMPLETED:
                    completed = True
                    break
                if ep_data.status == EpisodeStatus.FAILED:
                    pytest.fail("Agent run failed in background")
            await asyncio.sleep(2)

        if not completed:
            pytest.fail("Agent run timed out")

        # Verify the file was actually written
        read_req = ReadFileRequest(path="hello_integration.txt")
        fs_resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/read",
            json=read_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        assert fs_resp.status_code == 200
        read_data = ReadFileResponse.model_validate(fs_resp.json())
        assert read_data.content == "integration test"
