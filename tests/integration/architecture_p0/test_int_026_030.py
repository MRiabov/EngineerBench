import asyncio
import os
import uuid

import httpx
import pytest
import yaml

from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    BenchmarkGenerateRequest,
    BenchmarkGenerateResponse,
    EpisodeResponse,
    OpenAPISchema,
    StandardResponse,
)
from shared.enums import EpisodeStatus
from shared.models.schemas import (
    BenchmarkDefinition,
    BoundingBox,
    Constraints,
    MovedObject,
    ObjectivesSection,
)
from shared.workers.schema import (
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    WriteFileRequest,
)
from tests.integration.agent.helpers import seed_benchmark_assembly_definition

# Constants
WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
WORKER_HEAVY_URL = os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002")
CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")


def _default_benchmark_parts():
    return [
        {
            "part_id": "environment_fixture",
            "label": "environment_fixture",
            "metadata": {"fixed": True, "material_id": "aluminum_6061"},
        }
    ]


def _event_get(event, key: str, default=None):
    if isinstance(event, dict):
        return event.get(key, default)
    if hasattr(event, "get"):
        return event.get(key, default)
    return getattr(event, key, default)


async def _require_service(client: httpx.AsyncClient, name: str, url: str):
    try:
        resp = await client.get(f"{url}/health", timeout=5.0)
        resp.raise_for_status()
    except Exception:
        pytest.skip(f"{name} is not reachable at {url}")


async def _post_with_busy_retry(
    client: httpx.AsyncClient,
    *,
    url: str,
    json_payload: dict,
    headers: dict[str, str],
    timeout: float,
    max_attempts: int = 120,
) -> httpx.Response:
    """
    Retry transient heavy-worker busy responses (503) using readiness polling.
    This keeps the test deterministic under single-flight admission contention.
    """
    response: httpx.Response | None = None
    for attempt in range(max_attempts):
        response = await client.post(
            url,
            json=json_payload,
            headers=headers,
            timeout=timeout,
        )
        if response.status_code != 503:
            return response

        try:
            ready_resp = await client.get(f"{WORKER_HEAVY_URL}/ready", timeout=5.0)
            if ready_resp.status_code == 200:
                continue
        except Exception:
            # Keep retrying on transient readiness probe failures.
            pass

        await asyncio.sleep(1.0)

    assert response is not None
    return response


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-026")
async def test_int_026_mandatory_event_families():
    """INT-026: Verify mandatory event families are emitted in a real run."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        await _require_service(client, "worker-light", WORKER_LIGHT_URL)
        await _require_service(client, "worker-heavy", WORKER_HEAVY_URL)
        session_id = f"INT-026-{uuid.uuid4().hex[:8]}"

        # 1. Setup benchmark_definition.yaml
        objectives = BenchmarkDefinition(
            objectives=ObjectivesSection(
                goal_zone=BoundingBox(min=(8, 8, 8), max=(12, 12, 12)),
                build_zone=BoundingBox(min=(0, 0, 0), max=(20, 20, 20)),
            ),
            simulation_bounds=BoundingBox(min=(-10, -10, -10), max=(30, 30, 30)),
            payload=MovedObject(
                label="test_obj",
                shape="sphere",
                material_id="aluminum_6061",
                start_position=(0, 0, 5),
                runtime_jitter=(0, 0, 0),
            ),
            constraints=Constraints(max_unit_cost=100.0, max_weight_g=10.0),
            benchmark_parts=_default_benchmark_parts(),
        )
        write_obj_req = WriteFileRequest(
            path="benchmark_definition.yaml",
            content=yaml.dump(objectives.model_dump(mode="json")),
            overwrite=True,
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_obj_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        # 2. Write a script that manually emits an event to verify collection
        script = """
import os
from build123d import *
from shared.models.schemas import PartMetadata
from shared.observability.events import emit_event

def build():
    # Emit event to verify collection
    emit_event({"event_type": "simulation_result", "data": {"status": "success"}})
    
    # Trigger a standardized tool invocation event
    emit_event({"event_type": "tool_invocation", "data": {"tool": "fastener_hole", "args": {"type": "M3"}}})

    p = Box(1, 1, 1)
    p.label = "test_part"
    p.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return p
