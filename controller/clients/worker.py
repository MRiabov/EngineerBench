import asyncio
import base64
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal, cast

import httpx
import structlog

from controller.clients.worker_ws import WorkerLightWebSocketClient
from controller.config.settings import settings
from shared.current_role import current_role_agent_name_from_text
from shared.enums import AgentName, ResponseStatus
from shared.observability.storage import S3Client, S3Config
from shared.script_contracts import role_family_for_agent
from shared.simulation.schemas import (
    SimulatorBackendType,
    get_default_simulator_backend,
)
from shared.simulation.smoke_mode import (
    ensure_smoke_test_mode_allowed,
    resolve_default_smoke_test_mode,
)
from shared.workers.filesystem.backend import FileInfo
from shared.workers.schema import (
    BenchmarkToolResponse,
    EditOp,
    ExecuteResponse,
    ExistsResponse,
    GitCommitResponse,
    GitStatusResponse,
    GrepMatch,
    HealthResponse,
    InspectTopologyResponse,
    PreviewDesignResponse,
    PreviewRenderingType,
    ReadFileResponse,
    ReadFilesResponse,
    StatusResponse,
    UploadFilesFromObjectStoreRequest,
    WorkerLightRpcAction,
    WorkerLightRpcRequest,
)
from shared.workers.workbench_models import ManufacturingMethod, WorkbenchResult

logger = structlog.get_logger(__name__)


def _default_smoke_test_mode() -> bool:
    return resolve_default_smoke_test_mode(
        integration_enabled=settings.is_integration_test
    )


