import asyncio
import os
import uuid
from pathlib import Path

import httpx
import pytest
import yaml

from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    BenchmarkGenerateRequest,
    BenchmarkGenerateResponse,
    EpisodeResponse,
    StandardResponse,
)
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName, EpisodeStatus
from shared.models.schemas import (
    BenchmarkDefinition,
    BoundingBox,
    Constraints,
    MovedObject,
    ObjectivesSection,
)
from shared.workers.schema import BenchmarkToolResponse, WriteFileRequest
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


async def _seed_current_role_manifest(
    client: httpx.AsyncClient, *, session_id: str, agent_name: AgentName
) -> None:
    response = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path=".manifests/current_role.json",
            content=current_role_manifest_json(agent_name),
            overwrite=True,
            bypass_agent_permissions=True,
        ).model_dump(mode="json"),
        headers={
            "X-Session-ID": session_id,
            "X-System-FS-Bypass": "1",
        },
    )
    assert response.status_code == 200, response.text


async def _seed_workspace_file(
    client: httpx.AsyncClient,
    *,
    session_id: str,
    path: str,
    content: str,
) -> None:
    response = await client.post(
        f"{WORKER_LIGHT_URL}/fs/write",
        json=WriteFileRequest(
            path=path,
            content=content,
            overwrite=True,
            bypass_agent_permissions=True,
        ).model_dump(mode="json"),
        headers={
            "X-Session-ID": session_id,
            "X-System-FS-Bypass": "1",
        },
    )
    assert response.status_code == 200, response.text


async def _wait_for_episode_trace_names(
    client: httpx.AsyncClient,
    *,
    episode_id: str,
    expected_names: set[str],
    timeout_s: float = 30.0,
) -> set[str]:
    deadline = asyncio.get_running_loop().time() + timeout_s
    seen_names: set[str] = set()
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"{CONTROLLER_URL}/episodes/{episode_id}")
        assert response.status_code == 200, response.text
        episode = EpisodeResponse.model_validate(response.json())
        seen_names = {
            trace.name for trace in (episode.traces or []) if trace.name is not None
        }
        if expected_names.issubset(seen_names):
            return seen_names
        await asyncio.sleep(0.5)

    return seen_names


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-026")
async def test_int_026_mandatory_event_families(tmp_path: Path):
    """INT-026: Verify mandatory event families are emitted in a real run."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        await _require_service(client, "worker-light", WORKER_LIGHT_URL)
        await _require_service(client, "controller", CONTROLLER_URL)
        session_id = f"INT-026-{uuid.uuid4().hex[:8]}"
        await _seed_current_role_manifest(
            client, session_id=session_id, agent_name=AgentName.BENCHMARK_CODER
        )
        create_episode_resp = await client.post(
            f"{CONTROLLER_URL}/api/test/episodes",
            json=AgentRunRequest(
                task="INT-026 trace capture",
                session_id=session_id,
            ).model_dump(mode="json"),
        )
        assert create_episode_resp.status_code == 201, create_episode_resp.text
        episode_id = str(create_episode_resp.json()["episode_id"])

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

        # 2. Write a script that returns a valid component and emits a tool event.
        script = """
from build123d import *
from shared.observability.events import emit_event
from shared.observability.schemas import ToolInvocationEvent
from shared.models.schemas import PartMetadata

def build():
    emit_event(
        ToolInvocationEvent(
            tool_name="benchmark_script_build",
            arguments={"script_path": "benchmark_script.py"},
        )
    )
    p = Box(1, 1, 1)
    p.label = "test_part"
    p.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return p
"""
        await _seed_workspace_file(
            client,
            session_id=session_id,
            path="benchmark_definition.yaml",
            content=yaml.dump(objectives.model_dump(mode="json")),
        )
        await _seed_workspace_file(
            client,
            session_id=session_id,
            path="benchmark_script.py",
            content=script,
        )

        # 3. Trigger simulation through the controller boundary so request/result
        # events are recorded by the real observability middleware.
        resp = await _post_with_busy_retry(
            client,
            url=f"{CONTROLLER_URL}/api/script-tools/simulate",
            json_payload={
                "script_path": "benchmark_script.py",
                "agent_role": "benchmark_coder",
                "smoke_test_mode": True,
                "episode_id": episode_id,
            },
            headers={"X-Session-ID": session_id},
            timeout=300.0,
        )
        assert resp.status_code == 200
        data = BenchmarkToolResponse.model_validate(resp.json())
        assert data.success is True

        trace_names = await _wait_for_episode_trace_names(
            client,
            episode_id=episode_id,
            expected_names={
                "simulation_request",
                "simulation_result",
                "tool_invocation",
            },
        )

        assert "simulation_request" in trace_names, "Missing simulation_request trace"
        assert "simulation_result" in trace_names, "Missing simulation_result trace"
        assert "tool_invocation" in trace_names, "Missing tool_invocation trace"


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
@pytest.mark.int_id("INT-029")
async def test_int_029_api_key_enforcement(controller_client):
    """INT-029: Verify the legacy backup endpoint is no longer exposed."""
    client = controller_client

    # No key
    resp = await client.post("/ops/backup")
    assert resp.status_code == 404

    # Invalid auth
    resp = await client.post(
        "/ops/backup",
        headers={"X-Backup-Secret": "invalid-auth-val"},
    )
    assert resp.status_code == 404

    valid_auth = os.getenv("BACKUP_SECRET", "change-me-in-production")
    resp = await client.post("/ops/backup", headers={"X-Backup-Secret": valid_auth})
    assert resp.status_code == 404


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
