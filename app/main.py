"""
TraceMind AI — FastAPI application entry point.

Milestone 10: Production Readiness.
- Centralized configuration via app.config.Settings.
- Request correlation ID middleware (X-Request-ID).
- Structured logging with secret redaction.
- Public probes:
    - /health: Pure liveness probe (no DB/Redis dependencies).
    - /health/db: Backwards-compatible database readiness probe.
    - /ready: Full production readiness probe checking PostgreSQL and Redis.
- Protected API routes under /api/v1 (events, jobs, incidents, investigations, knowledge).
"""

from contextlib import asynccontextmanager
import logging
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import verify_api_key
from app.celery_app import check_redis_connection
from app.config import get_settings
from app.database import check_db_connection
from app.logging_config import request_id_ctx, setup_logging
from app.routers import events as events_router
from app.routers import incidents as incidents_router
from app.routers import investigations as investigations_router
from app.routers import jobs as jobs_router
from app.routers import knowledge as knowledge_router

settings = get_settings()
setup_logging(level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle management."""
    logger.info(
        "TraceMind AI starting up [environment=%s, demo_mode=%s, llm=%s, embed=%s]",
        settings.ENVIRONMENT.value,
        settings.DEMO_MODE,
        settings.LLM_PROVIDER,
        settings.EMBEDDING_PROVIDER,
    )
    yield
    logger.info("TraceMind AI shutting down.")


app = FastAPI(
    title="TraceMind AI",
    version="0.1.0",
    description="AI-powered software incident investigation platform.",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Cross-Origin Resource Sharing (CORS) Configuration
# ---------------------------------------------------------------------------
cors_origins = [orig.strip() for orig in settings.CORS_ORIGINS.split(",") if orig.strip()]
if not cors_origins or "*" in cors_origins:
    allow_origins = ["*"]
else:
    allow_origins = cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request Correlation & Timing Middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """
    Extract or generate X-Request-ID and inject it into the logging contextvar.
    Emits access log line with latency and status code.
    Catches unhandled exceptions to ensure safe 500 responses retain the correlation ID.
    """
    req_id = (
        request.headers.get("X-Request-ID")
        or request.headers.get("x-request-id")
        or str(uuid.uuid4())
    )
    request.state.request_id = req_id
    request.scope["request_id"] = req_id
    token = request_id_ctx.set(req_id)
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
    except HTTPException:
        raise
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.error(
            "Unhandled server exception during %s %s: %s (%.2f ms)",
            request.method,
            request.url.path,
            exc,
            latency_ms,
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Internal server error. Please contact system support.",
                "request_id": req_id,
            },
            headers={"X-Request-ID": req_id},
        )
    finally:
        request_id_ctx.reset(token)

    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
    response.headers["X-Request-ID"] = req_id
    logger.info(
        "%s %s -> %d (%.2f ms)",
        request.method,
        request.url.path,
        response.status_code,
        latency_ms,
    )
    return response


# ---------------------------------------------------------------------------
# Global Safe Exception Handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Safe catch-all error handler for ASGI-level errors.
    Logs sanitized exception with request_id and returns generic HTTP 500 without
    leaking internal stack traces, DB credentials, or tokens in production.
    """
    req_id = (
        getattr(request.state, "request_id", None)
        or request.scope.get("request_id")
        or request.headers.get("X-Request-ID")
        or request.headers.get("x-request-id")
        or request_id_ctx.get("-")
    )
    if not req_id or req_id == "-":
        req_id = str(uuid.uuid4())
    request_id_ctx.set(req_id)
    logger.error(
        "Unhandled server exception during %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error. Please contact system support.",
            "request_id": req_id,
        },
        headers={"X-Request-ID": req_id},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
# Events, jobs, incidents, investigations, and knowledge routers are mounted under /api/v1
# and protected with the verify_api_key security dependency.
app.include_router(
    events_router.router,
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
)
app.include_router(
    jobs_router.router,
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
)
app.include_router(
    incidents_router.router,
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
)
app.include_router(
    investigations_router.router,
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
)
app.include_router(
    knowledge_router.router,
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
)


# ---------------------------------------------------------------------------
# Health & Readiness Probes (Public / Unauthenticated)
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health_check() -> dict[str, str]:
    """
    Liveness probe.
    Returns HTTP 200 to confirm the web process is running.
    Deliberately does not touch PostgreSQL or Redis so dependency downtime
    does not cause orchestrators to kill the pod.
    """
    return {"status": "healthy", "service": "tracemind-ai"}


@app.get("/health/db", tags=["ops"])
async def db_health_check() -> JSONResponse:
    """
    Database readiness probe (backwards-compatible with Milestone 3).
    """
    if check_db_connection():
        return JSONResponse(status_code=200, content={"status": "ok", "database": "connected"})
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "degraded", "database": "unreachable"},
    )


@app.get("/ready", tags=["ops"])
async def readiness_check() -> JSONResponse:
    """
    Comprehensive readiness probe for production orchestrators (Render / Kubernetes / ECS).
    Verifies reachability of PostgreSQL and Redis.
    In DEMO_MODE, Redis is optional because background tasks execute in-process.
    Never exposes internal connection strings, credentials, or stack traces.
    """
    db_ok = check_db_connection()
    if settings.DEMO_MODE:
        redis_ok = True
        redis_status = "disabled (demo mode)"
    else:
        redis_ok = check_redis_connection()
        redis_status = "healthy" if redis_ok else "unreachable"

    is_ready = db_ok and redis_ok

    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    content = {
        "status": "ready" if is_ready else "unhealthy",
        "database": "healthy" if db_ok else "unreachable",
        "redis": redis_status,
    }
    return JSONResponse(status_code=status_code, content=content)
