import contextlib
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from controller.observability.broadcast import EpisodeBroadcaster
from controller.observability.tracing import record_worker_events, sync_asset
from shared.enums import FailureReason as SimulationFailureMode
from shared.observability.schemas import SimulationResultEvent

logger = structlog.get_logger(__name__)


async def record_events(episode_id: str, events: list[Any]):
    """Proxy to record_worker_events."""
    await record_worker_events(episode_id=episode_id, events=events)


async def broadcast_file_update(episode_id_str: str, path: str, content: str):
    """Broadcast file update to frontend and sync to Asset table."""
    global logger
    if "logger" not in globals() or logger is None:
        logger = structlog.get_logger(__name__)
    try:
        # Sync to Asset table first to get DB record.
        # sync_asset now handles prefixed UUID strings.
        asset = await sync_asset(episode_id_str, path, content)

        # We still need a UUID for broadcasting via EpisodeBroadcaster
        # Use the centralized helper for consistency
        from controller.utils import get_episode_id

        episode_id = get_episode_id(episode_id_str)

        payload = {
            "type": "file_update",
            "data": {
                "path": path,
                "content": content,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if asset:
            payload["data"].update(
                {
                    "id": asset.id,
                    "asset_type": asset.asset_type,
                    "created_at": asset.created_at.isoformat()
                    if asset.created_at
                    else None,
                }
            )

        await EpisodeBroadcaster.get_instance().broadcast(episode_id, payload)
    except ValueError:
        # If session_id is not a UUID, we can't broadcast (standard in some dev/test setups)
        pass
    except Exception as e:
        logger.warning("broadcast_file_update_failed", error=str(e), path=path)
        # Don't fail the write operation if broadcast fails
        pass


async def sync_file_asset(episode_id_str: str, path: str, content: str):
    """Sync file content to Asset table."""
    with contextlib.suppress(Exception):
        await sync_asset(episode_id_str, path, content)


def _simulation_result_to_dict(res: Any) -> dict[str, Any]:
    if hasattr(res, "model_dump"):
        return res.model_dump(mode="json")
    if isinstance(res, dict):
        return res
    return dict(res)


def map_simulation_failure_reason(res_dict: dict[str, Any]) -> SimulationFailureMode:
    """Map raw failure reasons from simulation result to SimulationFailureMode enum."""
    if res_dict.get("success", True):
        return SimulationFailureMode.NONE

    # Structured failure from SimulationFailure model
    failure_data = res_dict.get("failure")
    if isinstance(failure_data, dict) and "reason" in failure_data:
        try:
            return SimulationFailureMode(failure_data["reason"])
        except ValueError:
            pass

    raw_reason = str(res_dict.get("failure_reason") or "").upper()
    if "TIMEOUT" in raw_reason:
        return SimulationFailureMode.TIMEOUT
    if "OUT_OF_BOUNDS" in raw_reason:
        return SimulationFailureMode.OUT_OF_BOUNDS
    if "FORBID" in raw_reason:
        return SimulationFailureMode.FORBID_ZONE_HIT
    if "BREAK" in raw_reason or "STRESS" in raw_reason:
        return SimulationFailureMode.PART_BREAKAGE
    if "NAN" in raw_reason or "INSTABILITY" in raw_reason:
        return SimulationFailureMode.PHYSICS_INSTABILITY
    if "PAYLOAD_TRAJECTORY" in raw_reason:
        return SimulationFailureMode.PAYLOAD_TRAJECTORY_CONTRACT_VIOLATION

    return SimulationFailureMode.NONE


async def record_simulation_result(episode_id: str, res: Any):
    """Records simulation result and instability events."""
    res_dict = _simulation_result_to_dict(res)
    failure_reason = map_simulation_failure_reason(res_dict)
    simulation_run_id = uuid.uuid4().hex

    await record_worker_events(
        episode_id=episode_id,
        events=[
            SimulationResultEvent(
                success=res_dict.get("success", True),
                failure_reason=failure_reason,
                failure=res_dict.get("failure"),
                time_elapsed_s=res_dict.get("time_elapsed_s", 0.0),
                compute_time_ms=res_dict.get("compute_time_ms", 0.0),
                simulation_run_id=simulation_run_id,
                metadata=res_dict,
            )
        ],
    )

    # Instability long-tail telemetry is intentionally omitted in the pruned
    # publication bundle; the structured simulation result is the retained
    # observability surface.
