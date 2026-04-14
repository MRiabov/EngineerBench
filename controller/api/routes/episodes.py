import asyncio
import hashlib
import re
import uuid
from datetime import datetime
from pathlib import Path as FilePath
from typing import Annotated, Literal

import httpx
import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi import (
    Path as FastAPIPath,
)
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from controller.api.manager import manager, task_tracker
from controller.api.schemas import (
    EpisodeReplayResponse,
    ReplayReviewManifestResponse,
)
from controller.clients.worker import WorkerClient
from controller.config.settings import settings
from controller.observability.langfuse import get_langfuse_client
from controller.persistence.db import get_db
from controller.persistence.models import Asset, Episode, Trace
from shared.enums import (
    AssetType,
    EpisodeStatus,
    EpisodeType,
    ResponseStatus,
    ReviewDecision,
    TraceType,
)
from shared.git_utils import repo_revision
from shared.models.schemas import (
    EntryValidationContext,
    EpisodeMetadata,
    ReplayArtifactRecord,
    ReplayFailureSignal,
    ReplayTraceIds,
    TraceMetadata,
)
from shared.models.simulation import SimulationResult
from shared.observability.schemas import ReviewDecisionEvent
from shared.workers.schema import (
    PlanReviewManifest,
    ReviewManifest,
    SimulationFrameStreamMessage,
    ValidationResultRecord,
)

logger = structlog.get_logger(__name__)
_MESSAGE_LOG_PREVIEW_LIMIT = 500


def _is_closed_websocket_error(exc: Exception) -> bool:
    return isinstance(exc, RuntimeError) and (
        'Cannot call "send" once a close message has been sent.' in str(exc)
    )


def _normalize_plan_markdown(plan_content: str | None) -> str | None:
    """Normalize persisted plans for list responses used by dataset-readiness checks."""
    if not plan_content:
        return plan_content

    normalized = plan_content.strip()
    if "# Solution Overview" in normalized and "## Parts List" in normalized:
        return normalized

    if normalized.startswith("# Engineering Plan"):
        _, _, remainder = normalized.partition("\n")
        normalized = remainder.lstrip()

    replacements = {
        "## 1. Solution Overview": "# Solution Overview",
        "## 2. Parts List": "## Parts List",
        "## 3. Assembly Strategy": "## Assembly Strategy",
        "## 4. Assumption Register": "## Assumption Register",
        "## 5. Detailed Calculations": "## Detailed Calculations",
        "## 6. Critical Constraints / Operating Envelope": "## Critical Constraints / Operating Envelope",
        "## 7. Cost & Weight Budget": "## Cost & Weight Budget",
        "## 8. Risk Assessment": "## Risk Assessment",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)

    if "# Solution Overview" in normalized and "## Parts List" in normalized:
        return normalized

    return (
        "# Solution Overview\n"
        "Normalized from persisted plan artifact for dataset readiness.\n\n"
        "## Parts List\n"
        "- Original plan preserved below.\n\n"
        "## Source Plan\n"
        f"{normalized}"
    )


_REVIEW_ROUND_RE = re.compile(
    r"^(?P<prefix>reviews/.+-round-)(?P<round>\d+)(?P<suffix>\.yaml)$"
)
_REPLAY_REQUIRED_TEXT_ARTIFACTS = {
    "validation_results.json",
    "simulation_result.json",
}
_REPLAY_REVIEW_MANIFEST_SUFFIXES = (
    "benchmark_plan_review_manifest.json",
    "benchmark_review_manifest.json",
    "engineering_plan_review_manifest.json",
    "engineering_execution_handoff_manifest.json",
)


def _normalize_artifact_path(path: str) -> str:
    return FilePath(path).as_posix().lstrip("/")


def _select_latest_replay_assets(assets: list[Asset]) -> list[Asset]:
    latest_by_path: dict[str, Asset] = {}
    latest_round_by_family: dict[str, tuple[int, Asset]] = {}

    for asset in sorted(assets, key=lambda item: (item.created_at, item.id)):
        path = _normalize_artifact_path(asset.s3_path)
        match = _REVIEW_ROUND_RE.match(path)
        if match:
            family = match.group("prefix").removeprefix("reviews/")
            round_index = int(match.group("round"))
            current = latest_round_by_family.get(family)
            if current is None or round_index >= current[0]:
                latest_round_by_family[family] = (round_index, asset)
            continue

        latest_by_path[path] = asset

    selected: list[Asset] = list(latest_by_path.values())
    selected.extend(asset for _, asset in latest_round_by_family.values())
    selected.sort(key=lambda item: (_normalize_artifact_path(item.s3_path), item.id))
    return selected


def _asset_looks_like_review_manifest(path: str) -> bool:
    normalized = _normalize_artifact_path(path)
    return normalized.endswith(_REPLAY_REVIEW_MANIFEST_SUFFIXES)


def _artifact_kind_from_path(path: str) -> str:
    normalized = _normalize_artifact_path(path)
    if normalized.endswith("validation_results.json"):
        return "validation_results"
    if normalized.endswith("simulation_result.json"):
        return "simulation_result"
    if normalized.endswith(_REPLAY_REVIEW_MANIFEST_SUFFIXES):
        return "review_manifest"
    if normalized.startswith("reviews/"):
        return "review_evidence"
    return "artifact"


