import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from temporalio.client import Client

from controller.api import ops
from controller.api.manager import task_tracker
from controller.api.routes import (
    benchmark,
    cots,
    datasets,
    episodes,
    script_tools,
    skills,
)
from controller.config.settings import settings
from controller.observability.langfuse import get_langfuse_client
from controller.persistence.db import dispose_all_engines, get_sessionmaker
from controller.persistence.models import Asset, Episode, Trace
from shared.enums import EpisodeStatus, ResponseStatus
from shared.logging import configure_logging, get_logger, log_marker_middleware

# Configure logging
configure_logging("controller")
logger = get_logger(__name__)

# Initialize Langfuse client globally early to avoid "uninitialized" warnings
try:
    get_langfuse_client()
except Exception as e:
    logger.warning("failed_to_initialize_langfuse_globally", error=str(e))

TEMPORAL_URL = settings.temporal_url
WORKER_LIGHT_URL = settings.worker_light_url
TEMPORAL_CONNECT_MAX_ATTEMPTS = int(os.getenv("TEMPORAL_CONNECT_MAX_ATTEMPTS", "120"))
TEMPORAL_CONNECT_RETRY_SECONDS = float(
    os.getenv("TEMPORAL_CONNECT_RETRY_SECONDS", "1.0")
)

# Temporal client
temporal_client_instance: Client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global temporal_client_instance
    try:
        attempt = 0
        while True:
            try:
                temporal_client_instance = await Client.connect(TEMPORAL_URL)
                break
            except Exception as exc:
                attempt += 1
                if attempt >= TEMPORAL_CONNECT_MAX_ATTEMPTS:
                    raise RuntimeError(
                        f"Failed to connect to Temporal at {TEMPORAL_URL} "
                        f"after {TEMPORAL_CONNECT_MAX_ATTEMPTS} attempts"
                    ) from exc
                wait_s = min(TEMPORAL_CONNECT_RETRY_SECONDS * attempt, 10.0)
                logger.warning(
                    "temporal_connect_retry",
                    attempt=attempt,
                    max_attempts=TEMPORAL_CONNECT_MAX_ATTEMPTS,
                    error=str(exc),
                    retry_in_seconds=wait_s,
                    session_id="system",
                )
                await asyncio.sleep(wait_s)

        app.state.temporal_client = temporal_client_instance
        logger.info("connected_to_temporal", url=TEMPORAL_URL)
    except Exception as e:
        logger.error("failed_to_connect_to_temporal", error=str(e), session_id="system")
        raise

    yield

    await dispose_all_engines()


app = FastAPI(title="Problemologist Controller", lifespan=lifespan)
app.add_middleware(log_marker_middleware())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_unhandled_http_exceptions(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        logger.exception(
            "unhandled_http_exception",
            method=request.method,
            path=request.url.path,
            query=str(request.url.query),
        )
        raise


@app.get("/")
async def read_root():
    """Root endpoint for service discovery."""
    return {"status": "ok", "service": "controller"}


app.include_router(episodes.router, prefix="/api")
app.include_router(benchmark.router, prefix="/api")
app.include_router(datasets.router, prefix="/api")
app.include_router(script_tools.router, prefix="/api")
app.include_router(skills.router, prefix="/api")
app.include_router(ops.router, prefix="/api")
app.include_router(cots.router, prefix="/api")
# Backward compatibility for integration tests and legacy clients that use
# unprefixed controller routes.
app.include_router(episodes.router)
app.include_router(benchmark.router)
app.include_router(datasets.router)
app.include_router(script_tools.router)
app.include_router(skills.router)
app.include_router(ops.router)
app.include_router(cots.router)
from controller.api.routes import simulation

app.include_router(simulation.router, prefix="/api")
app.include_router(simulation.router)


from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    EpisodeCreateResponse,
    IntegrationTestStatusResponse,
)
from controller.api.tasks import execute_agent_task
from controller.utils import apply_integration_test_metadata, get_episode_id


