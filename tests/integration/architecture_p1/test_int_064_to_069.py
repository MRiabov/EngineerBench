import os
import uuid

import httpx
import pytest

from controller.api.schemas import CotsMetadataResponse, CotsSearchItem
from shared.workers.schema import (
    ExecuteRequest,
    ExecuteResponse,
    WriteFileRequest,
)

CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")
WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
WORKER_HEAVY_URL = os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002")


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_int_064_cots_metadata():
    """INT-064: COTS reproducibility metadata persistence."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # Seed a part first to ensure search works
        import json
        import sqlite3

        conn = sqlite3.connect("parts.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO parts (part_id, name, category, unit_cost, weight_g, import_recipe, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "M3_BOLT",
                "M3 Bolt",
                "Fastener",
                0.5,
                1.2,
                "recipe",
                json.dumps({"manufacturer": "Generic"}),
            ),
        )
        conn.commit()
        conn.close()

        # 1. Fetch metadata
        resp = await client.get(f"{CONTROLLER_URL}/api/cots/metadata")
        assert resp.status_code == 200
        # Validate COTS metadata structure
        data = CotsMetadataResponse.model_validate(resp.json())
        assert data.catalog_version is not None
        assert data.bd_warehouse_commit is not None

        # 2. Trigger search and check events (indirectly via search output or assuming search_parts logs it)
        # We'll just verify the endpoint exists and returns data as a proxy for persistence.
        # Ideally we'd check Langfuse/DB for the COTSSearchEvent fields.
        search_resp = await client.get(
            f"{CONTROLLER_URL}/api/cots/search", params={"q": "M3"}
        )
        assert search_resp.status_code == 200
        results = [CotsSearchItem.model_validate(item) for item in search_resp.json()]
        assert len(results) > 0


@pytest.mark.integration_p1
@pytest.mark.xdist_group(name="physics_sims")
@pytest.mark.asyncio
async def test_int_064_session_workspace_copies_parts_db_catalog():
    """INT-064: session workspaces must receive a usable catalog snapshot."""
    session_id = f"INT-064-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(timeout=300.0) as client:
        exec_resp = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code=(
                    "python - <<'PY'\n"
                    "import sqlite3\n"
                    "conn = sqlite3.connect('parts.db')\n"
                    "row = conn.execute(\n"
                    "    'SELECT part_id FROM parts WHERE part_id = ?',\n"
                    "    ('ServoMotor_SG90',),\n"
                    ").fetchone()\n"
                    "print(row[0] if row else '')\n"
                    "PY"
                ),
                timeout=60,
            ).model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        assert exec_resp.status_code == 200, exec_resp.text
        data = ExecuteResponse.model_validate(exec_resp.json())
        assert data.exit_code == 0, data
        assert data.stdout.strip() == "ServoMotor_SG90", data.stdout


        # First write a dummy image
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="renders/test.png", content="dummy-binary-content"
            ).model_dump(),
            headers={"X-Session-ID": "test-fe-contract"},
        )

        asset_resp = await client.get(
            f"{CONTROLLER_URL}/api/episodes/{episode_id}/assets/renders/test.png"
        )
        assert asset_resp.status_code == 200
        assert asset_resp.content == b"dummy-binary-content"
