import asyncio
import contextlib
import datetime
import json
import re
import uuid
from typing import Any

import structlog
from langchain_core.callbacks import BaseCallbackHandler
from opentelemetry import trace
from pydantic import BaseModel

from controller.config.settings import settings
from controller.observability.broadcast import EpisodeBroadcaster
from controller.persistence.db import get_sessionmaker
from controller.persistence.models import Trace
from controller.utils import resolve_episode_id
from shared.enums import TraceType
from shared.models.schemas import TraceMetadata

logger = structlog.get_logger(__name__)
_SYNC_TRACE_TIMEOUT_SECONDS = 0.25


def _should_block_for_sync_trace() -> bool:
    return not settings.is_integration_test


class TraceBroadcast(BaseModel):
    """Schema for broadcasting a trace event."""

    type: str = "new_trace"
    id: int | uuid.UUID
    created_at: str
    trace_type: TraceType
    name: str | None
    content: str | None
    metadata: dict[str, Any] | None
    langfuse_trace_id: str | None
    simulation_run_id: str | None = None
    review_id: str | None = None


class DatabaseCallbackHandler(BaseCallbackHandler):
    """Standalone recorder that stores explicit traces in the database."""

    def __init__(
        self,
        episode_id: str | uuid.UUID,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self.episode_id = resolve_episode_id(episode_id)
        self.session_factory = get_sessionmaker()
        self.broadcaster = EpisodeBroadcaster.get_instance()
        self._emitted_reasoning_by_node: dict[str, set[str]] = {}
        self.loop = loop or (
            asyncio.get_event_loop() if asyncio.get_event_loop().is_running() else None
        )

    async def _broadcast_trace(self, trace_obj: Trace) -> None:
        """Helper to broadcast a new trace."""
        created_at = trace_obj.created_at or datetime.datetime.now(datetime.UTC)
        payload = TraceBroadcast(
            id=trace_obj.id,
            created_at=created_at.isoformat(),
            trace_type=trace_obj.trace_type,
            name=trace_obj.name,
            content=trace_obj.content,
            metadata=trace_obj.metadata_vars,
            langfuse_trace_id=trace_obj.langfuse_trace_id,
            simulation_run_id=trace_obj.simulation_run_id,
            review_id=trace_obj.review_id,
        )
        await self.broadcaster.broadcast(
            self.episode_id, payload.model_dump(mode="json")
        )

    def _get_langfuse_id(self) -> str | None:
        """Extract trace ID from current OpenTelemetry span context."""
        try:
            span = trace.get_current_span()
            if span and span.get_span_context().is_valid:
                return f"{span.get_span_context().trace_id:032x}"
        except Exception:
            pass
        return None

    def _extract_reasoning_from_trajectory(
        self, trajectory: dict[str, Any]
    ) -> list[TraceMetadata]:
        """Extract thought-style reasoning steps from trajectory fields."""
        if not trajectory:
            return []

        pattern = re.compile(r"^thought_(\d+)$")
        by_index: dict[int, str] = {}
        for key, value in trajectory.items():
            match = pattern.match(str(key))
            if not match:
                continue
            idx_str = match.group(1)
            idx = int(idx_str)
            if isinstance(value, str) and value.strip():
                by_index[idx] = value.strip()

        steps: list[TraceMetadata] = []
        for idx in sorted(by_index):
            steps.append(
                TraceMetadata(
                    reasoning_step_index=idx,
                    reasoning_source="trajectory",
                    observation=by_index[idx],
                )
            )

        return steps

    def _extract_reasoning_from_fallback_text(
        self, output_data: str
    ) -> list[TraceMetadata]:
        """Fallback parser for reasoning embedded in stringified prediction."""
        if not output_data:
            return []

        steps: list[TraceMetadata] = []
        thought_matches = re.findall(
            r"thought_(\d+)['\"]?\s*:\s*['\"]([^'\"]+)['\"]", output_data
        )
        for raw_idx, thought in thought_matches:
            if thought and thought.strip():
                steps.append(
                    TraceMetadata(
                        reasoning_step_index=int(raw_idx),
                        reasoning_source="string_fallback",
                        observation=thought.strip(),
                    )
                )

        if steps:
            return steps

        reasoning_match = re.search(
            r"reasoning['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
            output_data,
            re.IGNORECASE,
        )
        if reasoning_match and reasoning_match.group(1).strip():
            steps.append(
                TraceMetadata(
                    reasoning_source="string_fallback",
                    observation=reasoning_match.group(1).strip(),
                )
            )

        return steps

    def _extract_reasoning_steps(
        self, output_data: str, output_obj: Any | None
    ) -> list[TraceMetadata]:
        """Structured-first extraction.

        Order: trajectory fields -> reasoning fields -> regex fallback on text.
        """
        steps: list[TraceMetadata] = []
        trajectory: dict[str, Any] | None = None
        reasoning_text: str | None = None
        reasoning_details: list[Any] | None = None

        candidate: Any = output_obj
        if candidate is None:
            candidate = output_data

        if isinstance(candidate, dict):
            maybe_trajectory = candidate.get("trajectory")
            trajectory = (
                maybe_trajectory if isinstance(maybe_trajectory, dict) else None
            )
            raw_reasoning = candidate.get("reasoning")
            if isinstance(raw_reasoning, str) and raw_reasoning.strip():
                reasoning_text = raw_reasoning.strip()
            raw_details = candidate.get("reasoning_details")
            if isinstance(raw_details, list):
                reasoning_details = raw_details
        elif hasattr(candidate, "model_dump"):
            with contextlib.suppress(Exception):
                dumped = candidate.model_dump()
                if isinstance(dumped, dict):
                    maybe_trajectory = dumped.get("trajectory")
                    trajectory = (
                        maybe_trajectory if isinstance(maybe_trajectory, dict) else None
                    )
                    raw_reasoning = dumped.get("reasoning")
                    if isinstance(raw_reasoning, str) and raw_reasoning.strip():
                        reasoning_text = raw_reasoning.strip()
                    raw_details = dumped.get("reasoning_details")
                    if isinstance(raw_details, list):
                        reasoning_details = raw_details

        if trajectory is None and hasattr(candidate, "trajectory"):
            maybe_trajectory = candidate.trajectory
            if isinstance(maybe_trajectory, dict):
                trajectory = maybe_trajectory

        if not reasoning_text and hasattr(candidate, "reasoning"):
            raw_reasoning = candidate.reasoning
            if isinstance(raw_reasoning, str) and raw_reasoning.strip():
                reasoning_text = raw_reasoning.strip()

        if trajectory:
            steps.extend(self._extract_reasoning_from_trajectory(trajectory))
        if steps:
            return steps

        if reasoning_details:
            for idx, detail in enumerate(reasoning_details):
                if not isinstance(detail, dict):
                    continue
                detail_text = detail.get("text")
                if not isinstance(detail_text, str) or not detail_text.strip():
                    continue
                detail_index = detail.get("index")
                step_index = detail_index if isinstance(detail_index, int) else idx
                steps.append(
                    TraceMetadata(
                        reasoning_step_index=step_index,
                        reasoning_source="reasoning_details",
                        observation=detail_text.strip(),
                    )
                )
            if steps:
                return steps

        if reasoning_text:
            steps.append(
                TraceMetadata(
                    reasoning_source="reasoning_field",
                    observation=reasoning_text,
                )
            )
            return steps

        return self._extract_reasoning_from_fallback_text(output_data)

    async def record_node_start(self, node_name: str, input_data: str = "") -> None:
        """Explicitly log the start of an agent node (e.g., Planner, Coder)."""
        logger.info("node_start", name=node_name, episode_id=str(self.episode_id))
        try:
            async with self.session_factory() as db:
                trace_obj = Trace(
                    episode_id=self.episode_id,
                    trace_type=TraceType.LOG,  # Use log for transitions
                    name=node_name,
                    content=(
                        f"Starting task phase: {node_name}. "
                        f"Input: {input_data[:100]}..."
                    ),
                    langfuse_trace_id=self._get_langfuse_id(),
                )
                db.add(trace_obj)
                await db.commit()
                await db.refresh(trace_obj)
                await self._broadcast_trace(trace_obj)
        except Exception as e:
            logger.warning(
                "database_trace_failed", error=str(e), episode_id=str(self.episode_id)
            )

    async def record_node_end(
        self, node_name: str, output_data: str = "", output_obj: Any | None = None
    ) -> None:
        """Explicitly log the end of an agent node."""
        logger.info("node_end", name=node_name, episode_id=str(self.episode_id))
        try:
            async with self.session_factory() as db:
                trace_obj = Trace(
                    episode_id=self.episode_id,
                    trace_type=TraceType.LOG,
                    name=node_name,
                    content=(
                        f"Completed task phase: {node_name}. "
                        f"Result: {output_data[:100]}..."
                    ),
                    langfuse_trace_id=self._get_langfuse_id(),
                )
                db.add(trace_obj)
                await db.commit()
                await db.refresh(trace_obj)
                await self._broadcast_trace(trace_obj)

                # Emit dedicated reasoning traces extracted from structured prediction
                # objects when available.
                reasoning_steps = self._extract_reasoning_steps(output_data, output_obj)
                live_emitted = self._emitted_reasoning_by_node.get(node_name, set())
                for step in reasoning_steps:
                    content = step.observation
                    if not content:
                        continue
                    if content in live_emitted:
                        continue

                    reasoning_trace = Trace(
                        episode_id=self.episode_id,
                        trace_type=TraceType.LLM_END,
                        name=node_name,
                        content=content,
                        metadata_vars=step.model_dump(mode="json"),
                        langfuse_trace_id=self._get_langfuse_id(),
                    )
                    db.add(reasoning_trace)
                    await db.commit()
                    await db.refresh(reasoning_trace)
                    await self._broadcast_trace(reasoning_trace)
        except Exception as e:
            logger.warning(
                "database_trace_failed", error=str(e), episode_id=str(self.episode_id)
            )

    async def record_reasoning_text(
        self,
        node_name: str,
        reasoning_text: str,
        step_index: int | None = None,
        source: str = "live_tool_loop",
    ) -> None:
        """Persist and broadcast a single live reasoning text chunk."""
        text = reasoning_text.strip()
        if not text:
            return

        node_key = str(node_name)
        seen = self._emitted_reasoning_by_node.setdefault(node_key, set())
        if text in seen:
            return

        metadata = TraceMetadata(
            reasoning_step_index=step_index,
            reasoning_source=source,
            observation=text,
        )

        try:
            async with self.session_factory() as db:
                reasoning_trace = Trace(
                    episode_id=self.episode_id,
                    trace_type=TraceType.LLM_END,
                    name=node_name,
                    content=text,
                    metadata_vars=metadata.model_dump(mode="json"),
                    langfuse_trace_id=self._get_langfuse_id(),
                )
                db.add(reasoning_trace)
                await db.commit()
                await db.refresh(reasoning_trace)
                await self._broadcast_trace(reasoning_trace)
                seen.add(text)
        except Exception as e:
            logger.warning("database_reasoning_trace_failed", error=str(e))

    async def record_tool_start(self, tool_name: str, input_data: str) -> int:
        """Explicitly log the start of a tool call."""
        try:
            async with self.session_factory() as db:
                trace_obj = Trace(
                    episode_id=self.episode_id,
                    trace_type=TraceType.TOOL_START,
                    name=tool_name,
                    content=input_data,
                    langfuse_trace_id=self._get_langfuse_id(),
                )
                db.add(trace_obj)
                await db.commit()
                await db.refresh(trace_obj)
                await self._broadcast_trace(trace_obj)
                return trace_obj.id
        except Exception as e:
            logger.warning("database_tool_start_failed", error=str(e))
            return 0

    async def record_tool_end(
        self, trace_id: int, output_data: str, is_error: bool = False
    ) -> None:
        """Explicitly log the end of a tool call, potentially updating metadata."""
        if not trace_id:
            return
        try:
            async with self.session_factory() as db:
                trace_obj = await db.get(Trace, trace_id)
                if trace_obj:
                    # For now, we update the existing TOOL_START trace with results
                    # to keep the UI simple (ActionCard can show output).
                    # Alternatively, we could create a TOOL_END trace.
                    from shared.models.schemas import TraceMetadata

                    metadata = TraceMetadata.model_validate(
                        trace_obj.metadata_vars or {}
                    )
                    if is_error:
                        metadata.error = output_data
                    else:
                        metadata.observation = output_data

                    trace_obj.metadata_vars = metadata.model_dump()
                    await db.commit()
                    await self._broadcast_trace(trace_obj)
        except Exception as e:
            logger.warning("database_tool_end_failed", error=str(e))

    def record_tool_start_sync(
        self,
        tool_name: str,
        input_data: str,
        *,
        force_block: bool = False,
    ) -> int:
        """Synchronous wrapper for record_tool_start."""
        try:
            if self.loop and self.loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self.record_tool_start(tool_name, input_data), self.loop
                )
                if force_block or _should_block_for_sync_trace():
                    return future.result(timeout=_SYNC_TRACE_TIMEOUT_SECONDS)
                return 0
            return asyncio.run(self.record_tool_start(tool_name, input_data))
        except Exception as e:
            logger.warning(
                "database_tool_start_sync_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            return 0

    def record_reasoning_text_sync(
        self,
        node_name: str,
        reasoning_text: str,
        step_index: int | None = None,
        source: str = "live_tool_loop",
    ) -> None:
        """Synchronous wrapper for live reasoning trace writes."""
        try:
            if self.loop and self.loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self.record_reasoning_text(
                        node_name=node_name,
                        reasoning_text=reasoning_text,
                        step_index=step_index,
                        source=source,
                    ),
                    self.loop,
                )
                if _should_block_for_sync_trace():
                    future.result(timeout=_SYNC_TRACE_TIMEOUT_SECONDS)
            else:
                asyncio.run(
                    self.record_reasoning_text(
                        node_name=node_name,
                        reasoning_text=reasoning_text,
                        step_index=step_index,
                        source=source,
                    )
                )
        except Exception as e:
            logger.warning(
                "database_reasoning_trace_sync_failed",
                error=str(e),
                error_type=type(e).__name__,
            )

    def record_tool_end_sync(
        self,
        trace_id: int,
        output_data: str,
        is_error: bool = False,
        *,
        force_block: bool = False,
    ) -> None:
        """Synchronous wrapper for record_tool_end."""
        if not trace_id:
            return
        try:
            if self.loop and self.loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self.record_tool_end(trace_id, output_data, is_error), self.loop
                )
                if force_block or _should_block_for_sync_trace():
                    future.result(timeout=_SYNC_TRACE_TIMEOUT_SECONDS)
            else:
                asyncio.run(self.record_tool_end(trace_id, output_data, is_error))
        except Exception as e:
            logger.warning(
                "database_tool_end_sync_failed",
                error=str(e),
                error_type=type(e).__name__,
            )

    # Keep generic event recording
    async def record_events(self, events: list[dict[str, Any]]) -> None:
        """Record domain-specific events in the database."""
        if not events:
            return

        try:
            async with self.session_factory() as db:
                for event_data in events:
                    data = event_data.get("data", {})
                    content = (
                        json.dumps(data)
                        if isinstance(data, (dict, list))
                        else str(data)
                    )
                    metadata = dict(event_data)
                    if not metadata.get("episode_id"):
                        metadata["episode_id"] = str(self.episode_id)

                    trace_obj = Trace(
                        episode_id=self.episode_id,
                        trace_type=TraceType.EVENT,
                        name=event_data.get("event_type", "generic_event"),
                        content=content,
                        metadata_vars=metadata,
                        langfuse_trace_id=self._get_langfuse_id(),
                        simulation_run_id=data.get("simulation_run_id"),
                        review_id=data.get("review_id"),
                    )
                    db.add(trace_obj)

                await db.commit()
        except Exception as e:
            logger.warning(
                "database_events_failed", error=str(e), episode_id=str(self.episode_id)
            )
