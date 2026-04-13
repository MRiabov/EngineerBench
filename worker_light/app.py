from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.logging import configure_logging, log_marker_middleware
from worker_heavy.api.routes import heavy_router
from worker_light.api.routes import light_router
from worker_light.config import settings

# Configure structured logging
configure_logging("worker-light")

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.skills_dir.mkdir(parents=True, exist_ok=True)

    yield


app = FastAPI(
    title="Problemologist Worker API (Light)",
    description="Sandboxed execution and filesystem API for agentic CAD tasks",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(PermissionError)
async def permission_error_handler(request: Request, exc: PermissionError):
    """Handle path traversal and other permission errors with 403."""
    return JSONResponse(
        status_code=403,
        content={"detail": str(exc)},
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


app.include_router(light_router, tags=["worker-light"])

# Support unified mode for integration tests
if os.getenv("WORKER_TYPE") == "unified":
    app.include_router(heavy_router, tags=["worker-heavy"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/")
async def root():
    """Root endpoint returning API information."""
    return {
        "name": "Problemologist Worker (Light)",
        "version": "0.1.0",
        "docs": "/docs",
    }
