import asyncio
import time

import httpx
import pytest

from shared.workers.schema import BenchmarkToolResponse

# Adjust URL to your worker
WORKER_LIGHT_URL = "http://localhost:18001"
WORKER_HEAVY_URL = "http://localhost:18002"

# A simple valid script that does something
SCRIPT_CONTENT = """
from build123d import *
from shared.models.schemas import PartMetadata
def build():
    b = Box(10, 10, 10)
    b.label = "test_box"
    b.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return b
"""


async def run_simulation(session_id: str):
    async with httpx.AsyncClient(timeout=300.0) as client:
        start_time = time.time()
        resp = await client.post(
            f"{WORKER_HEAVY_URL}/benchmark/simulate",
            json={
                "script_path": "test_box.py",
                "script_content": SCRIPT_CONTENT,
            },
            headers={"X-Session-ID": session_id},
        )
        end_time = time.time()
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw_text": resp.text}
        return resp.status_code, payload, start_time, end_time


@pytest.mark.integration
@pytest.mark.asyncio
async def test_simulation_concurrency_single_flight_busy_admission():
    # INT-004: one external heavy job is admitted, /ready flips away from ready,
    # and concurrent requests fail fast with deterministic WORKER_BUSY responses.

    session_ids = [f"sess_serialize_{i}_{int(time.time())}" for i in range(3)]

    # Pre-write the scripts
    async with httpx.AsyncClient(timeout=300.0) as client:
        for sid in session_ids:
            await client.post(
                f"{WORKER_LIGHT_URL}/fs/write",
                json={"path": "test_box.py", "content": SCRIPT_CONTENT},
                headers={"X-Session-ID": sid},
            )

    global_start = time.time()
    results = await asyncio.gather(*[run_simulation(sid) for sid in session_ids])
    global_end = time.time()

    total_duration = global_end - global_start

    successes: list[BenchmarkToolResponse] = []
    busy_payloads: list[dict] = []
    unexpected: list[str] = []

    for i, (status_code, payload, _start, _end) in enumerate(results):
        if status_code == 200:
            parsed = BenchmarkToolResponse.model_validate(payload)
            if parsed.success:
                successes.append(parsed)
            else:
                unexpected.append(
                    f"request[{i}] returned 200 but success=false: {parsed.message}"
                )
            continue

        if status_code == 503:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if isinstance(detail, dict) and detail.get("code") == "WORKER_BUSY":
                busy_payloads.append(payload)
            else:
                unexpected.append(
                    f"request[{i}] returned 503 without WORKER_BUSY payload: {payload}"
                )
            continue

        unexpected.append(f"request[{i}] unexpected status={status_code}: {payload}")

    assert not unexpected, "\n".join(unexpected)
    assert len(successes) == 1, (
        f"expected exactly 1 admitted request, got {len(successes)}"
    )
    assert len(busy_payloads) >= 1, (
        "expected concurrent requests to fail fast with WORKER_BUSY"
    )

    # Fail-fast behavior should reduce total wall time vs serialized queueing.
    assert total_duration < 240, f"run took unexpectedly long ({total_duration:.2f}s)"


if __name__ == "__main__":
    asyncio.run(test_simulation_concurrency_single_flight_busy_admission())