def _artifact_path_matches(path: str, target: str) -> bool:
    normalized = _normalize_artifact_path(path)
    return (
        normalized == target
        or normalized.endswith(f"/{target}")
        or normalized.endswith(target)
    )


async def _load_text_artifact(
    *,
    asset: Asset,
    worker_client: WorkerClient,
) -> str:
    if asset.content is not None:
        return asset.content

    path = _normalize_artifact_path(asset.s3_path)
    for candidate in (
        path,
        path.removeprefix("workspace/"),
        f"workspace/{path}",
    ):
        if not candidate:
            continue
        if await worker_client.exists(candidate, bypass_agent_permissions=True):
            return await worker_client.read_file(
                candidate, bypass_agent_permissions=True
            )

    raise FileNotFoundError(f"Persisted artifact not found: {path}")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _failure_signals_from_metadata(
    metadata: EpisodeMetadata,
) -> list[ReplayFailureSignal]:
    signals: list[ReplayFailureSignal] = []
    additional = metadata.additional_info or {}
    for key in ("unsupported_mechanism", "unsupported_feature_mismatch"):
        if additional.get(key):
            signals.append(
                ReplayFailureSignal(
                    kind=key,
                    message=str(additional.get(key)),
                    source="metadata.additional_info",
                )
            )

    for log in metadata.validation_logs:
        normalized = log.lower()
        if any(
            token in normalized for token in ("fallback", "unsupported", "mismatch")
        ):
            signals.append(
                ReplayFailureSignal(
                    kind="validation_log",
                    message=log,
                    source="metadata.validation_logs",
                )
            )

    entry_validation = additional.get("entry_validation")
    if isinstance(entry_validation, dict):
        errors = entry_validation.get("errors") or []
        for error in errors:
            if isinstance(error, dict):
                signals.append(
                    ReplayFailureSignal(
                        kind=error.get("code") or "entry_validation_error",
                        message=str(error.get("message") or ""),
                        source=str(error.get("source") or "entry_validation"),
                        artifact_path=(
                            str(error.get("artifact_path"))
                            if error.get("artifact_path")
                            else None
                        ),
                    )
                )

    return signals


def _trace_ids_from_episode(
    episode: Episode,
) -> tuple[ReplayTraceIds, str | None, str | None, str | None]:
    simulation_run_id: str | None = None
    cots_query_id: str | None = None
    review_id: str | None = None
    trace_ids = ReplayTraceIds()

    for trace in episode.traces:
        trace_metadata = TraceMetadata.model_validate(trace.metadata_vars or {})
        if simulation_run_id is None:
            simulation_run_id = (
                trace.simulation_run_id or trace_metadata.simulation_run_id
            )
        if cots_query_id is None:
            cots_query_id = trace.cots_query_id or trace_metadata.cots_query_id
        if review_id is None:
            review_id = trace.review_id or trace_metadata.review_id

        if trace.name == "simulation_result" or (
            simulation_run_id
            and (
                trace.simulation_run_id == simulation_run_id
                or trace_metadata.simulation_run_id == simulation_run_id
            )
        ):
            trace_ids.simulation_trace_ids.append(trace.id)

        if trace.name == "review_decision" or (
            review_id
            and (trace.review_id == review_id or trace_metadata.review_id == review_id)
        ):
            trace_ids.review_trace_ids.append(trace.id)

        if trace.name == "node_entry_validation_failed":
            trace_ids.entry_validation_trace_ids.append(trace.id)

    return trace_ids, simulation_run_id, cots_query_id, review_id


def _review_decision_events_from_episode(
    episode: Episode,
) -> list[ReviewDecisionEvent]:
    events: list[ReviewDecisionEvent] = []
    for trace in sorted(episode.traces, key=lambda trace: trace.id):
        if trace.name != "review_decision":
            continue
        metadata = TraceMetadata.model_validate(trace.metadata_vars or {})
        if metadata.decision is None:
            continue

        events.append(
            ReviewDecisionEvent(
                episode_id=str(episode.id),
                user_session_id=str(trace.user_session_id)
                if trace.user_session_id
                else (
                    str(episode.user_session_id) if episode.user_session_id else None
                ),
                agent_id=trace.name,
                decision=metadata.decision,
                reason=str(trace.content or metadata.observation or "Persisted review"),
                review_id=metadata.review_id or trace.review_id,
                checklist=dict(metadata.checklist or {}),
            )
        )
    return events


def _manifest_expected_revision(
    manifest: ReviewManifest | PlanReviewManifest,
) -> str | None:
    for attr in ("revision", "benchmark_revision", "solution_revision"):
        value = getattr(manifest, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _validate_manifest_session(
    *,
    manifest: ReviewManifest | PlanReviewManifest,
    episode_id: str,
    worker_session_id: str,
) -> None:
    for field_name, expected in (
        ("session_id", worker_session_id),
        ("episode_id", episode_id),
        ("worker_session_id", worker_session_id),
    ):
        actual = getattr(manifest, field_name, None)
        if actual and actual != expected:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"stale_manifest: {field_name} mismatch on "
                    f"{type(manifest).__name__}"
                ),
            )


