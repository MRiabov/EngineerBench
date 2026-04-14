import asyncio
import base64
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.encoders import jsonable_encoder

from shared.enums import FailureReason, ResponseStatus
from shared.models.simulation import SimulationFailure
from shared.observability.storage import S3Client, S3Config
from shared.rendering import (
    materialize_preview_response,
    render_preview,
    select_single_preview_render_subdir,
)
from shared.workers.bundling import extract_bundle_base64
from shared.workers.filesystem.router import (
    WritePermissionError,
    create_filesystem_router,
)
from shared.workers.persistence import collect_and_cleanup_events
from shared.workers.schema import (
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    DeleteFileRequest,
    EditFileRequest,
    ExecuteRequest,
    ExecuteResponse,
    ExistsResponse,
    FsFileEntry,
    GitCommitRequest,
    GitCommitResponse,
    GitMergeRequest,
    GitResolveRequest,
    GitStatusResponse,
    GrepMatch,
    GrepRequest,
    InspectTopologyRequest,
    InspectTopologyResponse,
    LintRequest,
    LintResponse,
    ListFilesRequest,
    PreviewDesignRequest,
    PreviewDesignResponse,
    PreviewRenderingType,
    ReadFileBlobEntry,
    ReadFileRequest,
    ReadFileResponse,
    ReadFilesRequest,
    ReadFilesResponse,
    RenderBundleIndexEntry,
    RenderBundlePointPickRequest,
    RenderBundlePointPickResult,
    RenderBundleQueryRequest,
    RenderBundleQueryResult,
    SimulationArtifacts,
    StatusResponse,
    UploadFilesFromObjectStoreRequest,
    UploadFilesRequest,
    WorkerLightRpcError,
    WorkerLightRpcRequest,
    WorkerLightRpcResponse,
    WriteFileRequest,
)
from shared.workers.validation_artifacts import build_validation_response
from worker_heavy.runtime.simulation_runner import run_validation_in_isolated_process
from worker_light.runtime.executor import RuntimeConfig, run_command_async
from worker_light.utils.assets import get_media_type, validate_asset_source
from worker_light.utils.git import (
    abort_merge,
    commit_all,
    complete_merge,
    get_repo_status,
    init_workspace_repo,
    resolve_conflict_ours,
    resolve_conflict_theirs,
)
from worker_light.utils.render_query import (
    list_render_bundles,
    pick_preview_pixel,
    pick_preview_pixels,
    query_render_bundle,
)

logger = structlog.get_logger(__name__)
light_router = APIRouter()


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


@contextmanager
def bundle_context(bundle_base64: str | None, default_root: Path):
    """Context manager to optionally extract a workspace bundle."""
    if not bundle_base64:
        yield default_root
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        try:
            extract_bundle_base64(bundle_base64, tmp_root)
            yield tmp_root
        except Exception as e:
            logger.warning("bundle_extraction_failed", error=str(e))
            raise RuntimeError(f"Failed to extract bundle: {e}") from e