def _storage_client_from_env() -> S3Client | None:
    access_key = os.getenv("S3_ACCESS_KEY", os.getenv("AWS_ACCESS_KEY_ID"))
    secret_key = os.getenv("S3_SECRET_KEY", os.getenv("AWS_SECRET_ACCESS_KEY"))
    if not access_key or not secret_key:
        return None

    return S3Client(
        S3Config(
            endpoint_url=os.getenv("S3_ENDPOINT"),
            access_key_id=access_key,
            secret_access_key=secret_key,
            bucket_name=os.getenv("ASSET_S3_BUCKET", "problemologist"),
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
    )


class WorkerClient:
    """Async client for interacting with the Problemologist Worker API."""

    def __init__(
        self,
        base_url: str,
        session_id: str,
        http_client: httpx.AsyncClient | None = None,
        heavy_url: str | None = None,
        controller_url: str | None = None,
        agent_role: AgentName | str = AgentName.ENGINEER_CODER,
        light_transport: Literal["auto", "http", "ws"] | None = None,
    ):
        """Initialize the worker client.

        Args:
            base_url: Base URL of the light worker service (e.g., http://worker-light:8000).
            session_id: Session ID to use for all requests.
            http_client: Pre-configured httpx.AsyncClient to reuse.
            heavy_url: Optional base URL of the heavy worker service.
        """
        self.base_url = base_url.rstrip("/")
        self.light_url = self.base_url
        self.heavy_url = (heavy_url or base_url).rstrip("/")
        controller_base_url = (
            controller_url
            if controller_url is not None
            else os.getenv("CONTROLLER_URL")
        )
        self.controller_url = (
            controller_base_url.rstrip("/") if controller_base_url else None
        )
        self.session_id = session_id
        self.agent_role = (
            agent_role.value if isinstance(agent_role, AgentName) else str(agent_role)
        )
        resolved_transport = (
            light_transport
            if light_transport is not None
            else settings.worker_light_transport
        )
        if isinstance(resolved_transport, str):
            resolved_transport = resolved_transport.strip().lower()
        if not resolved_transport or resolved_transport == "auto":
            resolved_transport = "ws"
        if resolved_transport not in {"http", "ws"}:
            raise ValueError(
                f"Unsupported worker light transport: {resolved_transport}"
            )
        self.light_transport = resolved_transport
        self.headers = {
            "X-Session-ID": session_id,
            "X-Agent-Role": self.agent_role,
            "X-Stage": self.agent_role,
        }
        self.http_client = http_client
        self._loop_clients: dict[int, httpx.AsyncClient] = {}
        self._loop_locks: dict[int, asyncio.Lock] = {}
        self._light_ws_client: WorkerLightWebSocketClient | None = None

    def _request_headers(
        self,
        *,
        bypass_agent_permissions: bool = False,
        stage: str | None = None,
        reviewer_stage: AgentName | None = None,
    ) -> dict[str, str]:
        headers = dict(self.headers)
        if stage:
            headers["X-Stage"] = stage
        if reviewer_stage:
            headers["X-Reviewer-Stage"] = reviewer_stage
            headers["X-Stage"] = reviewer_stage
        if bypass_agent_permissions:
            headers["X-System-FS-Bypass"] = "1"
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        """Helper to get a client, either shared or new (for compatibility)."""
        if self.http_client:
            return self.http_client

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Fallback for sync contexts that might somehow call this
            return httpx.AsyncClient()

        loop_id = id(loop)

        if loop_id in self._loop_clients:
            client = self._loop_clients[loop_id]
            # Check if the client is effectively closed or the loop is not running
            if getattr(client, "is_closed", False) or not loop.is_running():
                del self._loop_clients[loop_id]

        if loop_id not in self._loop_clients:
            if loop_id not in self._loop_locks:
                self._loop_locks[loop_id] = asyncio.Lock()

            async with self._loop_locks[loop_id]:
                if loop_id not in self._loop_clients:
                    self._loop_clients[loop_id] = httpx.AsyncClient()

        return self._loop_clients[loop_id]

    async def _close_client(self, client: httpx.AsyncClient):
        """Helper to close a client only if it was created locally."""
        # We no longer close the client here to allow connection pooling across requests.
        # The client will be closed when aclose() is called or the instance is destroyed.
        pass

    @staticmethod
    def _default_reviewer_stage(agent_role: AgentName | str) -> AgentName | None:
        role_value = (
            agent_role.value if isinstance(agent_role, AgentName) else str(agent_role)
        )
        role_to_stage: dict[str, AgentName] = {
            AgentName.BENCHMARK_CODER.value: AgentName.BENCHMARK_REVIEWER,
            AgentName.BENCHMARK_REVIEWER.value: AgentName.BENCHMARK_REVIEWER,
            AgentName.ELECTRONICS_REVIEWER.value: AgentName.ELECTRONICS_REVIEWER,
            AgentName.ENGINEER_CODER.value: AgentName.ENGINEER_EXECUTION_REVIEWER,
            AgentName.ENGINEER_EXECUTION_REVIEWER.value: AgentName.ENGINEER_EXECUTION_REVIEWER,
        }
        return role_to_stage.get(role_value)

    async def _call_controller_script_tool(
        self, action: str, payload: dict[str, Any], *, stage: str | None = None
    ) -> BenchmarkToolResponse | None:
        if not self.controller_url:
            return None
        client = await self._get_client()
        response = await client.post(
            f"{self.controller_url}/api/script-tools/{action.lstrip('/')}",
            json=payload,
            headers=self._request_headers(stage=stage),
            timeout=1000.0,
        )
        response.raise_for_status()
        return BenchmarkToolResponse.model_validate(response.json())

    def _should_use_light_websocket(self) -> bool:
        return self.light_transport == "ws"

    async def _get_light_ws_client(self) -> WorkerLightWebSocketClient:
        if self._light_ws_client is None:
            self._light_ws_client = WorkerLightWebSocketClient(
                self.base_url,
                self.headers,
            )
        return self._light_ws_client

    async def _light_ws_request(
        self, action: str, payload: dict[str, Any]
    ) -> dict[str, Any] | list[Any] | str | int | float | bool | None:
        client = await self._get_light_ws_client()
        request = WorkerLightRpcRequest(
            request_id=uuid.uuid4().hex,
            action=cast(WorkerLightRpcAction, action),
            payload=payload,
        )
        response = await client.request(request)
        if not response.ok:
            self._raise_light_ws_error(response, action)
        return response.result

    def _raise_light_ws_error(self, response, action: str) -> None:
        error = response.error
        status_code = error.status_code if error and error.status_code else 500
        message = (
            error.message
            if error
            else f"worker-light websocket action failed: {action}"
        )
        request = httpx.Request("WS", self.base_url)
        http_response = httpx.Response(
            status_code=status_code,
            request=request,
            content=message.encode("utf-8"),
        )
        raise httpx.HTTPStatusError(message, request=request, response=http_response)

    async def aclose(self):
        """Explicitly close all HTTP clients created for different loops."""
        # WP08: Handle loop-specific clients
        for loop_id, client in list(self._loop_clients.items()):
            await client.aclose()
            del self._loop_clients[loop_id]

        if self._light_ws_client is not None:
            await self._light_ws_client.aclose()
            self._light_ws_client = None

        # Compatibility for legacy _cached_client check in tests
        if hasattr(self, "_cached_client") and self._cached_client:
            await self._cached_client.aclose()
            self._cached_client = None

    async def inspect_topology(
        self, target_id: str, script_path: str = "script.py"
    ) -> InspectTopologyResponse:
        """Inspect topological features via worker."""
        if self._should_use_light_websocket():
            result = await self._light_ws_request(
                "topology_inspect",
                {"target_id": target_id, "script_path": script_path},
            )
            return InspectTopologyResponse.model_validate(result)
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/topology/inspect",
                json={"target_id": target_id, "script_path": script_path},
                headers=self.headers,
                timeout=10.0,
            )
            response.raise_for_status()
            return InspectTopologyResponse.model_validate(response.json())
        finally:
            await self._close_client(client)

    async def list_files(
        self, path: str = "/", *, bypass_agent_permissions: bool = False
    ) -> list[FileInfo]:
        """List contents of a directory."""
        if not path:
            path = "/"
        if self._should_use_light_websocket():
            result = await self._light_ws_request(
                "fs_ls",
                {
                    "path": path,
                    "bypass_agent_permissions": bypass_agent_permissions,
                },
            )
            return [FileInfo.model_validate(item) for item in result or []]
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/fs/ls",
                json={
                    "path": path,
                    "bypass_agent_permissions": bypass_agent_permissions,
                },
                headers=self._request_headers(
                    bypass_agent_permissions=bypass_agent_permissions
                ),
                timeout=10.0,
            )
            response.raise_for_status()
            return [FileInfo.model_validate(item) for item in response.json()]
        finally:
            await self._close_client(client)

    async def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        bypass_agent_permissions: bool = False,
    ) -> list[GrepMatch]:
        """Search for a pattern in files."""
        if self._should_use_light_websocket():
            result = await self._light_ws_request(
                "fs_grep",
                {
                    "pattern": pattern,
                    "path": path,
                    "glob": glob,
                    "bypass_agent_permissions": bypass_agent_permissions,
                },
            )
            return [GrepMatch.model_validate(item) for item in result or []]
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/fs/grep",
                json={
                    "pattern": pattern,
                    "path": path,
                    "glob": glob,
                    "bypass_agent_permissions": bypass_agent_permissions,
                },
                headers=self._request_headers(
                    bypass_agent_permissions=bypass_agent_permissions
                ),
                timeout=30.0,
            )
            response.raise_for_status()
            return [GrepMatch.model_validate(item) for item in response.json()]
        finally:
            await self._close_client(client)

    async def read_file(
        self, path: str, *, bypass_agent_permissions: bool = False
    ) -> str:
        """Read file contents."""
        if self._should_use_light_websocket():
            try:
                result = await self._light_ws_request(
                    "fs_read",
                    {
                        "path": path,
                        "bypass_agent_permissions": bypass_agent_permissions,
                    },
                )
                return ReadFileResponse.model_validate(result or {}).content
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return f"Error: File '{path}' not found."
                raise
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/fs/read",
                json={
                    "path": path,
                    "bypass_agent_permissions": bypass_agent_permissions,
                },
                headers=self._request_headers(
                    bypass_agent_permissions=bypass_agent_permissions
                ),
                timeout=10.0,
            )
            if response.status_code == 404:
                return f"Error: File '{path}' not found."
            response.raise_for_status()
            return ReadFileResponse.model_validate(response.json()).content
        finally:
            await self._close_client(client)

    async def read_file_optional(
        self, path: str, *, bypass_agent_permissions: bool = False
    ) -> str | None:
        """Read file contents and return ``None`` when the file does not exist."""
        if self._should_use_light_websocket():
            try:
                result = await self._light_ws_request(
                    "fs_read",
                    {
                        "path": path,
                        "bypass_agent_permissions": bypass_agent_permissions,
                    },
                )
                return ReadFileResponse.model_validate(result or {}).content
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return None
                raise
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/fs/read",
                json={
                    "path": path,
                    "bypass_agent_permissions": bypass_agent_permissions,
                },
                headers=self._request_headers(
                    bypass_agent_permissions=bypass_agent_permissions
                ),
                timeout=10.0,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return ReadFileResponse.model_validate(response.json()).content
        finally:
            await self._close_client(client)

    async def exists(
        self, path: str, *, bypass_agent_permissions: bool = False
    ) -> bool:
        """Check if a file exists."""
        if self._should_use_light_websocket():
            try:
                result = await self._light_ws_request(
                    "fs_exists",
                    {
                        "path": path,
                        "bypass_agent_permissions": bypass_agent_permissions,
                    },
                )
                return ExistsResponse.model_validate(result or {}).exists
            except httpx.HTTPStatusError:
                return False
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/fs/exists",
                json={
                    "path": path,
                    "bypass_agent_permissions": bypass_agent_permissions,
                },
                headers=self._request_headers(
                    bypass_agent_permissions=bypass_agent_permissions
                ),
                timeout=10.0,
            )
            if response.status_code == 404:
                return False
            response.raise_for_status()
            return ExistsResponse.model_validate(response.json()).exists
        except Exception:
            return False
        finally:
            await self._close_client(client)

    async def write_file(
        self,
        path: str,
        content: str,
        overwrite: bool = True,
        *,
        bypass_agent_permissions: bool = False,
    ) -> bool:
        """Write content to a file."""
        if self._should_use_light_websocket():
            result = await self._light_ws_request(
                "fs_write",
                {
                    "path": path,
                    "content": content,
                    "overwrite": overwrite,
                    "bypass_agent_permissions": bypass_agent_permissions,
                },
            )
            return (
                StatusResponse.model_validate(result or {}).status
                == ResponseStatus.SUCCESS
            )
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/fs/write",
                json={
                    "path": path,
                    "content": content,
                    "overwrite": overwrite,
                    "bypass_agent_permissions": bypass_agent_permissions,
                },
                headers=self._request_headers(
                    bypass_agent_permissions=bypass_agent_permissions
                ),
                timeout=10.0,
            )
            response.raise_for_status()
            return (
                StatusResponse.model_validate(response.json()).status
                == ResponseStatus.SUCCESS
            )
        finally:
            await self._close_client(client)

    async def bundle_session(self) -> bytes:
        """Bundle the session workspace into a gzipped tarball from the light worker."""
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.light_url}/fs/bundle",
                headers=self.headers,
                timeout=60.0,
            )
            response.raise_for_status()
            return response.content
        finally:
            await self._close_client(client)

    async def _add_bundle_to_payload(
        self, payload: dict, *, bundle_base64: str | None = None
    ):
        """Append workspace bundle payload for split light/heavy worker mode."""
        if bundle_base64 is not None:
            payload["bundle_base64"] = bundle_base64
        elif self.light_url != self.heavy_url:
            bundle = await self.bundle_session()
            payload["bundle_base64"] = base64.b64encode(bundle).decode("utf-8")

    @staticmethod
    def _multipart_escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @classmethod
    def _build_multipart_request(
        cls,
        *,
        fields: list[tuple[str, str]] | None = None,
        file_fields: list[tuple[str, str, bytes]] | None = None,
    ) -> tuple[bytes, str]:
        boundary = f"----problemologist-{uuid.uuid4().hex}"
        body = bytearray()
        fields = fields or []
        file_fields = file_fields or []

        for name, value in fields:
            body.extend(f"--{boundary}\r\n".encode("ascii"))
            body.extend(
                (
                    f'Content-Disposition: form-data; name="{cls._multipart_escape(name)}"'
                    "\r\n\r\n"
                ).encode("utf-8")
            )
            body.extend(value.encode("utf-8"))
            body.extend(b"\r\n")

        for name, filename, content in file_fields:
            body.extend(f"--{boundary}\r\n".encode("ascii"))
            body.extend(
                (
                    f'Content-Disposition: form-data; name="{cls._multipart_escape(name)}"; '
                    f'filename="{cls._multipart_escape(filename)}"\r\n'
                    "Content-Type: application/octet-stream\r\n\r\n"
                ).encode("utf-8")
            )
            body.extend(content)
            body.extend(b"\r\n")

        body.extend(f"--{boundary}--\r\n".encode("ascii"))
        return bytes(body), f"multipart/form-data; boundary={boundary}"

    class _AsyncBytesStream(httpx.AsyncByteStream):
        def __init__(self, data: bytes):
            self._data = data
            self._closed = False

        async def __aiter__(self):
            yield self._data

        async def aclose(self) -> None:
            self._closed = True

    async def _sync_handover_artifacts_to_light(
        self,
        response: BenchmarkToolResponse,
    ) -> None:
        """
        Mirror critical handover artifacts returned by the heavy worker into the
        light-worker workspace when running split-worker mode.
        """
        if self.light_url == self.heavy_url or not response.artifacts:
            return

        artifacts = response.artifacts
        writes: list[tuple[str, str]] = []
        if artifacts.validation_results_json:
            writes.append(
                ("validation_results.json", artifacts.validation_results_json)
            )
        if artifacts.simulation_result_json:
            writes.append(("simulation_result.json", artifacts.simulation_result_json))
        if artifacts.review_manifests_json:
            writes.extend(
                [
                    (path, content)
                    for path, content in artifacts.review_manifests_json.items()
                ]
            )
        elif artifacts.review_manifest_json:
            # Backward compatibility: keep honoring single-manifest payloads.
            writes.append(
                (
                    ".manifests/engineering_execution_handoff_manifest.json",
                    artifacts.review_manifest_json,
                )
            )

        batch_uploads: list[tuple[str, bytes]] = [
            (path, content.encode("utf-8")) for path, content in writes
        ]

        object_store_keys = getattr(artifacts, "object_store_keys", None) or {}
        object_store_uploads = [
            (path, object_key)
            for path, object_key in object_store_keys.items()
            if path not in artifacts.render_blobs_base64
        ]

        if object_store_uploads:
            try:
                if not await self.upload_files_from_object_store(
                    object_store_uploads,
                    bypass_agent_permissions=True,
                ):
                    logger.warning(
                        "handover_object_store_batch_upload_failed",
                        paths=[path for path, _ in object_store_uploads],
                    )
            except Exception as exc:
                logger.warning(
                    "handover_object_store_batch_upload_error",
                    error=str(exc),
                    paths=[path for path, _ in object_store_uploads],
                )
                storage_client = _storage_client_from_env()
                if storage_client is None:
                    logger.warning(
                        "handover_render_sync_object_store_unavailable",
                        paths=sorted(object_store_keys),
                    )
                else:
                    for path, object_key in object_store_uploads:
                        with tempfile.NamedTemporaryFile(
                            suffix=Path(path).suffix
                        ) as tmp:
                            storage_client.download_file(object_key, tmp.name)
                            batch_uploads.append((path, Path(tmp.name).read_bytes()))

        for path, encoded in artifacts.render_blobs_base64.items():
            if path in object_store_keys:
                continue
            batch_uploads.append((path, base64.b64decode(encoded)))

        if batch_uploads:
            if not await self.upload_files(
                batch_uploads,
                bypass_agent_permissions=True,
            ):
                logger.warning(
                    "handover_artifact_batch_upload_failed",
                    paths=[path for path, _ in batch_uploads],
                )
            else:
                for path, _ in batch_uploads:
                    logger.info("handover_artifact_synced", path=path)

    async def upload_files_from_object_store(
        self,
        files: list[tuple[str, str]],
        *,
        bypass_agent_permissions: bool = False,
    ) -> bool:
        """Stage multiple files by letting the worker-light service pull from S3."""
        payload = UploadFilesFromObjectStoreRequest(
            files=[
                {"path": path, "object_store_key": object_key}
                for path, object_key in files
            ],
            bypass_agent_permissions=bypass_agent_permissions,
        ).model_dump(mode="json")

        if self._should_use_light_websocket():
            result = await self._light_ws_request(
                "fs_upload_files_object_store", payload
            )
            return (
                StatusResponse.model_validate(result or {}).status
                == ResponseStatus.SUCCESS
            )

        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/fs/upload_files_object_store",
                json=payload,
                headers=self._request_headers(
                    bypass_agent_permissions=bypass_agent_permissions
                ),
                timeout=60.0,
            )
            response.raise_for_status()
            return (
                StatusResponse.model_validate(response.json()).status
                == ResponseStatus.SUCCESS
            )
        finally:
            await self._close_client(client)

    async def upload_file(
        self,
        path: str,
        content: bytes,
        *,
        bypass_agent_permissions: bool = False,
    ) -> bool:
        """Upload a file with binary content."""
        client = await self._get_client()
        try:
            body, content_type = self._build_multipart_request(
                fields=[
                    ("path", path),
                    ("bypass_agent_permissions", str(bypass_agent_permissions).lower()),
                ],
                file_fields=[
                    ("file", Path(path).name or "blob", content),
                ],
            )
            headers = self._request_headers(
                bypass_agent_permissions=bypass_agent_permissions
            )
            headers["Content-Type"] = content_type
            response = await client.post(
                f"{self.base_url}/fs/upload_file",
                content=self._AsyncBytesStream(body),
                headers=headers,
                timeout=30.0,
            )
            response.raise_for_status()
            return (
                StatusResponse.model_validate(response.json()).status
                == ResponseStatus.SUCCESS
            )
        finally:
            await self._close_client(client)

    async def upload_files(
        self,
        files: list[tuple[str, bytes]],
        *,
        bypass_agent_permissions: bool = False,
    ) -> bool:
        """Upload multiple files in one request."""
        client = await self._get_client()
        try:
            body, content_type = self._build_multipart_request(
                fields=[
                    *[("paths", path) for path, _content in files],
                    (
                        "bypass_agent_permissions",
                        str(bypass_agent_permissions).lower(),
                    ),
                ],
                file_fields=[
                    ("files", Path(path).name or "blob", content)
                    for path, content in files
                ],
            )
            headers = self._request_headers(
                bypass_agent_permissions=bypass_agent_permissions
            )
            headers["Content-Type"] = content_type
            response = await client.post(
                f"{self.base_url}/fs/upload_files_binary",
                content=self._AsyncBytesStream(body),
                headers=headers,
                timeout=60.0,
            )
            response.raise_for_status()
            return (
                StatusResponse.model_validate(response.json()).status
                == ResponseStatus.SUCCESS
            )
        finally:
            await self._close_client(client)

    async def read_file_binary(
        self, path: str, *, bypass_agent_permissions: bool = False
    ) -> bytes:
        """Read file contents as binary."""
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/fs/read_blob",
                json={
                    "path": path,
                    "bypass_agent_permissions": bypass_agent_permissions,
                },
                headers=self._request_headers(
                    bypass_agent_permissions=bypass_agent_permissions
                ),
                timeout=30.0,
            )
            response.raise_for_status()
            return response.content
        finally:
            await self._close_client(client)

    async def read_files_binary(
        self,
        paths: list[str],
        *,
        bypass_agent_permissions: bool = False,
    ) -> dict[str, bytes]:
        """Read multiple files as binary blobs in one request."""
        normalized_paths = [str(path) for path in paths if str(path)]
        if not normalized_paths:
            return {}

        payload = {
            "paths": normalized_paths,
            "bypass_agent_permissions": bypass_agent_permissions,
        }
        client = await self._get_client()
        try:
            http_response = await client.post(
                f"{self.base_url}/fs/read_files",
                json=payload,
                headers=self._request_headers(
                    bypass_agent_permissions=bypass_agent_permissions
                ),
                timeout=60.0,
            )
            http_response.raise_for_status()
            response = ReadFilesResponse.model_validate(http_response.json())
        finally:
            await self._close_client(client)

        return {
            entry.path: base64.b64decode(entry.content_b64) for entry in response.files
        }

    async def render_cad(
        self,
        script_path: str = "script.py",
        script_content: str | None = None,
        orbit_pitch: float | list[float] = 45.0,
        orbit_yaw: float | list[float] = 45.0,
        rgb: bool | None = None,
        depth: bool | None = None,
        segmentation: bool | None = None,
        payload_path: bool = False,
        rendering_type: PreviewRenderingType | str | None = None,
        bundle_base64: str | None = None,
        smoke_test_mode: bool | None = None,
        agent_role: AgentName | str | None = None,
    ) -> PreviewDesignResponse:
        """Trigger CAD preview via the controller preview workflow when available."""
        payload = {
            "script_path": script_path,
            "orbit_pitch": orbit_pitch,
            "orbit_yaw": orbit_yaw,
            "rgb": rgb,
            "depth": depth,
            "segmentation": segmentation,
            "payload_path": payload_path,
            "rendering_type": rendering_type,
        }
        if script_content is not None:
            payload["script_content"] = script_content

        if smoke_test_mode is not None:
            payload["smoke_test_mode"] = smoke_test_mode

        await self._add_bundle_to_payload(payload, bundle_base64=bundle_base64)

        client = await self._get_client()
        try:
            preview_agent_role = (
                agent_role.value if isinstance(agent_role, AgentName) else agent_role
            ) or self.agent_role
            payload["agent_role"] = preview_agent_role
            if self.controller_url:
                response = await client.post(
                    f"{self.controller_url}/api/script-tools/preview",
                    json=payload,
                    headers=self._request_headers(stage=preview_agent_role),
                    timeout=1000.0,
                )
            else:
                response = await client.post(
                    f"{self.base_url}/benchmark/render_cad",
                    json=payload,
                    headers=self._request_headers(stage=preview_agent_role),
                    timeout=300.0,
                )
            response.raise_for_status()
            return PreviewDesignResponse.model_validate(response.json())
        finally:
            await self._close_client(client)

    async def preview(
        self,
        script_path: str = "script.py",
        script_content: str | None = None,
        orbit_pitch: float | list[float] = 45.0,
        orbit_yaw: float | list[float] = 45.0,
        rgb: bool | None = None,
        depth: bool | None = None,
        segmentation: bool | None = None,
        payload_path: bool = False,
        rendering_type: PreviewRenderingType | str | None = None,
        bundle_base64: str | None = None,
        smoke_test_mode: bool | None = None,
        agent_role: AgentName | str | None = None,
    ) -> PreviewDesignResponse:
        return await self.render_cad(
            script_path=script_path,
            script_content=script_content,
            orbit_pitch=orbit_pitch,
            orbit_yaw=orbit_yaw,
            rgb=rgb,
            depth=depth,
            segmentation=segmentation,
            payload_path=payload_path,
            rendering_type=rendering_type,
            bundle_base64=bundle_base64,
            smoke_test_mode=smoke_test_mode,
            agent_role=agent_role,
        )

    async def edit_file(
        self,
        path: str,
        edits: list[EditOp],
        *,
        bypass_agent_permissions: bool = False,
    ) -> bool:
        """Edit a file with one or more operations."""
        if self._should_use_light_websocket():
            result = await self._light_ws_request(
                "fs_edit",
                {
                    "path": path,
                    "edits": [op.model_dump() for op in edits],
                    "bypass_agent_permissions": bypass_agent_permissions,
                },
            )
            return (
                StatusResponse.model_validate(result or {}).status
                == ResponseStatus.SUCCESS
            )
        client = await self._get_client()
        try:
            json_edits = [op.model_dump() for op in edits]
            response = await client.post(
                f"{self.base_url}/fs/edit",
                json={
                    "path": path,
                    "edits": json_edits,
                    "bypass_agent_permissions": bypass_agent_permissions,
                },
                headers=self._request_headers(
                    bypass_agent_permissions=bypass_agent_permissions
                ),
                timeout=10.0,
            )
            response.raise_for_status()
            return (
                StatusResponse.model_validate(response.json()).status
                == ResponseStatus.SUCCESS
            )
        finally:
            await self._close_client(client)

    async def execute_command(
        self,
        command: str,
        timeout: int = 30,
        *,
        episode_id: str | None = None,
    ) -> ExecuteResponse:
        """Execute a shell command in the session runtime."""
        if self._should_use_light_websocket():
            result = await self._light_ws_request(
                "runtime_execute",
                {
                    "code": command,
                    "timeout": timeout,
                    "episode_id": episode_id,
                },
            )
            return ExecuteResponse.model_validate(result)
        client = await self._get_client()
        try:
            http_timeout = float(timeout) + 5.0
            response = await client.post(
                f"{self.base_url}/runtime/execute",
                json={
                    "code": command,
                    "timeout": timeout,
                    "episode_id": episode_id,
                },
                headers=self._request_headers(stage=self.agent_role),
                timeout=http_timeout,
            )
            response.raise_for_status()
            return ExecuteResponse.model_validate(response.json())
        finally:
            await self._close_client(client)

    async def execute_python(self, code: str, timeout: int = 30) -> ExecuteResponse:
        """Legacy compatibility wrapper around shell-command execution."""
        return await self.execute_command(code, timeout=timeout)

    async def simulate(
        self,
        script_path: str = "script.py",
        script_content: str | None = None,
        backend: SimulatorBackendType | None = None,
        smoke_test_mode: bool | None = None,
        episode_id: str | None = None,
        stream_render_frames: bool = False,
    ) -> BenchmarkToolResponse:
        """Trigger physics simulation via worker."""
        resolved_backend = backend or get_default_simulator_backend()
        role_family = await self._role_family()
        ensure_smoke_test_mode_allowed(
            smoke_test_mode, integration_enabled=settings.is_integration_test
        )
        if self.controller_url:
            payload = {
                "script_path": script_path,
                "agent_role": self.agent_role,
                "backend": resolved_backend,
                "smoke_test_mode": smoke_test_mode,
                "episode_id": episode_id,
                "stream_render_frames": stream_render_frames,
            }
            if script_content is not None:
                raise NotImplementedError(
                    "controller script-tools proxy does not accept script_content"
                )
            parsed = await self._call_controller_script_tool(
                "simulate", payload, stage=self.agent_role
            )
            if parsed is None:
                raise RuntimeError("controller script-tools proxy unavailable")
            await self._sync_handover_artifacts_to_light(parsed)
            return parsed

        client = await self._get_client()
        try:
            payload = {"script_path": script_path, "backend": resolved_backend}
            if script_content is not None:
                payload["script_content"] = script_content
            if smoke_test_mode is not None:
                payload["smoke_test_mode"] = smoke_test_mode
            if episode_id is not None:
                payload["episode_id"] = episode_id
            payload["stream_render_frames"] = stream_render_frames

            await self._add_bundle_to_payload(payload)

            response = await client.post(
                f"{self.heavy_url}/{role_family}/simulate",
                json=payload,
                headers=self._request_headers(stage=self.agent_role),
                timeout=1000.0,
            )
            response.raise_for_status()
            parsed = BenchmarkToolResponse.model_validate(response.json())
            await self._sync_handover_artifacts_to_light(parsed)
            return parsed
        finally:
            await self._close_client(client)

    async def heavy_ready(self) -> bool:
        """Check whether the heavy worker is ready to accept a new job."""
        client = await self._get_client()
        try:
            response = await client.get(
                f"{self.heavy_url}/ready",
                headers=self.headers,
                timeout=5.0,
            )
            return response.status_code == 200
        finally:
            await self._close_client(client)

    async def validate(
        self,
        script_path: str = "script.py",
        script_content: str | None = None,
        bundle_base64: str | None = None,
    ) -> BenchmarkToolResponse:
        """Trigger geometric validation via worker."""
        role_family = await self._role_family()
        if self.controller_url:
            payload = {
                "script_path": script_path,
                "agent_role": self.agent_role,
                "bundle_base64": bundle_base64,
            }
            if script_content is not None:
                raise NotImplementedError(
                    "controller script-tools proxy does not accept script_content"
                )
            parsed = await self._call_controller_script_tool(
                "validate", payload, stage=self.agent_role
            )
            if parsed is None:
                raise RuntimeError("controller script-tools proxy unavailable")
            await self._sync_handover_artifacts_to_light(parsed)
            return parsed

        client = await self._get_client()
        try:
            payload = {"script_path": script_path, "bundle_base64": bundle_base64}
            if script_content is not None:
                payload["script_content"] = script_content

            response = await client.post(
                f"{self.light_url}/{role_family}/validate",
                json=payload,
                headers=self._request_headers(stage=self.agent_role),
                timeout=60.0,
            )
            response.raise_for_status()
            parsed = BenchmarkToolResponse.model_validate(response.json())
            await self._sync_handover_artifacts_to_light(parsed)
            return parsed
        finally:
            await self._close_client(client)

    async def verify(
        self,
        script_path: str = "script.py",
        script_content: str | None = None,
        *,
        backend: SimulatorBackendType | None = None,
        jitter_range: tuple[float, float, float] | None = None,
        num_scenes: int | None = None,
        duration: float | None = None,
        seed: int | None = None,
        smoke_test_mode: bool | None = None,
    ) -> BenchmarkToolResponse:
        """Trigger runtime-randomization verification via worker."""
        resolved_backend = backend or get_default_simulator_backend()
        if smoke_test_mode is not None:
            ensure_smoke_test_mode_allowed(
                smoke_test_mode, integration_enabled=settings.is_integration_test
            )
        payload: dict[str, Any] = {
            "script_path": script_path,
            "agent_role": self.agent_role,
            "backend": resolved_backend,
        }
        if jitter_range is not None:
            payload["jitter_range"] = jitter_range
        if num_scenes is not None:
            payload["num_scenes"] = num_scenes
        if duration is not None:
            payload["duration"] = duration
        if seed is not None:
            payload["seed"] = seed
        if smoke_test_mode is not None:
            payload["smoke_test_mode"] = smoke_test_mode
        else:
            payload["smoke_test_mode"] = _default_smoke_test_mode()
        if script_content is not None:
            raise NotImplementedError(
                "controller script-tools proxy does not accept script_content"
            )

        if self.controller_url:
            parsed = await self._call_controller_script_tool(
                "verify", payload, stage=self.agent_role
            )
            if parsed is None:
                raise RuntimeError("controller script-tools proxy unavailable")
            await self._sync_handover_artifacts_to_light(parsed)
            return parsed

        client = await self._get_client()
        try:
            direct_payload = {
                "script_path": script_path,
                "backend": resolved_backend,
            }
            if jitter_range is not None:
                direct_payload["jitter_range"] = jitter_range
            if num_scenes is not None:
                direct_payload["num_scenes"] = num_scenes
            if duration is not None:
                direct_payload["duration"] = duration
            if seed is not None:
                direct_payload["seed"] = seed
            if smoke_test_mode is not None:
                direct_payload["smoke_test_mode"] = smoke_test_mode
            else:
                direct_payload["smoke_test_mode"] = _default_smoke_test_mode()

            await self._add_bundle_to_payload(direct_payload)

            response = await client.post(
                f"{self.heavy_url}/benchmark/verify",
                json=direct_payload,
                headers=self._request_headers(stage=self.agent_role),
                timeout=1000.0,
            )
            response.raise_for_status()
            parsed = BenchmarkToolResponse.model_validate(response.json())
            await self._sync_handover_artifacts_to_light(parsed)
            return parsed
        finally:
            await self._close_client(client)

    async def analyze(
        self,
        method: ManufacturingMethod,
        script_path: str = "script.py",
        script_content: str | None = None,
        quantity: int = 1,
    ) -> WorkbenchResult:
        """Trigger manufacturing analysis via worker."""
        client = await self._get_client()
        try:
            payload = {
                "script_path": script_path,
                "method": method,
                "quantity": quantity,
            }
            if script_content is not None:
                payload["script_content"] = script_content

            await self._add_bundle_to_payload(payload)

            response = await client.post(
                f"{self.heavy_url}/benchmark/analyze",
                json=payload,
                headers=self._request_headers(stage=self.agent_role),
                timeout=60.0,
            )
            response.raise_for_status()
            return WorkbenchResult.model_validate(response.json())
        finally:
            await self._close_client(client)

    async def submit(
        self,
        script_path: str = "script.py",
        script_content: str | None = None,
        bundle_base64: str | None = None,
        reviewer_stage: AgentName | None = None,
        episode_id: str | None = None,
    ) -> BenchmarkToolResponse:
        """Trigger handover to review via worker."""
        effective_stage = reviewer_stage or self._default_reviewer_stage(
            self.agent_role
        )
        role_family = await self._role_family()
        if self.controller_url:
            payload = {
                "script_path": script_path,
                "agent_role": self.agent_role,
                "reviewer_stage": effective_stage,
                "episode_id": episode_id,
                "bundle_base64": bundle_base64,
            }
            if script_content is not None:
                raise NotImplementedError(
                    "controller script-tools proxy does not accept script_content"
                )
            parsed = await self._call_controller_script_tool(
                "submit", payload, stage=effective_stage or self.agent_role
            )
            if parsed is None:
                raise RuntimeError("controller script-tools proxy unavailable")
            await self._sync_handover_artifacts_to_light(parsed)
            return parsed

        client = await self._get_client()
        try:
            payload = {"script_path": script_path, "bundle_base64": bundle_base64}
            if script_content is not None:
                payload["script_content"] = script_content
            if effective_stage:
                payload["reviewer_stage"] = effective_stage
            if episode_id is not None:
                payload["episode_id"] = episode_id

            await self._add_bundle_to_payload(payload)

            response = await client.post(
                f"{self.heavy_url}/{role_family}/submit",
                json=payload,
                headers=self._request_headers(
                    stage=effective_stage or self.agent_role,
                    reviewer_stage=effective_stage,
                ),
                timeout=60.0,
            )
            response.raise_for_status()
            parsed = BenchmarkToolResponse.model_validate(response.json())
            await self._sync_handover_artifacts_to_light(parsed)
            return parsed
        finally:
            await self._close_client(client)

    async def _role_family(self) -> str:
        """Resolve the active role family from the current-role manifest."""
        manifest_content = await self.read_file_optional(
            ".manifests/current_role.json",
            bypass_agent_permissions=True,
        )
        if manifest_content is None:
            raise FileNotFoundError(
                "Missing current-role manifest: .manifests/current_role.json"
            )

        try:
            agent_name = current_role_agent_name_from_text(manifest_content)
        except Exception as exc:
            raise ValueError(
                "Invalid current-role manifest: .manifests/current_role.json"
            ) from exc

        role_family = role_family_for_agent(agent_name)
        if role_family is None:
            raise ValueError(f"Unsupported current-role manifest: {agent_name.value}")
        return role_family

    async def validate_benchmark(
        self,
        script_path: str = "script.py",
        script_content: str | None = None,
        bundle_base64: str | None = None,
    ) -> BenchmarkToolResponse:
        if await self._role_family() != "benchmark":
            raise ValueError("Current worker role is not benchmark-side")
        return await self.validate(
            script_path=script_path,
            script_content=script_content,
            bundle_base64=bundle_base64,
        )

    async def validate_engineering(
        self,
        script_path: str = "script.py",
        script_content: str | None = None,
        bundle_base64: str | None = None,
    ) -> BenchmarkToolResponse:
        if await self._role_family() != "engineering":
            raise ValueError("Current worker role is not engineering-side")
        return await self.validate(
            script_path=script_path,
            script_content=script_content,
            bundle_base64=bundle_base64,
        )

    async def simulate_benchmark(
        self,
        script_path: str = "script.py",
        script_content: str | None = None,
        backend: SimulatorBackendType | None = None,
        smoke_test_mode: bool | None = None,
        episode_id: str | None = None,
        stream_render_frames: bool = False,
    ) -> BenchmarkToolResponse:
        if await self._role_family() != "benchmark":
            raise ValueError("Current worker role is not benchmark-side")
        return await self.simulate(
            script_path=script_path,
            script_content=script_content,
            backend=backend,
            smoke_test_mode=smoke_test_mode,
            episode_id=episode_id,
            stream_render_frames=stream_render_frames,
        )

    async def simulate_engineering(
        self,
        script_path: str = "script.py",
        script_content: str | None = None,
        backend: SimulatorBackendType | None = None,
        smoke_test_mode: bool | None = None,
        episode_id: str | None = None,
        stream_render_frames: bool = False,
    ) -> BenchmarkToolResponse:
        if await self._role_family() != "engineering":
            raise ValueError("Current worker role is not engineering-side")
        return await self.simulate(
            script_path=script_path,
            script_content=script_content,
            backend=backend,
            smoke_test_mode=smoke_test_mode,
            episode_id=episode_id,
            stream_render_frames=stream_render_frames,
        )

    async def submit_benchmark_for_review(
        self,
        script_path: str = "script.py",
        script_content: str | None = None,
        bundle_base64: str | None = None,
        reviewer_stage: AgentName | None = None,
        episode_id: str | None = None,
    ) -> BenchmarkToolResponse:
        if await self._role_family() != "benchmark":
            raise ValueError("Current worker role is not benchmark-side")
        return await self.submit(
            script_path=script_path,
            script_content=script_content,
            bundle_base64=bundle_base64,
            reviewer_stage=reviewer_stage,
            episode_id=episode_id,
        )

    async def submit_solution_for_review(
        self,
        script_path: str = "script.py",
        script_content: str | None = None,
        bundle_base64: str | None = None,
        reviewer_stage: AgentName | None = None,
        episode_id: str | None = None,
    ) -> BenchmarkToolResponse:
        if await self._role_family() != "engineering":
            raise ValueError("Current worker role is not engineering-side")
        return await self.submit(
            script_path=script_path,
            script_content=script_content,
            bundle_base64=bundle_base64,
            reviewer_stage=reviewer_stage,
            episode_id=episode_id,
        )

    async def get_health(self) -> HealthResponse:
        """Check the health of the worker service."""
        client = await self._get_client()
        try:
            response = await client.get(f"{self.base_url}/health", timeout=5.0)
            response.raise_for_status()
            return HealthResponse.model_validate(response.json())
        finally:
            await self._close_client(client)

    async def git_init(self) -> bool:
        """Initialize a git repository in the workspace."""
        if self._should_use_light_websocket():
            result = await self._light_ws_request("git_init", {})
            return (
                StatusResponse.model_validate(result or {}).status
                == ResponseStatus.SUCCESS
            )
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/git/init",
                headers=self._request_headers(stage=self.agent_role),
                timeout=10.0,
            )
            response.raise_for_status()
            return (
                StatusResponse.model_validate(response.json()).status
                == ResponseStatus.SUCCESS
            )
        finally:
            await self._close_client(client)

    async def git_commit(self, message: str) -> GitCommitResponse:
        """Commit changes and sync to S3."""
        if self._should_use_light_websocket():
            result = await self._light_ws_request("git_commit", {"message": message})
            return GitCommitResponse.model_validate(result)
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/git/commit",
                json={"message": message},
                headers=self._request_headers(stage=self.agent_role),
                timeout=30.0,
            )
            response.raise_for_status()
            return GitCommitResponse.model_validate(response.json())
        finally:
            await self._close_client(client)

    async def git_status(self) -> GitStatusResponse:
        """Get repository status."""
        if self._should_use_light_websocket():
            result = await self._light_ws_request("git_status", {})
            return GitStatusResponse.model_validate(result)
        client = await self._get_client()
        try:
            response = await client.get(
                f"{self.base_url}/git/status",
                headers=self._request_headers(stage=self.agent_role),
                timeout=10.0,
            )
            response.raise_for_status()
            return GitStatusResponse.model_validate(response.json())
        finally:
            await self._close_client(client)

    async def git_resolve(
        self, file_path: str, strategy: Literal["ours", "theirs"]
    ) -> bool:
        """Resolve a merge conflict."""
        if self._should_use_light_websocket():
            result = await self._light_ws_request(
                "git_resolve",
                {"file_path": file_path, "strategy": strategy},
            )
            return (
                StatusResponse.model_validate(result or {}).status
                == ResponseStatus.SUCCESS
            )
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/git/resolve",
                json={"file_path": file_path, "strategy": strategy},
                headers=self._request_headers(stage=self.agent_role),
                timeout=10.0,
            )
            response.raise_for_status()
            return (
                StatusResponse.model_validate(response.json()).status
                == ResponseStatus.SUCCESS
            )
        finally:
            await self._close_client(client)

    async def git_merge_abort(self) -> bool:
        """Abort a merge."""
        if self._should_use_light_websocket():
            result = await self._light_ws_request("git_merge_abort", {})
            return (
                StatusResponse.model_validate(result or {}).status
                == ResponseStatus.SUCCESS
            )
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/git/merge/abort",
                headers=self.headers,
                timeout=10.0,
            )
            response.raise_for_status()
            return (
                StatusResponse.model_validate(response.json()).status
                == ResponseStatus.SUCCESS
            )
        finally:
            await self._close_client(client)

    async def git_merge_complete(self, message: str | None = None) -> GitCommitResponse:
        """Complete a merge."""
        if self._should_use_light_websocket():
            result = await self._light_ws_request(
                "git_merge_complete", {"message": message}
            )
            return GitCommitResponse.model_validate(result)
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/git/merge/complete",
                json={"message": message},
                headers=self.headers,
                timeout=30.0,
            )
            response.raise_for_status()
            return GitCommitResponse.model_validate(response.json())
        finally:
            await self._close_client(client)
