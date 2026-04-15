import os
import uuid

import httpx
import pytest

from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    EpisodeResponse,
    IntegrationTestStatusResponse,
)
from shared.enums import AssetType, EpisodeStatus, TraceType
from tests.integration.agent.helpers import (
    seed_benchmark_assembly_definition,
    seed_engineer_planner_handover,
    wait_for_episode_terminal,
)

CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")


async def _start_observability_episode(
    client: httpx.AsyncClient,
    *,
    session_id: str,
    task: str,
) -> uuid.UUID:
    await seed_benchmark_assembly_definition(client, session_id)
    request = AgentRunRequest(task=task, session_id=session_id)
    resp = await client.post(
        f"{CONTROLLER_URL}/api/agent/run",
        json=request.model_dump(mode="json"),
    )
    assert resp.status_code == 202, resp.text
    return AgentRunResponse.model_validate(resp.json()).episode_id


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
async def test_int_053_episode_lifecycle_persists():
    """INT-053: Verify episode lifecycle persistence over the live controller path."""
    session_id = f"INT-053-obs-{uuid.uuid4().hex[:8]}"
    async with httpx.AsyncClient(timeout=300.0) as client:
        await seed_engineer_planner_handover(
            client,
            session_id=session_id,
            int_id="INT-053",
            include_reviewer_artifacts=False,
        )
        episode_id = await _start_observability_episode(
            client,
            session_id=session_id,
            task="Test episode lifecycle persistence",
        )

        episode_data = EpisodeResponse.model_validate(
            await wait_for_episode_terminal(
                client,
                str(episode_id),
                timeout_s=300.0,
                poll_s=1.0,
            )
        )

        assert episode_data.status == EpisodeStatus.COMPLETED
        assert episode_data.updated_at is not None
        assert episode_data.last_trace_id is not None
        assert episode_data.traces

        trace_ids = {
            trace.langfuse_trace_id
            for trace in episode_data.traces
            if trace.langfuse_trace_id
        }
        assert trace_ids
        assert len(trace_ids) == 1

        event_traces = [
            trace
            for trace in episode_data.traces
            if trace.trace_type == TraceType.EVENT
        ]
        assert event_traces
        for trace in event_traces:
            if trace.metadata is None:
                continue
            episode_id_from_metadata = trace.metadata.additional_info.get("episode_id")
            if episode_id_from_metadata is not None:
                assert str(episode_id_from_metadata) == str(episode_id)


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-055")
async def test_int_055_s3_artifact_upload_logging():
    """INT-055: Verify S3 artifact upload logging and linkage."""
    session_id = f"INT-055-s3-{uuid.uuid4().hex[:8]}"
    async with httpx.AsyncClient(timeout=300.0) as client:
        episode_id = await _start_observability_episode(
            client,
            session_id=session_id,
            task="Test S3 Upload",
        )

        episode_data = EpisodeResponse.model_validate(
            await wait_for_episode_terminal(
                client,
                str(episode_id),
                timeout_s=300.0,
                poll_s=1.0,
            )
        )

        assert episode_data.status == EpisodeStatus.COMPLETED
        assert episode_data.assets
        video_assets = [
            asset
            for asset in episode_data.assets
            if asset.asset_type == AssetType.VIDEO
        ]
        assert video_assets

        asset = video_assets[0]
        assert asset.s3_path.startswith("videos/")
        assert asset.created_at is not None
