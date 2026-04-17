import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.logging import configure_logging, log_marker_middleware
from shared.rendering import configure_headless_physics

configure_logging("worker-heavy")
headless_config = configure_headless_physics()
from worker_heavy.api.routes import (
    heavy_busy_payload,
    heavy_router,
    is_heavy_busy,
)
from worker_heavy.runtime.simulation_runner import shutdown_simulation_executor

logger = structlog.get_logger(__name__)
logger.info(
    "worker_heavy_bootstrap_headless_env",
    physics_backend=headless_config.physics_backend.value,
    physics_gl_backend=headless_config.physics_gl_backend.value,
    render_backend=headless_config.rendering.value,
    pyopengl_platform=os.environ.get("PYOPENGL_PLATFORM"),
    vtk_default_open_gl_window=os.environ.get("VTK_DEFAULT_OPENGL_WINDOW"),
    stack_profile=os.environ.get("PROBLEMOLOGIST_STACK_PROFILE"),
    s3_endpoint=os.environ.get("S3_ENDPOINT"),
    s3_endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        await shutdown_simulation_executor()


app = FastAPI(
    title="Problemologist Worker API (Heavy)",
    description="Heavy compute API (simulation, validation) for agentic CAD tasks",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(log_marker_middleware())

# Add CORS middleware
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


app.include_router(heavy_router, tags=["worker-heavy"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/ready")
async def ready_check():
    """Readiness endpoint for external admission/routing."""
    if is_heavy_busy():
        return JSONResponse(
            status_code=503, content={"status": "busy", **heavy_busy_payload()}
        )
    return {"status": "ready"}


@app.get("/")
async def root():
    """Root endpoint returning API information."""
    return {
        "name": "Problemologist Worker (Heavy)",
        "version": "0.1.0",
        "docs": "/docs",
    }