def _rewrite_manifest_preview_paths(
    manifest_json: str, source_prefix: str, target_prefix: str
) -> str:
    def _rewrite(value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(source_prefix, target_prefix)
        if isinstance(value, list):
            return [_rewrite(item) for item in value]
        if isinstance(value, dict):
            return {
                (
                    key.replace(source_prefix, target_prefix)
                    if isinstance(key, str)
                    else key
                ): _rewrite(item)
                for key, item in value.items()
            }
        return value

    return json.dumps(_rewrite(json.loads(manifest_json)), indent=2)


def _bypass_enabled(requested: bool, system_header: str | None) -> bool:
    return bool(requested and system_header == "1")


def _sanitize_workspace_alias(text: str, session_dir: Path) -> str:
    """Hide host session roots from tool-visible output while preserving the legacy alias."""
    if not text:
        return text
    session_root = str(session_dir.resolve())
    return text.replace(session_root, "/workspace")


def _is_host_session_absolute_path(path: str, session_dir: Path) -> bool:
    """Detect leaked host paths that point at the current session root."""
    normalized = str(path).strip()
    if not normalized.startswith("/"):
        return False
    session_root = str(session_dir.resolve())
    return normalized == session_root or normalized.startswith(f"{session_root}/")


def _read_file_bytes(fs_router, path: str, *, bypass_agent_permissions: bool) -> bytes:
    if bypass_agent_permissions:
        local_path = fs_router.local_backend._resolve(path)
        if not local_path.exists():
            raise FileNotFoundError
        return local_path.read_bytes()
    return fs_router.read(path)


def _read_file_blob_entries(
    fs_router, paths: list[str], *, bypass_agent_permissions: bool
) -> ReadFilesResponse:
    files: list[ReadFileBlobEntry] = []
    missing_paths: list[str] = []
    for path in paths:
        try:
            content = _read_file_bytes(
                fs_router, path, bypass_agent_permissions=bypass_agent_permissions
            )
        except FileNotFoundError:
            missing_paths.append(path)
            continue
        files.append(
            ReadFileBlobEntry(
                path=path,
                content_b64=base64.b64encode(content).decode("ascii"),
            )
        )
    return ReadFilesResponse(files=files, missing_paths=missing_paths)


async def get_router(x_session_id: str = Header(...)):
    """Dependency to create a filesystem router for the current session."""
    try:
        from worker_light.config import settings

        return create_filesystem_router(
            session_id=x_session_id, base_dir=settings.sessions_dir
        )
    except Exception as e:
        logger.warning("router_creation_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to initialize filesystem")


@light_router.post("/topology/inspect", response_model=InspectTopologyResponse)
async def api_inspect_topology(
    request: InspectTopologyRequest,
    fs_router=Depends(get_router),
):
    """Inspect topological features of the component."""
    try:
        from worker_light.tools.topology import inspect_topology

        # Resolve script path
        try:
            local_p = fs_router.local_backend._resolve(request.script_path)
        except Exception:
            local_p = Path(request.script_path)

        props = inspect_topology(target_id=request.target_id, script_path=str(local_p))
        return InspectTopologyResponse(success=True, properties=props)
    except Exception as e:
        logger.warning("api_inspect_topology_failed", error=str(e))
        return InspectTopologyResponse(success=False, message=str(e))


@light_router.post(
    "/benchmark/render_cad",
    response_model=PreviewDesignResponse,
    response_model_exclude_none=True,
)
@light_router.post(
    "/benchmark/preview",
    response_model=PreviewDesignResponse,
    response_model_exclude_none=True,
    deprecated=True,
)
async def api_preview(
    request: PreviewDesignRequest,
    fs_router=Depends(get_router),
    x_session_id: str = Header(...),
    x_agent_role: str | None = Header(default=None),
):
    """Forward a preview request to the renderer worker and persist the result."""
    try:
        workspace_root = fs_router.local_backend.root
        logger.info(
            "worker_light_preview_started",
            session_id=x_session_id,
            script_path=request.script_path,
            agent_role=x_agent_role,
            rendering_type=(
                request.rendering_type.value if request.rendering_type else None
            ),
            rgb=request.rgb,
            depth=request.depth,
            segmentation=request.segmentation,
            payload_path=request.payload_path,
            orbit_pitch=request.orbit_pitch,
            orbit_yaw=request.orbit_yaw,
        )
        bundle_base64 = (
            request.bundle_base64
            if request.bundle_base64 is not None
            else base64.b64encode(_bundle_session_bytes(fs_router)).decode("utf-8")
        )
        response = await asyncio.to_thread(
            render_preview,
            bundle_base64=bundle_base64,
            script_path=request.script_path,
            orbit_pitch=request.orbit_pitch,
            orbit_yaw=request.orbit_yaw,
            rgb=request.rgb,
            depth=request.depth,
            segmentation=request.segmentation,
            payload_path=request.payload_path,
            rendering_type=request.rendering_type,
            session_id=x_session_id,
            agent_role=x_agent_role,
            script_content=request.script_content,
            smoke_test_mode=request.smoke_test_mode,
        )
        if not response.success:
            raise RuntimeError(response.message or "preview request failed")

        source_preview_prefix = None
        for candidate in (response.artifact_path, response.image_path):
            if not candidate:
                continue
            candidate_path = Path(candidate)
            if candidate_path.parent == Path():
                continue
            source_preview_prefix = str(candidate_path.parent)
            break

        preview_renders_dir = (
            workspace_root
            / "renders"
            / select_single_preview_render_subdir(
                workspace_root, agent_role=x_agent_role
            )
        )
        image_path = materialize_preview_response(response, preview_renders_dir)
        if image_path is None:
            raise RuntimeError("renderer returned no preview image")

        artifact_path = str(image_path.relative_to(workspace_root))
        target_preview_prefix = str(Path(artifact_path).parent)
        saved_render_dir = str(Path(artifact_path).parent).replace("\\", "/")
        manifest_path = str(
            Path(artifact_path).parent / "render_manifest.json"
        ).replace("\\", "/")
        preview_message = (
            "Preview generated successfully. "
            f"Saved renders to {saved_render_dir}. "
            f"Manifest: {manifest_path}."
        )
        if (
            preview_renders_dir.name != "current-episode"
            and source_preview_prefix
            and response.render_manifest_json
            and source_preview_prefix != target_preview_prefix
        ):
            response.render_manifest_json = _rewrite_manifest_preview_paths(
                response.render_manifest_json,
                source_preview_prefix,
                target_preview_prefix,
            )
            _write_text_atomic(
                preview_renders_dir / "render_manifest.json",
                response.render_manifest_json,
            )
            _write_text_atomic(
                preview_renders_dir.parent / "render_manifest.json",
                response.render_manifest_json,
            )

        events = _collect_events(fs_router)
        logger.info(
            "worker_light_preview_finished",
            session_id=x_session_id,
            artifact_path=artifact_path,
            manifest_path=manifest_path,
            rendering_type=(
                request.rendering_type.value if request.rendering_type else None
            ),
            view_count=response.view_count,
        )
        return PreviewDesignResponse(
            success=True,
            status_text="Preview generated successfully",
            message=preview_message,
            job_id=response.job_id,
            queued=response.queued,
            view_count=response.view_count,
            view_specs=response.view_specs,
            artifact_path=artifact_path,
            manifest_path=manifest_path,
            rendering_type=response.rendering_type,
            pitch=request.orbit_pitch
            if isinstance(request.orbit_pitch, float)
            else None,
            yaw=request.orbit_yaw if isinstance(request.orbit_yaw, float) else None,
            image_path=artifact_path,
            image_bytes_base64=response.image_bytes_base64,
            render_blobs_base64=response.render_blobs_base64,
            object_store_keys=response.object_store_keys,
            render_manifest_json=response.render_manifest_json,
            events=events,
        )
    except Exception as exc:
        logger.warning("api_preview_failed", error=str(exc))
        return PreviewDesignResponse(
            success=False,
            status_text="Preview generation failed",
            message=str(exc),
            rendering_type=(request.rendering_type or PreviewRenderingType.RGB),
            pitch=request.orbit_pitch
            if isinstance(request.orbit_pitch, float)
            else None,
            yaw=request.orbit_yaw if isinstance(request.orbit_yaw, float) else None,
        )


@light_router.post("/benchmark/validate", response_model=BenchmarkToolResponse)
@light_router.post("/engineering/validate", response_model=BenchmarkToolResponse)
async def api_validate(
    request: BenchmarkToolRequest,
    x_session_id: str = Header(...),
    fs_router=Depends(get_router),
):
    """Geometric validity check in isolated session."""
    try:
        with bundle_context(
            request.bundle_base64, fs_router.local_backend.root
        ) as root:
            is_valid, message = await run_validation_in_isolated_process(
                script_path=(
                    str(root / request.script_path)
                    if request.bundle_base64
                    else fs_router.local_backend._resolve(request.script_path)
                ),
                session_root=root,
                script_content=request.script_content,
                output_dir=root,
                smoke_test_mode=request.smoke_test_mode,
                session_id=x_session_id,
                particle_budget=request.particle_budget,
            )

            return build_validation_response(
                root=root,
                is_valid=is_valid,
                message=message,
                script_path=request.script_path,
                session_id=x_session_id,
            )
    except Exception as exc:
        logger.warning("api_benchmark_validate_failed", error=str(exc))
        return BenchmarkToolResponse(
            success=False,
            message=str(exc),
            artifacts=SimulationArtifacts(
                failure=SimulationFailure(
                    reason=FailureReason.VALIDATION_FAILED,
                    detail=str(exc),
                )
            ),
        )


def _collect_events(fs_router) -> list[dict[str, Any]]:
    """Read and delete events.jsonl from the workspace."""
    return collect_and_cleanup_events(fs_router.local_backend.root)


def _bundle_session_bytes(fs_router) -> bytes:
    import io
    import tarfile

    root = fs_router.local_backend.root

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        # Exclude internal state and large asset caches, but keep renders because
        # the reviewer handoff depends on the preview/simulation media.
        exclude = {".git", "__pycache__", "assets"}

        for path in root.rglob("*"):
            rel_p = path.relative_to(root)
            if any(part in exclude for part in rel_p.parts):
                continue
            if path.is_file():
                tar.add(path, arcname=str(rel_p))

    return buf.getvalue()


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


def _upload_workspace_files(
    fs_router,
    files: list[tuple[str, bytes]],
    *,
    bypass_agent_permissions: bool,
):
    """Write a batch of workspace files through the owning backend."""
    if bypass_agent_permissions:
        return fs_router.local_backend.upload_files(files)
    return fs_router.upload_files(files)


def _raise_first_upload_error(responses) -> None:
    first_error = next(
        (response.error for response in responses if response.error), None
    )
    if first_error is not None:
        raise HTTPException(status_code=403, detail=first_error)


def _download_object_store_files(
    fs_router,
    files: list[tuple[str, str]],
    *,
    bypass_agent_permissions: bool,
):
    storage_client = _storage_client_from_env()
    if storage_client is None:
        raise HTTPException(
            status_code=503,
            detail="Object-store upload requested but S3 credentials are unavailable",
        )

    staged_files: list[tuple[str, bytes]] = []
    for path, object_key in files:
        with tempfile.NamedTemporaryFile(suffix=Path(path).suffix) as tmp:
            storage_client.download_file(object_key, tmp.name)
            staged_files.append((path, Path(tmp.name).read_bytes()))

    return _upload_workspace_files(
        fs_router,
        staged_files,
        bypass_agent_permissions=bypass_agent_permissions,
    )


async def _handle_light_rpc_action(
    action: str,
    payload: dict[str, Any],
    fs_router,
    *,
    x_session_id: str,
) -> Any:
    if action == "fs_ls":
        if payload.get("bypass_agent_permissions", False):
            return fs_router.local_backend.ls(payload.get("path", "/"))
        return fs_router.ls(payload.get("path", "/"))

    if action == "fs_exists":
        if payload.get("bypass_agent_permissions", False):
            return {"exists": fs_router.local_backend.exists(payload.get("path", "/"))}
        return {"exists": fs_router.exists(payload.get("path", "/"))}

    if action == "fs_read":
        if payload.get("bypass_agent_permissions", False):
            local_path = fs_router.local_backend._resolve(payload["path"])
            if not local_path.exists():
                raise FileNotFoundError
            return {"content": local_path.read_text(encoding="utf-8")}
        return {"content": fs_router.read(payload["path"]).decode("utf-8")}

    if action == "fs_read_blob":
        if payload.get("bypass_agent_permissions", False):
            content = _read_file_bytes(
                fs_router,
                payload["path"],
                bypass_agent_permissions=True,
            )
        else:
            content = fs_router.read(payload["path"])
        return {"content_b64": base64.b64encode(content).decode("ascii")}

    if action == "fs_read_files":
        request = ReadFilesRequest.model_validate(payload)
        return _read_file_blob_entries(
            fs_router,
            request.paths,
            bypass_agent_permissions=request.bypass_agent_permissions,
        )

    if action == "fs_write":
        if payload.get("bypass_agent_permissions", False):
            result = fs_router.local_backend.write(
                payload["path"],
                payload["content"],
                overwrite=payload.get("overwrite", False),
            )
            if result.error:
                raise HTTPException(status_code=500, detail=result.error)
            return {"status": ResponseStatus.SUCCESS}
        fs_router.write(
            payload["path"],
            payload["content"],
            overwrite=payload.get("overwrite", False),
        )
        return {"status": ResponseStatus.SUCCESS}

    if action == "fs_edit":
        edits = payload.get("edits") or []
        if payload.get("bypass_agent_permissions", False):
            session_dir = fs_router.local_backend.root
            if _is_host_session_absolute_path(payload["path"], session_dir):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Host session absolute paths are not allowed. "
                        "Use workspace-relative paths like 'script.py'. "
                        "The '/workspace' alias is legacy compatibility only."
                    ),
                )

            if not fs_router.local_backend.exists(payload["path"]):
                raise HTTPException(status_code=404, detail="File not found")
            for edit in edits:
                result = fs_router.local_backend.edit(
                    payload["path"], edit["old_string"], edit["new_string"]
                )
                if result.error or (result.occurrences or 0) <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Content not found for replacement: "
                            f"{edit['old_string'][:50]}..."
                        ),
                    )
            return {"status": ResponseStatus.SUCCESS}

        if not fs_router.exists(payload["path"]):
            raise HTTPException(status_code=404, detail="File not found")
        for edit in edits:
            success = fs_router.edit(
                payload["path"], edit["old_string"], edit["new_string"]
            )
            if not success:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Content not found for replacement: "
                        f"{edit['old_string'][:50]}..."
                    ),
                )
        return {"status": ResponseStatus.SUCCESS}

    if action == "fs_upload_file":
        content = base64.b64decode(payload["content_b64"])
        responses = _upload_workspace_files(
            fs_router,
            [(payload["path"], content)],
            bypass_agent_permissions=payload.get("bypass_agent_permissions", False),
        )
        _raise_first_upload_error(responses)
        return {"status": ResponseStatus.SUCCESS}

    if action == "fs_upload_files":
        request = UploadFilesRequest.model_validate(payload)
        files = [
            (entry.path, base64.b64decode(entry.content_b64)) for entry in request.files
        ]
        responses = _upload_workspace_files(
            fs_router,
            files,
            bypass_agent_permissions=request.bypass_agent_permissions,
        )
        _raise_first_upload_error(responses)
        return {"status": ResponseStatus.SUCCESS}

    if action == "fs_upload_files_object_store":
        request = UploadFilesFromObjectStoreRequest.model_validate(payload)
        responses = _download_object_store_files(
            fs_router,
            [(entry.path, entry.object_store_key) for entry in request.files],
            bypass_agent_permissions=request.bypass_agent_permissions,
        )
        _raise_first_upload_error(responses)
        return {"status": ResponseStatus.SUCCESS}

    if action == "fs_delete":
        if payload.get("bypass_agent_permissions", False):
            fs_router.local_backend.delete(payload["path"])
            return {"status": ResponseStatus.SUCCESS}
        fs_router.delete(payload["path"])
        return {"status": ResponseStatus.SUCCESS}

    if action == "fs_grep":
        if payload.get("bypass_agent_permissions", False):
            matches = fs_router.local_backend.grep_raw(
                pattern=payload["pattern"],
                path=payload.get("path"),
                glob=payload.get("glob"),
            )
        else:
            matches = fs_router.grep_raw(
                pattern=payload["pattern"],
                path=payload.get("path"),
                glob=payload.get("glob"),
            )
        if isinstance(matches, str):
            raise HTTPException(status_code=400, detail=matches)
        return matches

    if action == "fs_bundle":
        return {
            "content_b64": base64.b64encode(_bundle_session_bytes(fs_router)).decode(
                "ascii"
            )
        }

    if action == "git_init":
        from worker_light.utils.git import init_workspace_repo

        init_workspace_repo(fs_router.local_backend.root)
        return {"status": ResponseStatus.SUCCESS}

    if action == "git_commit":
        from worker_light.utils.git import commit_all

        commit_hash = commit_all(fs_router.local_backend.root, payload["message"])
        if commit_hash:
            return {
                "success": True,
                "commit_hash": commit_hash,
                "message": "Commit successful",
            }
        return {
            "success": True,
            "commit_hash": None,
            "message": "No changes to commit",
        }

    if action == "git_status":
        from worker_light.utils.git import get_repo_status

        return get_repo_status(fs_router.local_backend.root)

    if action == "git_resolve":
        from worker_light.utils.git import (
            resolve_conflict_ours,
            resolve_conflict_theirs,
        )

        if payload["strategy"] == "ours":
            success = resolve_conflict_ours(
                fs_router.local_backend.root, payload["file_path"]
            )
        else:
            success = resolve_conflict_theirs(
                fs_router.local_backend.root, payload["file_path"]
            )

        if success:
            return {"status": ResponseStatus.SUCCESS}
        raise HTTPException(status_code=500, detail="Failed to resolve conflict")

    if action == "git_merge_abort":
        from worker_light.utils.git import abort_merge

        if abort_merge(fs_router.local_backend.root):
            return {"status": ResponseStatus.SUCCESS}
        raise HTTPException(status_code=500, detail="Failed to abort merge")

    if action == "git_merge_complete":
        from worker_light.utils.git import complete_merge

        commit_hash = complete_merge(
            fs_router.local_backend.root,
            payload.get("message"),
            session_id=x_session_id,
        )
        if commit_hash:
            return {
                "success": True,
                "commit_hash": commit_hash,
                "message": "Merge completed successfully",
            }
        return {
            "success": False,
            "commit_hash": None,
            "message": "Failed to complete merge (conflicts might remain)",
        }

    if action == "runtime_execute":
        session_dir = fs_router.local_backend.root

        config = RuntimeConfig(
            timeout_seconds=payload["timeout"],
            working_directory=str(session_dir),
        )
        from worker_light.config import settings

        result = await run_command_async(
            command=payload["code"],
            env={
                "SESSION_ID": x_session_id,
                "EPISODE_ID": payload.get("episode_id") or x_session_id,
                "WORKER_HEAVY_URL": settings.worker_heavy_url,
                "CONTROLLER_URL": "",
            },
            config=config,
            session_id=x_session_id,
        )
        events = _collect_events(fs_router)

        return {
            "stdout": _sanitize_workspace_alias(result.stdout, session_dir),
            "stderr": _sanitize_workspace_alias(result.stderr, session_dir),
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "events": events,
        }

    if action == "topology_inspect":
        from worker_light.tools.topology import inspect_topology

        try:
            local_p = fs_router.local_backend._resolve(payload["script_path"])
        except Exception:
            local_p = Path(payload["script_path"])

        props = inspect_topology(
            target_id=payload["target_id"], script_path=str(local_p)
        )
        return {"success": True, "properties": props}

    raise HTTPException(
        status_code=400, detail=f"Unsupported worker RPC action: {action}"
    )


