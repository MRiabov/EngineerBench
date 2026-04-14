import asyncio
import os
import uuid

import httpx
import pytest
from temporalio.client import Client, WorkflowFailureError

from controller.api.schemas import (
    AgentRunRequest,
    EpisodeCreateResponse,
    EpisodeResponse,
    IntegrationTestStatusResponse,
)
from shared.enums import AssetType, EpisodeStatus

CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")
TEMPORAL_URL = os.getenv("TEMPORAL_URL", "127.0.0.1:17233")


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_controller_reports_integration_test_mode():
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.get(f"{CONTROLLER_URL}/api/test/is_integration_test")
        assert resp.status_code == 200, resp.text
        payload = IntegrationTestStatusResponse.model_validate(resp.json())
        assert payload.is_integration_test is True


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-053")
async def test_int_053_temporal_workflow_lifecycle():
    """INT-053: Verify Temporal workflow lifecycle persistence."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # 1. Create a dummy episode to link to without starting a background agent run.
        req = AgentRunRequest(
            task="Test Temporal Workflow Lifecycle",
            session_id=f"INT-053-obs-{uuid.uuid4().hex[:8]}",
        )
        resp = await client.post(
            f"{CONTROLLER_URL}/api/test/episodes",
            json=req.model_dump(mode="json"),
        )
        assert resp.status_code == 201, resp.text
        episode_id = EpisodeCreateResponse.model_validate(resp.json()).episode_id

        # 2. Connect to Temporal and start SimulationWorkflow
        temporal = await Client.connect(TEMPORAL_URL)

        # We use a dummy compound_json that will be "compiled" by mock activity
        params = {"compound_json": "{}", "episode_id": str(episode_id)}

        handle = await temporal.start_workflow(
            "SimulationWorkflow",
            params,
            id=f"test-sim-{episode_id}",
            task_queue="simulation-task-queue",
        )

        # 3. Wait for workflow completion
        await handle.result()

        # 4. Verify episode status in DB via API
        status_resp = await client.get(f"{CONTROLLER_URL}/api/episodes/{episode_id}")
        assert status_resp.status_code == 200
        ep_data = EpisodeResponse.model_validate(status_resp.json())
        assert ep_data.status == EpisodeStatus.COMPLETED
        assert ep_data.updated_at is not None


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-055")
async def test_int_055_s3_artifact_upload_logging():
    """INT-055: Verify S3 artifact upload logging and linkage."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # 1. Create an isolated episode without starting a background agent run.
        req = AgentRunRequest(
            task="Test S3 Upload", session_id=f"INT-055-s3-{uuid.uuid4().hex[:8]}"
        )
        resp = await client.post(
            f"{CONTROLLER_URL}/api/test/episodes",
            json=req.model_dump(mode="json"),
        )
        assert resp.status_code == 201, resp.text
        episode_id = EpisodeCreateResponse.model_validate(resp.json()).episode_id

        # 2. Trigger workflow
        temporal = await Client.connect(TEMPORAL_URL)
        await temporal.execute_workflow(
            "SimulationWorkflow",
            {"compound_json": "{}", "episode_id": str(episode_id)},
            id=f"test-s3-{episode_id}",
            task_queue="simulation-task-queue",
        )

        # 3. Verify Asset record via API
        episode_resp = await client.get(f"{CONTROLLER_URL}/api/episodes/{episode_id}")
        ep_data = EpisodeResponse.model_validate(episode_resp.json())

        assert len(ep_data.assets) > 0
        asset = ep_data.assets[0]
        assert asset.asset_type == AssetType.VIDEO
        assert asset.s3_path.startswith("videos/")
        assert asset.created_at is not None


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-054")
async def test_int_054_temporal_failure_path():
    """INT-054: Verify Temporal outage/failure logging path (via failure injection)."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # 1. Create episode via API
        req = AgentRunRequest(task="Test Failure Injection", session_id="INT-054-fail")
        resp = await client.post(
            f"{CONTROLLER_URL}/api/test/episodes",
            json=req.model_dump(mode="json"),
        )
        assert resp.status_code == 201
        data = EpisodeCreateResponse.model_validate(resp.json())
        episode_id = data.episode_id

        # 2. Trigger workflow with MJCF failure injection
        temporal = await Client.connect(TEMPORAL_URL)

        params = {
            "compound_json": "{}",
            "episode_id": str(episode_id),
            "simulate_failures": {"mjcf_compilation": True},
        }

        handle = await temporal.start_workflow(
            "SimulationWorkflow",
            params,
            id=f"test-fail-{episode_id}",
            task_queue="simulation-task-queue",
        )

        # 3. Wait for workflow failure (it should fail after 3 attempts)
        with pytest.raises((RuntimeError, WorkflowFailureError)):
            await handle.result()

        # 4. Verify episode status is FAILED in DB
        status_resp = await client.get(f"{CONTROLLER_URL}/api/episodes/{episode_id}")
        assert status_resp.status_code == 200
        ep_data = EpisodeResponse.model_validate(status_resp.json())
        assert ep_data.status == EpisodeStatus.FAILED


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-056")
async def test_int_056_s3_upload_failure_retry():
    """INT-056: Verify S3 upload failure + retry logging."""
    # Similar issue with retries.
    # But here we WANT to verify retry logic.
    # Temporal retries by default.
    # We can verify that the episode does NOT go to completed status quickly.

    async with httpx.AsyncClient(timeout=300.0) as client:
        # Create episode via test endpoint (no agent task interference)
        req = AgentRunRequest(task="Test S3 Retry", session_id="INT-056-retry")
        resp = await client.post(
            f"{CONTROLLER_URL}/api/test/episodes",
            json=req.model_dump(mode="json"),
        )
        assert resp.status_code == 201
        data = EpisodeCreateResponse.model_validate(resp.json())
        episode_id = data.episode_id

        temporal = await Client.connect(TEMPORAL_URL)
        handle = await temporal.start_workflow(
            "SimulationWorkflow",
            {
                "compound_json": "{}",
                "episode_id": episode_id,
                "simulate_failures": {"s3_upload": True},
            },
            id=f"test-retry-{episode_id}",
            task_queue="simulation-task-queue",
        )

        # Wait a bit. It should be retrying.
        # With maximum_attempts=3 and 1s initial backoff, it fails around 3-4s.
        # So we check at 1s.
        await asyncio.sleep(1)

        status_resp = await client.get(f"{CONTROLLER_URL}/api/episodes/{episode_id}")
        ep_data = EpisodeResponse.model_validate(status_resp.json())
        assert (
            ep_data.status == EpisodeStatus.RUNNING
        )  # Should still be running (retrying)

        # Cleanup: Cancel it so we don't spam logs
        await handle.cancel()