async def _build_episode_replay_response(
    *,
    episode: Episode,
    worker_client: WorkerClient,
) -> EpisodeReplayResponse:
    if not episode.metadata_vars:
        raise HTTPException(status_code=422, detail="missing_metadata: episode")

    metadata = EpisodeMetadata.model_validate(episode.metadata_vars)
    worker_session_id = metadata.worker_session_id or str(episode.id)
    if not worker_session_id:
        raise HTTPException(status_code=422, detail="missing_worker_session_id")

    additional = metadata.additional_info or {}
    if additional.get("unsupported_mechanism") or additional.get(
        "unsupported_feature_mismatch"
    ):
        raise HTTPException(
            status_code=422,
            detail="unsupported_mechanism: replay cannot reconstruct unsupported path",
        )

    selected_assets = _select_latest_replay_assets(list(episode.assets))

    missing_required = [
        path
        for path in sorted(_REPLAY_REQUIRED_TEXT_ARTIFACTS)
        if not any(
            _artifact_path_matches(asset.s3_path, path) for asset in selected_assets
        )
    ]
    if missing_required:
        raise HTTPException(
            status_code=422,
            detail=f"missing_artifact: {missing_required[0]}",
        )

    review_manifest_assets = [
        asset
        for asset in selected_assets
        if _asset_looks_like_review_manifest(asset.s3_path)
    ]
    if not review_manifest_assets:
        raise HTTPException(
            status_code=422,
            detail="missing_review_evidence: review manifest missing",
        )

    replay_artifacts: list[ReplayArtifactRecord] = []
    artifact_contents: dict[str, str] = {}
    for asset in selected_assets:
        path = _normalize_artifact_path(asset.s3_path)
        if not (
            any(
                _artifact_path_matches(path, required)
                for required in _REPLAY_REQUIRED_TEXT_ARTIFACTS
            )
            or _asset_looks_like_review_manifest(path)
            or path.startswith("reviews/")
            or path
            in {
                "plan.md",
                "todo.md",
                "journal.md",
                "script.py",
                "solution_script.py",
                "benchmark_script.py",
            }
        ):
            continue

        content = await _load_text_artifact(asset=asset, worker_client=worker_client)
        replay_artifacts.append(
            ReplayArtifactRecord(
                path=path,
                sha256=_sha256_text(content),
                size_bytes=len(content.encode("utf-8")),
                asset_type=asset.asset_type,
            )
        )
        artifact_contents[path] = content

    validation_asset = next(
        asset
        for asset in selected_assets
        if _artifact_path_matches(asset.s3_path, "validation_results.json")
    )
    validation_text = artifact_contents.get("validation_results.json")
    if validation_text is None:
        validation_text = await _load_text_artifact(
            asset=validation_asset, worker_client=worker_client
        )
    try:
        validation_result = ValidationResultRecord.model_validate_json(validation_text)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"invalid_artifact: validation_results.json ({exc!s})",
        ) from exc

    simulation_asset = next(
        asset
        for asset in selected_assets
        if _artifact_path_matches(asset.s3_path, "simulation_result.json")
    )
    simulation_text = artifact_contents.get("simulation_result.json")
    if simulation_text is None:
        simulation_text = await _load_text_artifact(
            asset=simulation_asset, worker_client=worker_client
        )
    try:
        simulation_result = SimulationResult.model_validate_json(simulation_text)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"invalid_artifact: simulation_result.json ({exc!s})",
        ) from exc

    if validation_result.script_path:
        script_path = _normalize_artifact_path(validation_result.script_path)
        script_asset = next(
            (
                asset
                for asset in selected_assets
                if _artifact_path_matches(asset.s3_path, script_path)
            ),
            None,
        )
        if script_asset is None:
            raise HTTPException(
                status_code=422,
                detail=f"missing_artifact: {script_path}",
            )
        script_text = await _load_text_artifact(
            asset=script_asset, worker_client=worker_client
        )
        script_hash = _sha256_text(script_text)
        if (
            validation_result.script_sha256
            and script_hash != validation_result.script_sha256
        ):
            raise HTTPException(
                status_code=422,
                detail=f"stale_manifest: script hash mismatch for {script_path}",
            )

    review_manifests: list[ReplayReviewManifestResponse] = []
    current_revision = repo_revision(FilePath(__file__).resolve().parents[3])
    if current_revision is None:
        raise HTTPException(
            status_code=422,
            detail="stale_manifest: unable to determine current repository revision",
        )

    for asset in review_manifest_assets:
        path = _normalize_artifact_path(asset.s3_path)
        manifest_text = artifact_contents.get(path)
        if manifest_text is None:
            manifest_text = await _load_text_artifact(
                asset=asset, worker_client=worker_client
            )
        try:
            if path.endswith("benchmark_plan_review_manifest.json") or path.endswith(
                "engineering_plan_review_manifest.json"
            ):
                manifest = PlanReviewManifest.model_validate_json(manifest_text)
            else:
                manifest = ReviewManifest.model_validate_json(manifest_text)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"invalid_artifact: {path} ({exc!s})",
            ) from exc

        expected_revision = _manifest_expected_revision(manifest)
        if expected_revision is None:
            raise HTTPException(
                status_code=422,
                detail=f"stale_manifest: missing revision in {path}",
            )
        if expected_revision != current_revision:
            raise HTTPException(
                status_code=422,
                detail=f"stale_manifest: revision mismatch in {path}",
            )
        _validate_manifest_session(
            manifest=manifest,
            episode_id=str(episode.id),
            worker_session_id=worker_session_id,
        )
        review_manifests.append(
            ReplayReviewManifestResponse(path=path, manifest=manifest)
        )

    trace_ids, simulation_run_id, cots_query_id, review_id = _trace_ids_from_episode(
        episode
    )
    review_decision_events = _review_decision_events_from_episode(episode)
    if not review_decision_events:
        raise HTTPException(
            status_code=422,
            detail="missing_review_evidence: review_decision trace missing",
        )

    entry_validation = None
    raw_entry_validation = (metadata.additional_info or {}).get("entry_validation")
    if raw_entry_validation is not None:
        try:
            entry_validation = EntryValidationContext.model_validate(
                raw_entry_validation
            )
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"invalid_artifact: entry_validation ({exc!s})",
            ) from exc

    return EpisodeReplayResponse(
        id=episode.id,
        user_session_id=episode.user_session_id,
        task=episode.task,
        status=episode.status,
        created_at=episode.created_at,
        updated_at=episode.updated_at,
        skill_git_hash=episode.skill_git_hash,
        template_versions=episode.template_versions,
        metadata_vars=metadata,
        todo_list=episode.todo_list,
        journal=episode.journal,
        plan=episode.plan,
        validation_logs=metadata.validation_logs,
        last_trace_id=max((trace.id for trace in episode.traces), default=None),
        traces=[
            TraceResponse.model_validate(t)
            for t in sorted(episode.traces, key=lambda t: t.id)
        ],
        assets=[AssetResponse.model_validate(a) for a in selected_assets],
        worker_session_id=worker_session_id,
        simulation_run_id=simulation_run_id,
        cots_query_id=cots_query_id,
        review_id=review_id,
        terminal_reason=metadata.terminal_reason,
        failure_class=metadata.failure_class,
        detailed_status=metadata.detailed_status,
        entry_validation=entry_validation,
        replay_artifacts=replay_artifacts,
        trace_ids=trace_ids,
        validation_result=validation_result,
        simulation_result=simulation_result,
        review_manifests=review_manifests,
        review_decision_events=review_decision_events,
        failure_signals=_failure_signals_from_metadata(metadata),
    )