@light_router.websocket("/ws")
async def worker_light_websocket(websocket: WebSocket):
    session_id = websocket.headers.get("x-session-id")
    if not session_id:
        await websocket.accept()
        await websocket.send_json(
            {
                "request_id": "",
                "ok": False,
                "error": {
                    "message": "Missing X-Session-ID header",
                    "status_code": 1008,
                    "error_type": "WebSocketPolicyViolation",
                },
            }
        )
        await websocket.close(code=1008)
        return

    try:
        fs_router = await get_router(x_session_id=session_id)
    except HTTPException as exc:
        await websocket.accept()
        await websocket.send_json(
            {
                "request_id": "",
                "ok": False,
                "error": {
                    "message": str(exc.detail),
                    "status_code": exc.status_code,
                    "error_type": exc.__class__.__name__,
                },
            }
        )
        await websocket.close(code=1008)
        return

    await websocket.accept()

    try:
        while True:
            raw_message = await websocket.receive_text()
            request = WorkerLightRpcRequest.model_validate_json(raw_message)
            try:
                result = await _handle_light_rpc_action(
                    request.action,
                    request.payload,
                    fs_router,
                    x_session_id=session_id,
                )
                response = WorkerLightRpcResponse(
                    request_id=request.request_id,
                    ok=True,
                    result=jsonable_encoder(result),
                )
            except FileNotFoundError:
                response = WorkerLightRpcResponse(
                    request_id=request.request_id,
                    ok=False,
                    error=WorkerLightRpcError(
                        message="File not found",
                        status_code=404,
                        error_type="FileNotFoundError",
                    ),
                )
            except HTTPException as exc:
                response = WorkerLightRpcResponse(
                    request_id=request.request_id,
                    ok=False,
                    error=WorkerLightRpcError(
                        message=str(exc.detail),
                        status_code=exc.status_code,
                        error_type=exc.__class__.__name__,
                    ),
                )
            except Exception as exc:
                response = WorkerLightRpcResponse(
                    request_id=request.request_id,
                    ok=False,
                    error=WorkerLightRpcError(
                        message=str(exc),
                        status_code=500,
                        error_type=exc.__class__.__name__,
                    ),
                )

            await websocket.send_text(response.model_dump_json())
    except WebSocketDisconnect:
        return
    except Exception as exc:
        logger.warning("worker_light_websocket_failed", error=str(exc))
        raise


