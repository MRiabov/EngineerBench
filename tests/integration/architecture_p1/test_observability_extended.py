import asyncio
import os
import uuid

import boto3
import httpx
import pytest
from temporalio.client import Client

from controller.api.schemas import AgentRunRequest, AgentRunResponse, EpisodeResponse
from shared.enums import EpisodeStatus, TraceType
from tests.integration.agent.helpers import seed_benchmark_assembly_definition
from tests.integration.contracts import BackupWorkflowResponse

CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")
TEMPORAL_URL = os.getenv("TEMPORAL_URL", "127.0.0.1:17233")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://127.0.0.1:19000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
ASSET_BUCKET = os.getenv("ASSET_S3_BUCKET", "problemologist")

pytestmark = pytest.mark.xdist_group(name="physics_sims")


@pytest.mark.integration_p1
@pytest.mark.asyncio
@pytest.mark.int_id("INT-057")
async def test_int_057_backup_logging_flow():
    """
    INT-057: Backup-to-S3 logging flow
    Verify that backup endpoint triggers workflow, creates S3 objects,
    and (ideally) persists metadata.
    """
    async with httpx.AsyncClient(timeout=300.0) as client:
        # 1. Trigger backup
        # The secret defaults to 'change-me-in-production' in dev compose
        headers = {"X-Backup-Secret": "change-me-in-production"}
        resp = await client.post(f"{CONTROLLER_URL}/ops/backup", headers=headers)

        if resp.status_code == 403:
            # Try without secret if it's disabled or different
            resp = await client.post(f"{CONTROLLER_URL}/ops/backup")

        assert resp.status_code == 202, f"Backup trigger failed: {resp.text}"
        backup_resp = BackupWorkflowResponse.model_validate(resp.json())
        workflow_id = backup_resp.workflow_id

        # 2. Connect to Temporal to wait for completion
        temporal = await Client.connect(TEMPORAL_URL)
        handle = temporal.get_workflow_handle(workflow_id)

        # Wait for completion
        try:
            result = await handle.result()
            assert result is not None
        except Exception as e:
            pytest.fail(f"Backup workflow failed: {e}")

        # 3. Verify S3 object creation
        s3 = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name="us-east-1",
        )

        # Check for postgres backup key if returned in result
        pg_key = result.get("postgres_backup_key")
        if pg_key:
            # Verify object exists in bucket
            backup_bucket = os.getenv("BACKUP_S3_BUCKET", ASSET_BUCKET)
            try:
                s3.head_object(Bucket=backup_bucket, Key=pg_key)
            except Exception as e:
                pytest.fail(
                    f"Postgres backup object {pg_key} not found in {backup_bucket}: {e}"
                )


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

        # 2. Wait for completion to ensure traces and assets exist
        max_retries = 30
        for _ in range(max_retries):
            status_resp = await client.get(f"{CONTROLLER_URL}/episodes/{episode_id}")
            ep = EpisodeResponse.model_validate(status_resp.json())
            if ep.status in [EpisodeStatus.COMPLETED, EpisodeStatus.FAILED]:
                break
            await asyncio.sleep(1)

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