class FeedbackRequest(BaseModel):
    score: Literal[0, 1]
    comment: str | None = None

    @field_validator("comment")
    @classmethod
    def strip_null_bytes(cls, v: str | None) -> str | None:
        if v is not None:
            return v.replace("\u0000", "")
        return v


router = APIRouter(prefix="/episodes", tags=["episodes"])


@router.post("/{episode_id}/traces/{trace_id}/feedback", status_code=202)
async def report_trace_feedback(
    episode_id: uuid.UUID,
    trace_id: Annotated[int, FastAPIPath(ge=-(2**31), le=2**31 - 1)],
    feedback: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """Report feedback for a specific trace to Langfuse."""
    logger.info("searching_for_trace", episode_id=str(episode_id), trace_id=trace_id)
    result = await db.execute(
        select(Trace).where(Trace.id == trace_id, Trace.episode_id == episode_id)
    )
    trace = result.scalar_one_or_none()

    if not trace:
        # Diagnostic: Try finding trace by ID alone to see if episode_id is mismatched
        diag_result = await db.execute(select(Trace).where(Trace.id == trace_id))
        diag_trace = diag_result.scalar_one_or_none()
        if diag_trace:
            logger.warning(
                "trace_episode_id_mismatch",
                trace_id=trace_id,
                requested_episode_id=str(episode_id),
                actual_episode_id=str(diag_trace.episode_id),
                trace_type=diag_trace.trace_type,
                trace_name=diag_trace.name,
            )
            # WP10: We return 404 to be strict with the API contract, but the log now has more info
            raise HTTPException(
                status_code=404,
                detail=f"Trace {trace_id} belongs to episode {diag_trace.episode_id}, not {episode_id}",
            )
        logger.warning("trace_not_found_even_by_id", trace_id=trace_id)

        logger.warning("trace_not_found", episode_id=str(episode_id), trace_id=trace_id)
        raise HTTPException(status_code=404, detail="Trace not found")

    # Langfuse update (best effort)
    if trace.langfuse_trace_id:
        try:
            langfuse = get_langfuse_client()
            if langfuse:
                langfuse.create_score(
                    trace_id=trace.langfuse_trace_id,
                    name="user-feedback",
                    value=feedback.score,
                    comment=feedback.comment,
                )
        except Exception as e:
            logger.warning("langfuse_feedback_failed", error=str(e))

    # Store locally
    trace.feedback_score = feedback.score
    trace.feedback_comment = feedback.comment
    await db.commit()

    return {"status": ResponseStatus.ACCEPTED}


@router.get("/{episode_id}/assets/{path:path}")
async def get_episode_asset(
    episode_id: uuid.UUID,
    path: str,
    db: AsyncSession = Depends(get_db),
):
    """Proxy asset requests to the worker."""
    result = await db.execute(select(Episode).where(Episode.id == episode_id))
    episode = result.scalar_one_or_none()

    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    worker_session_id = None
    if episode.metadata_vars:
        metadata = EpisodeMetadata.model_validate(episode.metadata_vars)
        worker_session_id = metadata.worker_session_id

    if not worker_session_id:
        # Fallback for older episodes or benchmarks where session_id might be the id itself
        worker_session_id = str(episode_id)

    normalized_path = path.lstrip("/")
    candidate_asset_paths = [normalized_path]
    if not normalized_path.startswith("workspace/"):
        candidate_asset_paths.insert(0, f"workspace/{normalized_path}")

    worker_light_url = settings.worker_light_url
    # Episode assets are session-workspace artifacts. The worker also exposes
    # read-only mounts such as /reviews, so we try the workspace path first to
    # avoid accidentally resolving session review files against the static mount.
    candidate_paths = candidate_asset_paths

    async with httpx.AsyncClient() as client:
        try:
            deadline = asyncio.get_running_loop().time() + 5.0
            while True:
                asset_result = await db.execute(
                    select(Asset).where(Asset.episode_id == episode_id)
                )
                for asset in asset_result.scalars():
                    normalized_asset_path = _normalize_artifact_path(asset.s3_path)
                    if normalized_asset_path not in candidate_asset_paths:
                        continue
                    if asset.content is not None:
                        return Response(
                            content=asset.content.encode("utf-8"),
                            media_type="text/plain; charset=utf-8",
                            status_code=200,
                        )
                    break

                last_404 = None
                for candidate_path in candidate_paths:
                    asset_url = f"{worker_light_url}/assets/{candidate_path}"
                    resp = await client.get(
                        asset_url,
                        headers={"X-Session-ID": worker_session_id},
                        timeout=10.0,
                    )
                    if resp.status_code == 404:
                        last_404 = resp
                        continue
                    resp.raise_for_status()

                    return Response(
                        content=resp.content,
                        media_type=resp.headers.get("content-type"),
                        status_code=resp.status_code,
                    )

                if asyncio.get_running_loop().time() >= deadline:
                    break
                await asyncio.sleep(0.25)

            if last_404 is not None:
                raise HTTPException(
                    status_code=404, detail=f"Asset {path} not found on worker"
                )
            raise HTTPException(
                status_code=404, detail=f"Asset {path} not found on worker"
            )
        except HTTPException:
            raise
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code, detail=str(e)
            ) from e
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to proxy asset: {e!s}"
            ) from e