@light_router.post("/fs/ls", response_model=list[FsFileEntry])
async def list_files(
    request: ListFilesRequest,
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """List contents of a directory."""
    try:
        if _bypass_enabled(request.bypass_agent_permissions, x_system_fs_bypass):
            return fs_router.local_backend.ls(request.path)
        return fs_router.ls(request.path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.warning("api_ls_failed", path=request.path, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/fs/exists", response_model=ExistsResponse)
async def file_exists(
    request: ReadFileRequest,
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """Check if a file or directory exists."""
    try:
        if _bypass_enabled(request.bypass_agent_permissions, x_system_fs_bypass):
            return ExistsResponse(exists=fs_router.local_backend.exists(request.path))
        exists = fs_router.exists(request.path)
        return ExistsResponse(exists=exists)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.warning("api_exists_failed", path=request.path, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/fs/read", response_model=ReadFileResponse)
async def read_file(
    request: ReadFileRequest,
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """Read file contents."""
    try:
        if _bypass_enabled(request.bypass_agent_permissions, x_system_fs_bypass):
            local_path = fs_router.local_backend._resolve(request.path)
            if not local_path.exists():
                raise FileNotFoundError
            return ReadFileResponse(content=local_path.read_text(encoding="utf-8"))
        content = fs_router.read(request.path)
        return ReadFileResponse(content=content.decode("utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.warning("api_read_failed", path=request.path, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/fs/write", response_model=StatusResponse)
async def write_file(
    request: WriteFileRequest,
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """Write content to a file."""
    try:
        if _bypass_enabled(request.bypass_agent_permissions, x_system_fs_bypass):
            result = fs_router.local_backend.write(
                request.path, request.content, overwrite=request.overwrite
            )
            if result.error:
                raise HTTPException(status_code=500, detail=result.error)
            return StatusResponse(status=ResponseStatus.SUCCESS)
        fs_router.write(request.path, request.content, overwrite=request.overwrite)
        return StatusResponse(status=ResponseStatus.SUCCESS)
    except (WritePermissionError, PermissionError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.warning("api_write_failed", path=request.path, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/fs/edit", response_model=StatusResponse)
async def edit_file(
    request: EditFileRequest,
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """Edit a file with one or more operations."""
    try:
        session_dir = fs_router.local_backend.root
        if _is_host_session_absolute_path(request.path, session_dir):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Host session absolute paths are not allowed. "
                    "Use workspace-relative paths like 'script.py' or the "
                    "'/workspace/script.py' alias."
                ),
            )

        if _bypass_enabled(request.bypass_agent_permissions, x_system_fs_bypass):
            if not fs_router.local_backend.exists(request.path):
                raise HTTPException(status_code=404, detail="File not found")
            for edit in request.edits:
                result = fs_router.local_backend.edit(
                    request.path, edit.old_string, edit.new_string
                )
                if result.error or (result.occurrences or 0) <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Content not found for replacement: {edit.old_string[:50]}...",
                    )
            return StatusResponse(status=ResponseStatus.SUCCESS)

        # Check if file exists first
        if not fs_router.exists(request.path):
            raise HTTPException(status_code=404, detail="File not found")

        # Apply each edit operation
        for edit in request.edits:
            success = fs_router.edit(request.path, edit.old_string, edit.new_string)
            if not success:
                raise HTTPException(
                    status_code=400,
                    detail=f"Content not found for replacement: {edit.old_string[:50]}...",
                )

        return StatusResponse(status=ResponseStatus.SUCCESS)
    except (WritePermissionError, PermissionError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_edit_failed", path=request.path, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/fs/upload_file", response_model=StatusResponse)
async def upload_file(
    path: str = Form(...),
    file: UploadFile = File(...),
    bypass_agent_permissions: bool = Form(False),
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """Upload a file with binary content."""
    try:
        content = await file.read()
        responses = _upload_workspace_files(
            fs_router,
            [(path, content)],
            bypass_agent_permissions=_bypass_enabled(
                bypass_agent_permissions, x_system_fs_bypass
            ),
        )
        _raise_first_upload_error(responses)

        return StatusResponse(status=ResponseStatus.SUCCESS)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_upload_file_failed", path=path, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/fs/upload_files_binary", response_model=StatusResponse)
async def upload_files_binary(
    paths: list[str] = Form(...),
    files: list[UploadFile] = File(...),
    bypass_agent_permissions: bool = Form(False),
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """Upload multiple files in one multipart request."""
    try:
        if len(paths) != len(files):
            raise HTTPException(
                status_code=400,
                detail="paths and files must contain the same number of entries",
            )

        payload_files: list[tuple[str, bytes]] = []
        for path, upload in zip(paths, files):
            payload_files.append((path, await upload.read()))

        responses = _upload_workspace_files(
            fs_router,
            payload_files,
            bypass_agent_permissions=_bypass_enabled(
                bypass_agent_permissions, x_system_fs_bypass
            ),
        )
        _raise_first_upload_error(responses)
        return StatusResponse(status=ResponseStatus.SUCCESS)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_upload_files_binary_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/fs/upload_files", response_model=StatusResponse)
async def upload_files(
    request: UploadFilesRequest,
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """Upload multiple files in a single JSON payload."""
    try:
        files = [
            (entry.path, base64.b64decode(entry.content_b64)) for entry in request.files
        ]
        responses = _upload_workspace_files(
            fs_router,
            files,
            bypass_agent_permissions=_bypass_enabled(
                request.bypass_agent_permissions, x_system_fs_bypass
            ),
        )
        _raise_first_upload_error(responses)

        return StatusResponse(status=ResponseStatus.SUCCESS)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_upload_files_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/fs/upload_files_object_store", response_model=StatusResponse)
async def upload_files_object_store(
    request: UploadFilesFromObjectStoreRequest,
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """Stage multiple workspace files from object-store keys in one request."""
    try:
        responses = _download_object_store_files(
            fs_router,
            [(entry.path, entry.object_store_key) for entry in request.files],
            bypass_agent_permissions=_bypass_enabled(
                request.bypass_agent_permissions, x_system_fs_bypass
            ),
        )
        _raise_first_upload_error(responses)
        return StatusResponse(status=ResponseStatus.SUCCESS)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_upload_files_object_store_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/fs/read_blob")
async def read_blob(
    request: ReadFileRequest,
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """Read file contents as binary blob."""
    try:
        if _bypass_enabled(request.bypass_agent_permissions, x_system_fs_bypass):
            local_path = fs_router.local_backend._resolve(request.path)
            if not local_path.exists():
                raise FileNotFoundError
            return Response(
                content=local_path.read_bytes(),
                media_type="application/octet-stream",
            )
        content = fs_router.read(request.path)
        return Response(content=content, media_type="application/octet-stream")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.warning("api_read_blob_failed", path=request.path, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/fs/read_files", response_model=ReadFilesResponse)
async def read_files(
    request: ReadFilesRequest,
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """Read multiple files as base64-encoded binary blobs in one request."""
    try:
        bypass = _bypass_enabled(request.bypass_agent_permissions, x_system_fs_bypass)
        return _read_file_blob_entries(
            fs_router,
            list(request.paths),
            bypass_agent_permissions=bypass,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.warning("api_read_files_failed", paths=request.paths, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/fs/grep", response_model=list[GrepMatch])
async def api_grep(
    request: GrepRequest,
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """Search for a pattern in files."""
    try:
        if _bypass_enabled(request.bypass_agent_permissions, x_system_fs_bypass):
            matches = fs_router.local_backend.grep_raw(
                pattern=request.pattern, path=request.path, glob=request.glob
            )
        else:
            matches = fs_router.grep_raw(
                pattern=request.pattern, path=request.path, glob=request.glob
            )
        if isinstance(matches, str):
            raise HTTPException(status_code=400, detail=matches)
        return matches
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_grep_failed", pattern=request.pattern, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/fs/bundle")
async def bundle_session(fs_router=Depends(get_router)):
    """Bundle the session workspace into a gzipped tarball."""
    return Response(
        content=_bundle_session_bytes(fs_router),
        media_type="application/x-gzip",
        headers={"Content-Disposition": "attachment; filename=session.tar.gz"},
    )


@light_router.get("/render/bundles", response_model=list[RenderBundleIndexEntry])
async def list_render_bundle_history(fs_router=Depends(get_router)):
    """List published render bundles from the append-only discovery index."""
    return list_render_bundles(fs_router.local_backend.root)


@light_router.post("/render/query", response_model=RenderBundleQueryResult)
async def query_render_bundle_route(
    request: RenderBundleQueryRequest,
    fs_router=Depends(get_router),
):
    """Resolve compact metadata for one published render bundle."""
    try:
        return query_render_bundle(request, workspace_root=fs_router.local_backend.root)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning(
            "api_render_bundle_query_failed",
            bundle_path=request.bundle_path,
            manifest_path=request.manifest_path,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@light_router.post("/render/pick", response_model=RenderBundlePointPickResult)
async def pick_render_bundle_pixel_route(
    request: RenderBundlePointPickRequest,
    fs_router=Depends(get_router),
):
    """Resolve a screen-space click against one published render bundle."""
    try:
        return pick_preview_pixel(request, workspace_root=fs_router.local_backend.root)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning(
            "api_render_bundle_pick_failed",
            bundle_path=request.bundle_path,
            manifest_path=request.manifest_path,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@light_router.post(
    "/render/pick/batch", response_model=list[RenderBundlePointPickResult]
)
async def pick_render_bundle_pixels_route(
    requests: list[RenderBundlePointPickRequest],
    fs_router=Depends(get_router),
):
    """Resolve multiple screen-space clicks as one request object per pick."""
    try:
        return pick_preview_pixels(
            requests, workspace_root=fs_router.local_backend.root
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning(
            "api_render_bundle_pick_batch_failed",
            pick_count=len(requests),
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@light_router.post("/fs/delete", response_model=StatusResponse)
async def delete_file(
    request: DeleteFileRequest,
    fs_router=Depends(get_router),
    x_system_fs_bypass: str | None = Header(default=None, alias="X-System-FS-Bypass"),
):
    """Delete a file or directory."""
    try:
        if _bypass_enabled(request.bypass_agent_permissions, x_system_fs_bypass):
            fs_router.local_backend.delete(request.path)
            return StatusResponse(status=ResponseStatus.SUCCESS)
        fs_router.delete(request.path)
        return StatusResponse(status=ResponseStatus.SUCCESS)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Path not found")
    except (WritePermissionError, PermissionError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        logger.warning("api_delete_failed", path=request.path, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@light_router.post("/git/init", response_model=StatusResponse)
async def git_init(fs_router=Depends(get_router)):
    """Initialize a git repository in the workspace."""
    try:
        init_workspace_repo(fs_router.local_backend.root)
        return StatusResponse(status=ResponseStatus.SUCCESS)
    except Exception as e:
        logger.warning("api_git_init_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/git/commit", response_model=GitCommitResponse)
async def git_commit(request: GitCommitRequest, fs_router=Depends(get_router)):
    """Commit changes to the local repository."""
    try:
        commit_hash = commit_all(fs_router.local_backend.root, request.message)

        if commit_hash:
            return GitCommitResponse(
                success=True,
                commit_hash=commit_hash,
                message="Commit successful",
            )
        return GitCommitResponse(
            success=True,
            commit_hash=None,
            message="No changes to commit",
        )
    except Exception as e:
        logger.warning("api_git_commit_failed", error=str(e))
        return GitCommitResponse(success=False, message=str(e))


@light_router.get("/git/status", response_model=GitStatusResponse)
async def git_status(fs_router=Depends(get_router)):
    """Get repository status."""
    return get_repo_status(fs_router.local_backend.root)


@light_router.post("/git/resolve", response_model=StatusResponse)
async def git_resolve(request: GitResolveRequest, fs_router=Depends(get_router)):
    """Resolve a merge conflict."""
    path = fs_router.local_backend.root
    success = False
    if request.strategy == "ours":
        success = resolve_conflict_ours(path, request.file_path)
    elif request.strategy == "theirs":
        success = resolve_conflict_theirs(path, request.file_path)

    if success:
        return StatusResponse(status=ResponseStatus.SUCCESS)
    raise HTTPException(status_code=500, detail="Failed to resolve conflict")


@light_router.post("/git/merge/abort", response_model=StatusResponse)
async def git_abort(fs_router=Depends(get_router)):
    """Abort a merge."""
    if abort_merge(fs_router.local_backend.root):
        return StatusResponse(status=ResponseStatus.SUCCESS)
    raise HTTPException(status_code=500, detail="Failed to abort merge")


@light_router.post("/git/merge/complete", response_model=GitCommitResponse)
async def git_complete(
    request: GitMergeRequest,
    x_session_id: str = Header(...),
    fs_router=Depends(get_router),
):
    """Complete a merge."""
    commit_hash = complete_merge(
        fs_router.local_backend.root, request.message, session_id=x_session_id
    )
    if commit_hash:
        return GitCommitResponse(
            success=True,
            commit_hash=commit_hash,
            message="Merge completed successfully",
        )
    return GitCommitResponse(
        success=False,
        message="Failed to complete merge (conflicts might remain)",
    )


@light_router.post("/runtime/execute", response_model=ExecuteResponse)
async def execute_code(
    request: ExecuteRequest,
    http_request: Request,
    x_session_id: str = Header(...),
    fs_router=Depends(get_router),
):
    """Execute a shell command in the session-isolated environment."""
    session_dir = fs_router.local_backend.root
    worker_light_url = str(http_request.base_url).rstrip("/")

    config = RuntimeConfig(
        timeout_seconds=request.timeout,
        working_directory=str(session_dir),
    )
    from worker_light.config import settings

    # Executed scripts should validate directly against the session workspace
    # rather than re-entering the controller script-tools proxy. The proxy path
    # is for control-plane orchestration, while runtime execution needs the
    # lightweight heavy-worker fallback to observe the exact workspace files
    # written in this session.
    result = await run_command_async(
        command=request.code,
        env={
            "SESSION_ID": x_session_id,
            "EPISODE_ID": request.episode_id or x_session_id,
            "WORKER_HEAVY_URL": settings.worker_heavy_url,
            "CONTROLLER_URL": os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000"),
            # Runtime execution must exercise the real validation path, not the
            # control-plane import shim used while materializing authored scripts.
            "PROBLEMOLOGIST_SCRIPT_IMPORT_MODE": "0",
            "WORKER_LIGHT_URL": worker_light_url,
            **(
                {"WORKER_SESSIONS_DIR": settings.sessions_dir}
                if settings.sessions_dir is not None
                else {}
            ),
        },
        config=config,
        session_id=x_session_id,
    )
    events = _collect_events(fs_router)

    return ExecuteResponse(
        stdout=_sanitize_workspace_alias(result.stdout, session_dir),
        stderr=_sanitize_workspace_alias(result.stderr, session_dir),
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        events=events,
    )


@light_router.get("/assets/{path:path}")
async def get_asset(path: str, fs_router=Depends(get_router)):
    """Serve assets from the filesystem."""
    try:
        validate_asset_source(fs_router.local_backend.root, path)

        content = fs_router.read(path)
        media_type = get_media_type(path)
        return Response(content=content, media_type=media_type)
    except (FileNotFoundError, IsADirectoryError):
        raise HTTPException(status_code=404, detail="Asset not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_asset_failed", path=path, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@light_router.post("/lint", response_model=LintResponse)
async def api_lint(
    request: LintRequest,
    fs_router=Depends(get_router),
):
    """Lint Python code using ruff."""
    import asyncio
    import json
    import tempfile

    try:
        # Get content either from path or direct content
        if request.path:
            content = fs_router.read(request.path).decode("utf-8")
        elif request.content:
            content = request.content
        else:
            return LintResponse(
                success=False,
                errors=[{"message": "Either path or content must be provided"}],
            )

        # Write to temp file for ruff
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # Run ruff check with JSON output asynchronously
            process = await asyncio.create_subprocess_exec(
                "ruff",
                "check",
                "--output-format",
                "json",
                tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise

            errors = []
            warnings = []

            if stdout:
                lint_results = json.loads(stdout.decode())
                for item in lint_results:
                    issue = {
                        "code": item.get("code", ""),
                        "message": item.get("message", ""),
                        "line": item.get("location", {}).get("row", 0),
                        "column": item.get("location", {}).get("column", 0),
                    }
                    if item.get("code", "").startswith(("E", "F")):
                        errors.append(issue)
                    else:
                        warnings.append(issue)

            return LintResponse(
                success=len(errors) == 0,
                errors=errors,
                warnings=warnings,
            )
        finally:
            Path(tmp_path).unlink()

    except FileNotFoundError:
        return LintResponse(
            success=False,
            errors=[{"message": f"File not found: {request.path}"}],
        )
    except Exception as e:
        logger.warning("api_lint_failed", error=str(e))
        return LintResponse(
            success=False,
            errors=[{"message": str(e)}],
        )
