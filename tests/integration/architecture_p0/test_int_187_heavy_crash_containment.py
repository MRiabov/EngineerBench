import uuid
from time import sleep

import httpx
import pytest

from shared.workers.schema import BenchmarkToolResponse
from worker_heavy.runtime.simulation_runner import (
    SimulationExecutorManager,
    SimulationExecutorOperationTimeoutError,
)

WORKER_LIGHT_URL = "http://localhost:18001"
WORKER_HEAVY_URL = "http://localhost:18002"

VALID_SCRIPT = """
from build123d import *
from shared.models.schemas import PartMetadata

def build():
    p = Box(10, 10, 10)
    p.label = "ok_part"
    p.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return p
"""

CRASH_SCRIPT = """
import os
os._exit(42)
"""


def _session_id() -> str:
    return f"INT-187-{uuid.uuid4().hex[:8]}"


@pytest.mark.integration
@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        r"simulation_child_process_crashed",
        r"simulation_executor_crashed",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-187")
async def test_int_187_heavy_worker_crash_containment_boundary():
    crash_sid = _session_id()
    ok_sid = _session_id()

    async with httpx.AsyncClient(timeout=120.0) as client:
        crash_resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json={"script_path": "crash.py", "script_content": CRASH_SCRIPT},
            headers={"X-Session-ID": crash_sid},
        )

        assert crash_resp.status_code == 200, crash_resp.text
        crash_body = BenchmarkToolResponse.model_validate(crash_resp.json())
        assert not crash_body.success, "crash case unexpectedly succeeded"
        assert "SIMULATION_CHILD_PROCESS_CRASHED" in (crash_body.message or "")

        health = await client.get(f"{WORKER_HEAVY_URL}/health")
        assert health.status_code == 200, health.text
        assert health.json().get("status") == "healthy"

        write_resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json={"path": "ok.py", "content": VALID_SCRIPT},
            headers={"X-Session-ID": ok_sid},
        )
        assert write_resp.status_code == 200, write_resp.text

        # Subsequent heavy request must still be served after crash.
        validate_resp = await client.post(
            f"{WORKER_LIGHT_URL}/benchmark/validate",
            json={"script_path": "ok.py", "script_content": VALID_SCRIPT},
            headers={"X-Session-ID": ok_sid},
        )
        assert validate_resp.status_code == 200, validate_resp.text
        validate_body = BenchmarkToolResponse.model_validate(validate_resp.json())
        assert validate_body.success, validate_body.message

        # Sanity: keep test deterministic under contention by briefly checking ready.
        ready_resp = await client.get(f"{WORKER_HEAVY_URL}/ready")
        assert ready_resp.status_code == 200, ready_resp.text
        assert ready_resp.json().get("status") == "ready"


@pytest.mark.integration
@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-189")
async def test_int_189_simulation_executor_timeout_recreates_child():
    manager = SimulationExecutorManager()

    try:
        with pytest.raises(SimulationExecutorOperationTimeoutError):
            await manager.submit(
                "simulate",
                "SIMULATION_CHILD_PROCESS_CRASHED",
                sleep,
                2.0,
                timeout_seconds=0.2,
            )

        result = await manager.submit(
            "validate",
            "VALIDATION_CHILD_PROCESS_CRASHED",
            pow,
            2,
            5,
        )
        assert result == 32
    finally:
        await manager.shutdown()