class ReviewRequest(BaseModel):
    review_content: str

    @field_validator("review_content")
    @classmethod
    def strip_null_bytes(cls, v: str) -> str:
        return v.replace("\u0000", "")


class MessageRequest(BaseModel):
    message: StrictStr
    metadata_vars: EpisodeMetadata | None = Field(
        None, description="Additional metadata for the message."
    )

    @field_validator("message")
    @classmethod
    def strip_null_bytes(cls, v: str) -> str:
        return v.replace("\u0000", "")


@router.post("/{episode_id}/review")
async def review_episode(
    episode_id: uuid.UUID,
    request: ReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit a review for an episode."""
    from shared.observability.schemas import ReviewEvent
    from worker_heavy.utils.file_validation import validate_review_frontmatter

    result = await db.execute(select(Episode).where(Episode.id == episode_id))
    episode = result.scalar_one_or_none()

    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    # Validate the review frontmatter
    # Routing checks for refusal decisions are handled below with concrete
    # plan_refusal.md validation and deterministic status codes.
    review_validation_session_id = str(episode_id)
    if episode.metadata_vars:
        metadata = EpisodeMetadata.model_validate(episode.metadata_vars)
        review_validation_session_id = (
            metadata.worker_session_id or review_validation_session_id
        )

    is_valid, review_data = validate_review_frontmatter(
        request.review_content,
        cad_agent_refused=True,
        session_id=review_validation_session_id,
    )
    if not is_valid:
        raise HTTPException(status_code=422, detail=f"Invalid review: {review_data}")

    # Update episode based on decision
    decision = review_data.decision
    rejection_decisions = {
        ReviewDecision.REJECTED,
        ReviewDecision.REJECT_PLAN,
        ReviewDecision.REJECT_CODE,
    }
    if decision in rejection_decisions:
        rejection_reason = next(
            (
                comment.strip()
                for comment in review_data.comments
                if isinstance(comment, str) and comment.strip()
            ),
            "",
        )
        if not rejection_reason:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Rejection decisions require at least one non-empty reason "
                    "in review comments."
                ),
            )

    episode_metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
    engineer_execution_decisions = {
        ReviewDecision.APPROVED,
        ReviewDecision.REJECTED,
        ReviewDecision.REJECT_PLAN,
        ReviewDecision.REJECT_CODE,
    }
    if (
        episode_metadata.episode_type == EpisodeType.ENGINEER
        and decision in engineer_execution_decisions
    ):
        evidence = (
            review_data.evidence if isinstance(review_data.evidence, dict) else {}
        )
        stability_summary = evidence.get("stability_summary")
        if not stability_summary:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Engineer review decisions require stability_summary evidence "
                    "from validation_results.json."
                ),
            )

    if decision == ReviewDecision.APPROVED:
        episode.status = EpisodeStatus.COMPLETED
    elif decision in (
        ReviewDecision.REJECTED,
        ReviewDecision.REJECT_PLAN,
        ReviewDecision.REJECT_CODE,
    ):
        episode.status = EpisodeStatus.FAILED
    elif decision == ReviewDecision.CONFIRM_PLAN_REFUSAL:
        # WP06: Validate plan_refusal.md existence and content
        worker_session_id = str(episode_id)
        if episode.metadata_vars:
            metadata = EpisodeMetadata.model_validate(episode.metadata_vars)
            worker_session_id = metadata.worker_session_id or worker_session_id

        client = WorkerClient(
            base_url=settings.worker_light_url,
            session_id=worker_session_id,
            heavy_url=settings.worker_heavy_url,
        )
        try:
            refusal_content = await client.read_file("plan_refusal.md")
            from worker_heavy.utils.file_validation import validate_plan_refusal

            is_valid_refusal, refusal_errs = validate_plan_refusal(refusal_content)
            if not is_valid_refusal:
                raise HTTPException(
                    status_code=422, detail=f"Invalid plan_refusal.md: {refusal_errs}"
                )
        except FileNotFoundError:
            raise HTTPException(
                status_code=422,
                detail="plan_refusal.md not found but required for CONFIRM_PLAN_REFUSAL",
            )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(
                status_code=500, detail=f"Failed to validate plan_refusal.md: {e!s}"
            )

        episode.status = EpisodeStatus.FAILED

    # Record review event to DB
    import uuid as uuid_lib

    from controller.observability.tracing import record_worker_events

    review_id = uuid_lib.uuid4().hex

    await record_worker_events(
        episode_id=episode_id,
        events=[
            ReviewEvent(
                episode_id=str(episode_id),
                decision=decision,
                comments=review_data.comments,
                review_id=review_id,
            )
        ],
    )

    await db.commit()
    return {"status": ResponseStatus.SUCCESS, "decision": decision}


@router.post("/{episode_id}/messages", status_code=202)
async def continue_episode(
    episode_id: uuid.UUID,
    request: MessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a follow-up message to a running or completed episode."""
    from controller.api.tasks import continue_agent_task

    result = await db.execute(select(Episode).where(Episode.id == episode_id))
    episode = result.scalar_one_or_none()

    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    logger.info(
        "episode_message_received",
        episode_id=str(episode_id),
        message=request.message,
        message_preview=request.message[:_MESSAGE_LOG_PREVIEW_LIMIT],
        message_length=len(request.message),
        has_metadata=bool(request.metadata_vars),
    )

    # In a real system, we might want to check if the agent is already busy
    # but for now we'll rely on the task_tracker or just allow it to queue.

    task = asyncio.create_task(
        continue_agent_task(
            episode_id,
            request.message,
            metadata=request.metadata_vars.model_dump()
            if request.metadata_vars
            else None,
        )
    )
    task_tracker.register_task(episode_id, task)

    return {"status": ResponseStatus.ACCEPTED, "message": "Message sent to agent"}

class TraceResponse(BaseModel):
    id: int
    user_session_id: uuid.UUID | None = None
    langfuse_trace_id: str | None
    simulation_run_id: str | None = None
    cots_query_id: str | None = None
    review_id: str | None = None
    trace_type: TraceType
    name: str | None
    content: str | None
    metadata_vars: TraceMetadata | None = None
    feedback_score: int | None = None
    feedback_comment: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @property
    def metadata(self) -> TraceMetadata | None:
        """Backward-compatible alias for clients using `metadata`."""
        return self.metadata_vars


class AssetResponse(BaseModel):
    id: int
    user_session_id: uuid.UUID | None = None
    asset_type: AssetType
    s3_path: str
    content: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EpisodeResponse(BaseModel):
    id: uuid.UUID
    user_session_id: uuid.UUID | None = None
    task: StrictStr
    status: EpisodeStatus
    created_at: datetime
    updated_at: datetime
    skill_git_hash: str | None = None
    template_versions: dict | None = None
    metadata_vars: EpisodeMetadata | None = None
    todo_list: dict | None = None
    journal: str | None = None
    plan: str | None = None
    validation_logs: list[str] | None = None
    last_trace_id: int | None = None
    traces: list[TraceResponse] | None = None
    assets: list[AssetResponse] | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @property
    def metadata(self) -> EpisodeMetadata | None:
        """Backward-compatible alias for clients using `metadata`."""
        return self.metadata_vars


@router.get("/", response_model=list[EpisodeResponse])
async def list_episodes(
    limit: Annotated[int, Query(ge=0, lt=2**63)] = 100,
    offset: Annotated[int, Query(ge=0, lt=2**63)] = 0,
    db: AsyncSession = Depends(get_db),
):
    """List all agent episodes."""
    from sqlalchemy import func

    try:
        result = await db.execute(
            select(Episode)
            .order_by(Episode.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        episodes = result.scalars().all()

        # Batch fetch last trace IDs for the UI feedback system
        ep_ids = [ep.id for ep in episodes]
        last_trace_map = {}
        markdown_asset_map: dict[uuid.UUID, dict[str, str]] = {}
        if ep_ids:
            trace_result = await db.execute(
                select(Trace.episode_id, func.max(Trace.id))
                .where(Trace.episode_id.in_(ep_ids))
                .group_by(Trace.episode_id)
            )
            last_trace_map = dict(trace_result.all())
            assets_result = await db.execute(
                select(Asset.episode_id, Asset.s3_path, Asset.content).where(
                    Asset.episode_id.in_(ep_ids),
                    Asset.s3_path.in_(
                        ["plan.md", "/plan.md", "journal.md", "/journal.md"]
                    ),
                )
            )
            for episode_id, s3_path, content in assets_result.all():
                if not content:
                    continue
                key = s3_path.lstrip("/")
                markdown_asset_map.setdefault(episode_id, {})[key] = content

        # Explicitly convert to EpisodeResponse to avoid lazy-loading traces/assets during serialization
        responses: list[EpisodeResponse] = []
        for ep in episodes:
            asset_content = markdown_asset_map.get(ep.id, {})
            plan_content = _normalize_plan_markdown(
                ep.plan or asset_content.get("plan.md")
            )
            journal_content = ep.journal or asset_content.get("journal.md")

            # Normalize legacy journals to required structured sections.
            if journal_content:
                stripped = journal_content.strip()
                if (
                    not (stripped.startswith("#") or "##" in stripped)
                    or "## Observations" not in stripped
                    or "## Decision Log" not in stripped
                ):
                    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
                    bullet_lines = (
                        "\n".join(f"- {ln}" for ln in lines) or "- No details"
                    )
                    journal_content = (
                        "# Execution Journal\n"
                        "## Observations\n"
                        f"{bullet_lines}\n\n"
                        "## Decision Log\n"
                        "- [x] completed: true\n"
                    )

            responses.append(
                EpisodeResponse(
                    id=ep.id,
                    user_session_id=ep.user_session_id,
                    task=ep.task,
                    status=ep.status,
                    created_at=ep.created_at,
                    updated_at=ep.updated_at,
                    skill_git_hash=ep.skill_git_hash,
                    template_versions=ep.template_versions,
                    metadata_vars=EpisodeMetadata.model_validate(ep.metadata_vars)
                    if ep.metadata_vars
                    else None,
                    todo_list=ep.todo_list
                    or (
                        {"completed": True}
                        if ep.status == EpisodeStatus.COMPLETED
                        else None
                    ),
                    journal=journal_content,
                    plan=plan_content,
                    validation_logs=ep.validation_logs,
                    last_trace_id=last_trace_map.get(ep.id),
                    traces=[],
                    assets=[],
                )
            )
        return responses
    except Exception as e:
        logger.warning("list_episodes_failed", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Internal Server Error: {e!s}"
        ) from e


@router.get("/{episode_id}", response_model=EpisodeResponse)
async def get_episode(episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get a specific episode."""
    result = await db.execute(
        select(Episode)
        .where(Episode.id == episode_id)
        .options(selectinload(Episode.traces), selectinload(Episode.assets))
    )
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    # Populate last_trace_id for EpisodeResponse
    last_trace_id = None
    sorted_traces = sorted(episode.traces, key=lambda t: t.id)
    if sorted_traces:
        last_trace_id = max(t.id for t in sorted_traces)
    canonical_lf_trace_id = next(
        (t.langfuse_trace_id for t in sorted_traces if t.langfuse_trace_id),
        str(episode.id),
    )
    for t in sorted_traces:
        t.langfuse_trace_id = canonical_lf_trace_id

    return EpisodeResponse(
        id=episode.id,
        user_session_id=episode.user_session_id,
        task=episode.task,
        status=episode.status,
        created_at=episode.created_at,
        updated_at=episode.updated_at,
        skill_git_hash=episode.skill_git_hash,
        template_versions=episode.template_versions,
        metadata_vars=EpisodeMetadata.model_validate(episode.metadata_vars)
        if episode.metadata_vars
        else None,
        todo_list=episode.todo_list
        or ({"completed": True} if episode.status == EpisodeStatus.COMPLETED else None),
        journal=episode.journal,
        plan=episode.plan,
        validation_logs=episode.validation_logs,
        last_trace_id=last_trace_id,
        traces=[TraceResponse.model_validate(t) for t in sorted_traces],
        assets=[
            AssetResponse.model_validate(a)
            for a in sorted(
                episode.assets,
                key=lambda a: (a.asset_type != AssetType.VIDEO, -(a.id or 0)),
            )
        ],
    )


@router.get("/{episode_id}/replay", response_model=EpisodeReplayResponse)
async def replay_episode(
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Reconstruct a failed episode from persisted artifacts and traces."""
    result = await db.execute(
        select(Episode)
        .where(Episode.id == episode_id)
        .options(selectinload(Episode.traces), selectinload(Episode.assets))
    )
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
    worker_session_id = metadata.worker_session_id or str(episode.id)
    worker_client = WorkerClient(
        base_url=settings.worker_light_url,
        session_id=worker_session_id,
        heavy_url=settings.worker_heavy_url,
    )
    return await _build_episode_replay_response(
        episode=episode,
        worker_client=worker_client,
    )


@router.delete("/{episode_id}")
async def delete_episode(episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete an episode and its associated data."""
    result = await db.execute(select(Episode).where(Episode.id == episode_id))
    episode = result.scalar_one_or_none()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    try:
        await db.delete(episode)
        await db.commit()
    except Exception as e:
        logger.warning(
            "delete_episode_failed", episode_id=str(episode_id), error=str(e)
        )
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete episode: {e!s}")

    return {
        "status": ResponseStatus.SUCCESS,
        "message": f"Episode {episode_id} and its traces/assets deleted.",
    }


@router.websocket("/{episode_id}/ws")
async def episode_websocket(
    websocket: WebSocket,
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    await manager.connect(episode_id, websocket)
    try:
        try:
            snapshot = await get_episode(episode_id, db)
        except HTTPException as exc:
            await websocket.send_json(
                {
                    "type": "error",
                    "episode_id": str(episode_id),
                    "message": exc.detail,
                    "status_code": exc.status_code,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            manager.disconnect(episode_id, websocket)
            await websocket.close(code=1008)
            return
        await websocket.send_json(
            {
                "type": "episode_snapshot",
                "episode_id": str(episode_id),
                "episode": snapshot.model_dump(mode="json"),
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        logger.info(
            "episode_snapshot_sent",
            episode_id=str(episode_id),
            trace_count=len(snapshot.traces or []),
            asset_count=len(snapshot.assets or []),
        )
        # Initial message
        await websocket.send_json(
            {
                "type": "log",
                "data": f"Subscribed to updates for episode {episode_id}",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        # Keep connection alive
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        manager.disconnect(episode_id, websocket)
    except Exception as e:
        manager.disconnect(episode_id, websocket)
        if _is_closed_websocket_error(e):
            logger.info(
                "episode_websocket_closed",
                episode_id=str(episode_id),
                error=str(e),
            )
            return
        logger.exception(
            "episode_websocket_error",
            episode_id=str(episode_id),
            error=str(e),
        )
        raise


@router.websocket("/{episode_id}/simulation-stream/ws")
async def episode_simulation_stream_websocket(
    websocket: WebSocket,
    episode_id: uuid.UUID,
):
    session_id = websocket.headers.get("x-session-id")
    if not session_id:
        await websocket.accept()
        await websocket.close(code=1008)
        return

    await websocket.accept()
    logger.info(
        "episode_simulation_stream_connected",
        episode_id=str(episode_id),
        session_id=session_id,
    )

    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                payload = SimulationFrameStreamMessage.model_validate_json(raw_message)
            except Exception as exc:
                logger.warning(
                    "episode_simulation_stream_message_invalid",
                    episode_id=str(episode_id),
                    session_id=session_id,
                    error=str(exc),
                )
                continue

            if payload.episode_id != str(episode_id):
                logger.warning(
                    "episode_simulation_stream_episode_mismatch",
                    episode_id=str(episode_id),
                    payload_episode_id=payload.episode_id,
                    session_id=session_id,
                )
                continue

            await manager.broadcast(
                episode_id,
                {
                    **payload.model_dump(mode="json"),
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
    except WebSocketDisconnect:
        logger.info(
            "episode_simulation_stream_disconnected",
            episode_id=str(episode_id),
            session_id=session_id,
        )
    except Exception as exc:
        if _is_closed_websocket_error(exc):
            logger.info(
                "episode_simulation_stream_closed",
                episode_id=str(episode_id),
                session_id=session_id,
                error=str(exc),
            )
            return
        logger.exception(
            "episode_simulation_stream_error",
            episode_id=str(episode_id),
            session_id=session_id,
            error=str(exc),
        )
        raise


@router.post("/{episode_id}/interrupt")
async def interrupt_episode(episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Interrupt a running episode."""
    # 1. Cancel the asyncio task
    task = task_tracker.get_task(episode_id)
    if task and not task.done():
        logger.info("cancelling_episode_task", episode_id=str(episode_id))
        task.cancel()
    else:
        logger.warning("task_not_found_or_already_done", episode_id=str(episode_id))

    # 2. Update status in DB immediately (failsafe)
    # The cancelled task exception handler in main.py will also do this,
    # but we do it here to give immediate feedback.
    result = await db.execute(select(Episode).where(Episode.id == episode_id))
    episode = result.scalar_one_or_none()

    if episode and episode.status in [EpisodeStatus.RUNNING]:
        episode.status = EpisodeStatus.CANCELLED
        await db.commit()

        # Broadcast update
        await manager.broadcast(
            episode_id,
            {
                "type": "status_update",
                "status": EpisodeStatus.CANCELLED,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    return {"status": ResponseStatus.ACCEPTED, "message": "Interruption requested"}
