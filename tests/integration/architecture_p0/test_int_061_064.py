import os
import time

import httpx
import pytest

from controller.api.schemas import OpenAPISchema
from shared.workers.schema import (
    DeleteFileRequest,
    WriteFileRequest,
)

# Constants
WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
WORKER_HEAVY_URL = os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002")


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-061")
async def test_int_061_asset_serving_security():
    """INT-061: Asset serving security + session isolation contract."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_a = f"test-61-a-{int(time.time())}"
        session_b = f"test-61-b-{int(time.time())}"

        # 1. Setup session A with a valid python file and an asset
        write_py_a = WriteFileRequest(
            path="part.py",
            content="import build123d\ndef build(): return None",
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_py_a.model_dump(mode="json"),
            headers={"X-Session-ID": session_a},
        )
        write_stl_a = WriteFileRequest(path="part.stl", content="dummy-stl-content")
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_stl_a.model_dump(mode="json"),
            headers={"X-Session-ID": session_a},
        )

        # 2. Setup session B with a broken python file and an asset
        write_py_b = WriteFileRequest(
            path="broken.py",
            content="invalid syntax !!!",
        )
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_py_b.model_dump(mode="json"),
            headers={"X-Session-ID": session_b},
        )
        write_stl_b = WriteFileRequest(path="broken.stl", content="dummy-stl-content")
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_stl_b.model_dump(mode="json"),
            headers={"X-Session-ID": session_b},
        )

        # 3. Assert successful serving and MIME type for session A
        resp = await client.get(
            f"{WORKER_LIGHT_URL}/assets/part.stl", headers={"X-Session-ID": session_a}
        )
        assert resp.status_code == 200
        assert resp.content == b"dummy-stl-content"
        assert resp.headers["content-type"] == "model/stl"

        # 4. Assert 422 for session B due to syntax error in broken.py
        resp = await client.get(
            f"{WORKER_LIGHT_URL}/assets/broken.stl", headers={"X-Session-ID": session_b}
        )
        assert resp.status_code == 422
        assert "has syntax errors" in resp.text

        # 5. Assert session isolation: session B cannot access session A's assets
        resp = await client.get(
            f"{WORKER_LIGHT_URL}/assets/part.stl", headers={"X-Session-ID": session_b}
        )
        assert resp.status_code == 404

        # 6. Verify other MIME types
        write_png_a = WriteFileRequest(path="test.png", content="png-data")
        await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_png_a.model_dump(mode="json"),
            headers={"X-Session-ID": session_a},
        )
        resp = await client.get(
            f"{WORKER_LIGHT_URL}/assets/test.png", headers={"X-Session-ID": session_a}
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-062")
async def test_int_062_worker_openapi_contract():
    """INT-062: Split-worker OpenAPI artifact contract."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        # Check Worker Light OpenAPI
        resp = await client.get(f"{WORKER_LIGHT_URL}/openapi.json")
        assert resp.status_code == 200
        light_schema = OpenAPISchema.model_validate(resp.json())
        paths = light_schema.paths
        assert "/fs/ls" in paths
        assert "/assets/{path}" in paths

        # Check Worker Heavy OpenAPI
        resp = await client.get(f"{WORKER_HEAVY_URL}/openapi.json")
        assert resp.status_code == 200
        heavy_schema = OpenAPISchema.model_validate(resp.json())
        paths = heavy_schema.paths
        assert "/benchmark/simulate" in paths
        assert "/benchmark/validate" in paths


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-063")
async def test_int_063_mounted_path_read_only():
    """INT-063: Mounted path compatibility/read-only contract."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"test-63-{int(time.time())}"

        # 1. Verify workspace root is writable
        write_root = WriteFileRequest(path="writable.txt", content="i am writable")
        resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=write_root.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )
        assert resp.status_code == 200

        # 2. Verify read-only mounts
        for ro_path in ["/utils", "/skills", "/reviews", "/config"]:
            # Try write
            write_ro = WriteFileRequest(path=f"{ro_path}/test.txt", content="fail")
            resp = await client.post(
                f"{WORKER_LIGHT_URL}/fs/write",
                json=write_ro.model_dump(mode="json"),
                headers={"X-Session-ID": session_id},
            )
            assert resp.status_code == 403, f"Expected 403 for {ro_path} write"

            # Try delete
            delete_ro = DeleteFileRequest(path=f"{ro_path}/nonexistent")
            resp = await client.post(
                f"{WORKER_LIGHT_URL}/fs/delete",
                json=delete_ro.model_dump(mode="json"),
                headers={"X-Session-ID": session_id},
            )
            assert resp.status_code == 403, f"Expected 403 for {ro_path} delete"


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-070")
async def test_int_070_mounted_path_traversal_protection():
    """INT-070: Mounted path traversal protection."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        session_id = f"INT-070-{int(time.time())}"

        # Attempt to escape /utils mount point via path traversal.
        # We use /fs/read because GET /assets/... might be normalized by the HTTP client.
        # Path in JSON body is not normalized by the client.
        from shared.workers.schema import ReadFileRequest

        read_req = ReadFileRequest(path="/utils/../pyproject.toml")
        resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/read",
            json=read_req.model_dump(mode="json"),
            headers={"X-Session-ID": session_id},
        )

        # Should be blocked with 403 Forbidden.
        assert resp.status_code == 403
        assert "Path traversal attempted" in resp.text