"""
        write_script_req = WriteFileRequest(
            path="script.py", content=script, overwrite=True
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_script_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        # 3. Trigger simulation
        sim_req = BenchmarkToolRequest(script_path="script.py")
        resp = await _post_with_busy_retry(
            client,
            url=f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json_payload=sim_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
            timeout=300.0,
        )
        assert resp.status_code == 200
        data = BenchmarkToolResponse.model_validate(resp.json())
        events = data.events

        # Verify event families
        event_types = [_event_get(e, "event_type") for e in events]
        assert "simulation_result" in event_types, "Missing simulation_result event"
        assert "tool_invocation" in event_types, "Missing tool_invocation event"


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-027")
async def test_int_027_seed_variant_tracking():
    """INT-027: Verify DB persistence of variant_id and seed from the API response."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"INT-027-{uuid.uuid4().hex[:8]}"
        variant_id = "test-variant-027"
        seed = 42

        # 1. Start an episode with seed and variant_id in metadata_vars
        await seed_benchmark_assembly_definition(client, session_id)
        payload = AgentRunRequest(
            task="Test seed and variant tracking",
            session_id=session_id,
            metadata_vars={
                "variant_id": variant_id,
                "seed": seed,
            },
        )
        resp = await client.post(
            f"{CONTROLLER_URL}/agent/run", json=payload.model_dump(mode="json")
        )
        assert resp.status_code == 202
        run_data = AgentRunResponse.model_validate(resp.json())
        episode_id = run_data.episode_id

        # 2. Verify that variant_id and seed are persisted in the episode record
        data = None
        for _ in range(5):
            try:
                status_resp = await client.get(
                    f"{CONTROLLER_URL}/episodes/{episode_id}", timeout=10.0
                )
                if status_resp.status_code == 200:
                    ep_data = EpisodeResponse.model_validate(status_resp.json())
                    if (
                        ep_data.metadata_vars
                        and ep_data.metadata_vars.variant_id == variant_id
                    ):
                        data = ep_data
                        break
            except (httpx.ReadTimeout, httpx.ConnectError):
                pass
            await asyncio.sleep(1)

        assert data is not None
        assert data.metadata_vars is not None
        assert data.metadata_vars.variant_id == variant_id
        assert data.metadata_vars.seed == seed


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-028")
async def test_int_028_strict_api_schema_contract():
    """INT-028: Verify OpenAPI schema validity and live responses."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # 1. Controller OpenAPI
        resp = await client.get(f"{CONTROLLER_URL}/openapi.json")
        assert resp.status_code == 200
        schema_data = resp.json()
        OpenAPISchema.model_validate(schema_data)
        assert "openapi" in schema_data

        # 2. Worker OpenAPI
        resp = await client.get(f"{WORKER_LIGHT_URL}/openapi.json")
        assert resp.status_code == 200
        worker_schema = resp.json()
        OpenAPISchema.model_validate(worker_schema)

        # 3. Validate a live response against the schema
        health_resp = await client.get(f"{WORKER_LIGHT_URL}/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()

        try:
            health_schema = worker_schema["paths"]["/health"]["get"]["responses"][
                "200"
            ]["content"]["application/json"]["schema"]
            if "$ref" in health_schema:
                ref_name = health_schema["$ref"].split("/")[-1]
                health_schema = worker_schema["components"]["schemas"][ref_name]

            if "required" in health_schema:
                for req in health_schema["required"]:
                    assert req in health_data, (
                        f"Missing required field {req} in /health response"
                    )

            properties = health_schema.get("properties", {})
            if "status" in properties:
                assert "status" in health_data

        except KeyError as e:
            pytest.fail(f"Could not locate schema for /health validation: {e}")


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-029")
async def test_int_029_api_key_enforcement(controller_client):
    """INT-029: Verify API key enforcement on protected endpoints."""
    client = controller_client

    # No key
    resp = await client.post("/ops/backup")
    assert resp.status_code == 403

    # Invalid auth
    resp = await client.post(
        "/ops/backup",
        headers={"X-Backup-Secret": "invalid-auth-val"},
    )
    assert resp.status_code == 403

    valid_auth = os.getenv("BACKUP_SECRET", "change-me-in-production")
    resp = await client.post("/ops/backup", headers={"X-Backup-Secret": valid_auth})
    assert resp.status_code in [202, 500]
    if resp.status_code == 500:
        assert (
            "Backup configuration missing" in resp.text
            or "Temporal" in resp.text
            or "connection" in resp.text.lower()
        )


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-030")
async def test_int_030_interrupt_propagation():
    """INT-030: Verify user interrupt cancels worker jobs."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"INT-030-{uuid.uuid4().hex[:8]}"
        await seed_benchmark_assembly_definition(client, session_id)
        payload = AgentRunRequest(
            task="Perform a very complex multi-step reasoning task.",
            session_id=session_id,
        )
        resp = await client.post(
            f"{CONTROLLER_URL}/agent/run", json=payload.model_dump(mode="json")
        )
        assert resp.status_code == 202
        run_data = AgentRunResponse.model_validate(resp.json())
        episode_id = run_data.episode_id

        await asyncio.sleep(0.5)

        interrupt_resp = await client.post(
            f"{CONTROLLER_URL}/episodes/{episode_id}/interrupt"
        )
        assert interrupt_resp.status_code in [200, 202]
        StandardResponse.model_validate(interrupt_resp.json())

        status = None
        for _i in range(20):
            await asyncio.sleep(0.5)
            status_resp = await client.get(f"{CONTROLLER_URL}/episodes/{episode_id}")
            assert status_resp.status_code == 200
            ep_data = EpisodeResponse.model_validate(status_resp.json())
            status = ep_data.status
            if status in [EpisodeStatus.CANCELLED, EpisodeStatus.FAILED]:
                break

        assert status in [
            EpisodeStatus.CANCELLED,
            EpisodeStatus.FAILED,
        ], f"Expected cancelled or failed, got {status}"


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-030")
async def test_int_030_benchmark_interrupt_propagation():
    """INT-030 benchmark variant: Verify user interrupt cancels benchmark jobs."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        request = BenchmarkGenerateRequest(
            prompt=f"INT-030 benchmark interrupt path {uuid.uuid4()}",
        )
        resp = await client.post(
            f"{CONTROLLER_URL}/benchmark/generate",
            json=request.model_dump(mode="json"),
        )
        assert resp.status_code in [200, 202], resp.text
        run_data = BenchmarkGenerateResponse.model_validate(resp.json())
        episode_id = run_data.episode_id

        saw_running = False
        for _ in range(40):
            status_resp = await client.get(f"{CONTROLLER_URL}/benchmark/{episode_id}")
            if status_resp.status_code == 200:
                ep_data = EpisodeResponse.model_validate(status_resp.json())
                if ep_data.status == EpisodeStatus.RUNNING:
                    saw_running = True
                    break
                if ep_data.status in [
                    EpisodeStatus.PLANNED,
                    EpisodeStatus.COMPLETED,
                    EpisodeStatus.FAILED,
                    EpisodeStatus.CANCELLED,
                ]:
                    break
            await asyncio.sleep(0.25)

        assert saw_running, "Benchmark run never entered RUNNING before interrupt"

        interrupt_resp = await client.post(
            f"{CONTROLLER_URL}/episodes/{episode_id}/interrupt"
        )
        assert interrupt_resp.status_code in [200, 202]
        StandardResponse.model_validate(interrupt_resp.json())

        final_status = None
        for _ in range(40):
            await asyncio.sleep(0.5)
            status_resp = await client.get(f"{CONTROLLER_URL}/benchmark/{episode_id}")
            assert status_resp.status_code == 200
            ep_data = EpisodeResponse.model_validate(status_resp.json())
            final_status = ep_data.status
            if final_status in [EpisodeStatus.CANCELLED, EpisodeStatus.FAILED]:
                break

        assert final_status == EpisodeStatus.CANCELLED, (
            f"Expected benchmark interrupt to cancel run, got {final_status}"
        )
