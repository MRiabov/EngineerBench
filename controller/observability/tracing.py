import uuid
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select

from controller.persistence.db import get_sessionmaker
from controller.persistence.models import Asset, Episode, Trace
from controller.utils import resolve_episode_id
from shared.enums import AssetType, TraceType
from shared.observability.schemas import BaseEvent

logger = structlog.get_logger(__name__)


async def record_worker_events(
    episode_id: str | uuid.UUID,
    events: list[dict[str, Any] | BaseEvent],
    langfuse_trace_id: str | None = None,
) -> None:
    """
    Persists structured events from worker execution into the database.

    Args:
        episode_id: The ID of the current episode (can be string or UUID).
        events: List of event dictionaries or BaseEvent models.
        langfuse_trace_id: Optional Langfuse trace ID to link the event.
    """
    if not events:
        return

    episode_uuid = resolve_episode_id(episode_id)

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        # Fetch user_session_id for denormalized storage
        episode_res = await db.execute(
            select(Episode).where(Episode.id == episode_uuid)
        )
        episode = episode_res.scalar_one_or_none()
        if episode is None:
            logger.warning(
                "record_worker_events_skipped_missing_episode",
                episode_id=str(episode_uuid),
                event_count=len(events),
            )
            return
        user_session_id = episode.user_session_id if episode else None

        logger.info(
            "recording_events",
            count=len(events),
            episode_id=str(episode_uuid),
            user_session_id=str(user_session_id),
        )

        for event in events:
            if isinstance(event, BaseEvent):
                # Serialize model
                event_dict = event.model_dump(mode="json")
                name = event_dict.get("event_type", "generic_event")
                # content can be a string representation for searchability
                content = str(event_dict.get("data", event_dict))
                metadata = event_dict
                # Use user_session_id from event if present, otherwise from episode
                event_user_session_id = (
                    uuid.UUID(event.user_session_id)
                    if event.user_session_id
                    else user_session_id
                )
                logger.info(
                    "event_ids",
                    name=name,
                    event_user_session_id=str(event_user_session_id),
                )
                simulation_run_id = event_dict.get("simulation_run_id")
                review_id = event_dict.get("review_id")
            else:
                name = event.get("event_type", "generic_event")
                content = str(event.get("data", {}))
                metadata = event
                event_user_session_id = (
                    uuid.UUID(event.get("user_session_id"))
                    if event.get("user_session_id")
                    else user_session_id
                )
                simulation_run_id = event.get("simulation_run_id")
                review_id = event.get("review_id")

            if isinstance(metadata, dict) and not metadata.get("episode_id"):
                metadata = dict(metadata)
                metadata["episode_id"] = str(episode_uuid)

            trace = Trace(
                episode_id=episode_uuid,
                user_session_id=event_user_session_id,
                trace_type=TraceType.EVENT,
                name=name,
                content=content,
                metadata_vars=metadata,
                langfuse_trace_id=langfuse_trace_id,
                simulation_run_id=simulation_run_id,
                review_id=review_id,
            )
            db.add(trace)

        await db.commit()


async def sync_asset(
    episode_id: str | uuid.UUID,
    path: str | Path,
    content: str | None = None,
    asset_type: AssetType | None = None,
) -> Asset | None:
    """
    Syncs or creates an Asset record for a file change.

    Args:
        episode_id: The ID of the current episode.
        path: Path to the asset (relative to worker root).
        content: Optional content snippet or full content to cache.
        asset_type: Optional explicit AssetType. If None, inferred from extension.
    """
    episode_uuid = resolve_episode_id(episode_id)
    normalized_path = Path(path).as_posix().lstrip("/")
    if not normalized_path:
        normalized_path = Path(path).as_posix()

    if asset_type is None:
        p = Path(normalized_path)
        ext = p.suffix.lower()
        if ext == ".py":
            asset_type = AssetType.PYTHON
        elif ext in (".xml", ".mjcf"):
            asset_type = AssetType.MJCF
        elif ext in (".png", ".jpg", ".jpeg", ".webp"):
            asset_type = AssetType.IMAGE
        elif ext in (".glb", ".gltf"):
            asset_type = AssetType.GLB
        elif ext in (".stl",):
            asset_type = AssetType.STL
        elif ext in (".step", ".stp"):
            asset_type = AssetType.STEP
        elif ext in (".mp4", ".mov", ".avi", ".webm"):
            asset_type = AssetType.VIDEO
        elif ext in (".md", ".txt"):
            asset_type = AssetType.MARKDOWN
        elif ext in (".json", ".yaml", ".yml"):
            asset_type = AssetType.OTHER
        else:
            asset_type = AssetType.OTHER

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        # Fetch user_session_id for denormalized storage
        episode_res = await db.execute(
            select(Episode).where(Episode.id == episode_uuid)
        )
        episode = episode_res.scalar_one_or_none()
        user_session_id = episode.user_session_id if episode else None

        # Check if asset already exists
        stmt = select(Asset).where(
            Asset.episode_id == episode_uuid, Asset.s3_path == normalized_path
        )
        res = await db.execute(stmt)
        asset = res.scalar_one_or_none()

        if asset:
            asset.content = content
            asset.asset_type = asset_type
            asset.user_session_id = user_session_id
            logger.info(
                "sync_asset_updated",
                episode_id=str(episode_uuid),
                path=normalized_path,
                type=asset_type,
            )
        else:
            asset = Asset(
                episode_id=episode_uuid,
                user_session_id=user_session_id,
                s3_path=normalized_path,
                content=content,
                asset_type=asset_type,
            )
            db.add(asset)
            logger.info(
                "sync_asset_created",
                episode_id=str(episode_uuid),
                path=normalized_path,
                type=asset_type,
            )

        await db.commit()
        await db.refresh(asset)
        return asset