@app.post("/api/test/episodes", status_code=201, response_model=EpisodeCreateResponse)
@app.post("/test/episodes", status_code=201, response_model=EpisodeCreateResponse)
async def create_test_episode(request: AgentRunRequest):
    """Create a dummy episode for testing purposes (no agent run)."""
    if not settings.is_integration_test:
        raise HTTPException(status_code=403, detail="Only allowed in integration tests")

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        # Ensure session_id is preserved in metadata
        from shared.models.schemas import EpisodeMetadata

        metadata = EpisodeMetadata.model_validate(request.metadata_vars or {})
        metadata.benchmark_id = (metadata.benchmark_id or "").strip() or None
        metadata.worker_session_id = request.session_id
        metadata.additional_info["reasoning_required"] = (
            settings.require_reasoning_traces
        )
        metadata = apply_integration_test_metadata(
            metadata,
            is_integration_test=settings.is_integration_test,
            task=request.task,
            session_id=request.session_id,
        )

        episode_id = get_episode_id(request.session_id)
        existing = await db.get(Episode, episode_id)
        if existing:
            # Reset deterministic test episodes so repeated runs start cleanly.
            await db.execute(delete(Trace).where(Trace.episode_id == episode_id))
            await db.execute(delete(Asset).where(Asset.episode_id == episode_id))
            existing.task = request.task
            existing.status = EpisodeStatus.RUNNING
            existing.metadata_vars = metadata.model_dump()
            existing.skill_git_hash = request.skill_git_hash
            existing.user_session_id = request.user_session_id
            existing.todo_list = None
            existing.journal = None
            existing.plan = None
            await db.commit()
            return EpisodeCreateResponse(episode_id=existing.id)

        episode = Episode(
            id=episode_id,
            task=request.task,
            status=EpisodeStatus.RUNNING,
            metadata_vars=metadata.model_dump(),
            skill_git_hash=request.skill_git_hash,
            user_session_id=request.user_session_id,
        )
        db.add(episode)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = await db.get(Episode, episode_id)
            if existing:
                return EpisodeCreateResponse(episode_id=existing.id)
            raise
        await db.refresh(episode)
        return EpisodeCreateResponse(episode_id=episode.id)


@app.get("/api/health")
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "is_integration_test": settings.is_integration_test,
    }


@app.get(
    "/api/test/is_integration_test",
    response_model=IntegrationTestStatusResponse,
)
@app.get("/test/is_integration_test", response_model=IntegrationTestStatusResponse)
async def is_integration_test():
    """Return whether the controller is running in integration-test mode."""
    return IntegrationTestStatusResponse(
        is_integration_test=settings.is_integration_test
    )


@app.post("/api/agent/run", status_code=202, response_model=AgentRunResponse)
@app.post("/agent/run", status_code=202, response_model=AgentRunResponse)
async def run_agent(request: AgentRunRequest):
    # Note: We removed BackgroundTasks - we use asyncio.create_task for granular control
    session_factory = get_sessionmaker()

    # Ensure session_id is preserved in metadata for asset proxying
    from shared.enums import EpisodeType
    from shared.models.schemas import EpisodeMetadata

    metadata = EpisodeMetadata.model_validate(request.metadata_vars or {})
    metadata.benchmark_id = (metadata.benchmark_id or "").strip() or None
    metadata.worker_session_id = request.session_id
    metadata.additional_info["reasoning_required"] = settings.require_reasoning_traces
    metadata.episode_type = EpisodeType.ENGINEER
    metadata = apply_integration_test_metadata(
        metadata,
        is_integration_test=settings.is_integration_test,
        task=request.task,
        session_id=request.session_id,
    )

    async with session_factory() as db:
        episode_id = get_episode_id(request.session_id)
        existing = await db.get(Episode, episode_id)
        if existing:
            # Keep deterministic integration/test session IDs re-runnable.
            await db.execute(delete(Trace).where(Trace.episode_id == episode_id))
            await db.execute(delete(Asset).where(Asset.episode_id == episode_id))
            existing.task = request.task
            existing.status = EpisodeStatus.RUNNING
            existing.metadata_vars = metadata.model_dump()
            existing.skill_git_hash = request.skill_git_hash
            existing.user_session_id = request.user_session_id
            existing.todo_list = None
            existing.journal = None
            existing.plan = None
            await db.commit()
            await db.refresh(existing)
        else:
            episode = Episode(
                id=episode_id,
                task=request.task,
                status=EpisodeStatus.RUNNING,
                metadata_vars=metadata.model_dump(),
                skill_git_hash=request.skill_git_hash,
                user_session_id=request.user_session_id,
            )
            db.add(episode)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                existing = await db.get(Episode, episode_id)
                if existing is None:
                    raise
                # Late collision: treat same as deterministic rerun.
                await db.execute(delete(Trace).where(Trace.episode_id == episode_id))
                await db.execute(delete(Asset).where(Asset.episode_id == episode_id))
                existing.task = request.task
                existing.status = EpisodeStatus.RUNNING
                existing.metadata_vars = metadata.model_dump()
                existing.skill_git_hash = request.skill_git_hash
                existing.user_session_id = request.user_session_id
                existing.todo_list = None
                existing.journal = None
                existing.plan = None
                await db.commit()
                await db.refresh(existing)
            else:
                await db.refresh(episode)

    # Create task and register it
    import asyncio

    task = asyncio.create_task(
        execute_agent_task(
            episode_id,
            request.task,
            request.session_id,
            agent_name=request.agent_name,
            start_node=request.start_node,
        )
    )
    task_tracker.register_task(episode_id, task)

    return AgentRunResponse(
        status=ResponseStatus.ACCEPTED,
        message="Agent execution started",
        episode_id=episode_id,
    )
