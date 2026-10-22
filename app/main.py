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
from typing import Any
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import verify_api_key
from app.celery_app import check_redis_connection
from app.config import get_settings
from app.database import check_db_connection
from app.logging_config import request_id_ctx, sanitize_request_id, setup_logging
from app.metrics import get_metrics_snapshot, record_request_metric
from app.routers import auth as auth_router
from app.routers import events as events_router
from app.routers import incidents as incidents_router
from app.routers import investigations as investigations_router
from app.routers import jobs as jobs_router
from app.routers import knowledge as knowledge_router
from app.routers import webhooks as webhooks_router
from app.routers import workspaces as workspaces_router
from app.services.incident_service import (
    IncidentConflictError,
    IncidentDatabaseError,
    IncidentInvalidTransitionError,
    IncidentNotFoundError,
    IncidentValidationError,
)
from app.services.rbac import (
    DuplicateMemberError,
    LastAdminError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.services.user_service import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
    UserInactiveError,
)

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


tags_metadata = [
    {
        "name": "Authentication",
        "description": "User registration, login, JWT token issuance, and profile management.",
    },
    {
        "name": "incidents",
        "description": "Deterministic incident grouping, management, and lifecycle workflow.",
    },
    {
        "name": "events",
        "description": "Ingest and query error events.",
    },
    {
        "name": "investigations",
        "description": "AI-powered root-cause investigation jobs.",
    },
    {
        "name": "knowledge",
        "description": "Runbook ingestion and semantic vector retrieval.",
    },
    {
        "name": "jobs",
        "description": "Asynchronous background task status polling.",
    },
]

app = FastAPI(
    title="TraceMind AI",
    version="0.1.0",
    description="AI-powered software incident investigation platform.",
    lifespan=lifespan,
    openapi_tags=tags_metadata,
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
    Extract, sanitize, or generate X-Request-ID and inject it into logging contextvar.
    Emits access log line with latency and status code.
    Quiets successful health check probes at DEBUG level to reduce production log noise.
    Records operational metrics and catches unhandled exceptions to return safe 500s.
    """
    raw_incoming = request.headers.get("X-Request-ID") or request.headers.get("x-request-id")
    req_id = sanitize_request_id(raw_incoming)
    request.state.request_id = req_id
    request.scope["request_id"] = req_id
    token = request_id_ctx.set(req_id)
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
    finally:
        request_id_ctx.reset(token)

    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
    response.headers["X-Request-ID"] = req_id
    record_request_metric(request.method, request.url.path, response.status_code, latency_ms)

    # Quiet successful routine health probes to avoid noisy log spam
    is_health_probe = request.url.path in ("/health", "/health/db", "/ready", "/metrics")
    if is_health_probe and response.status_code == 200:
        logger.debug(
            "%s %s -> %d (%.2f ms)",
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
        )
    else:
        logger.info(
            "%s %s -> %d (%.2f ms)",
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
        )
    return response


# ---------------------------------------------------------------------------
# Centralized Error Handlers
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Standardize all HTTP exceptions with correlation request_id in headers.
    Preserves existing response structure and response headers (such as WWW-Authenticate).
    """
    req_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or request_id_ctx.get("-")
    )
    if not req_id or req_id == "-":
        req_id = str(uuid.uuid4())
    headers = dict(exc.headers) if exc.headers else {}
    headers["X-Request-ID"] = req_id
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=headers,
    )



def _sanitize_validation_errors(errors: list[Any]) -> list[Any]:
    sanitized = []
    for err in errors:
        if isinstance(err, dict):
            clean_err = {}
            for k, v in err.items():
                if k == "ctx" and isinstance(v, dict):
                    clean_err[k] = {ck: str(cv) if isinstance(cv, (Exception, type)) else cv for ck, cv in v.items()}
                elif isinstance(v, Exception):
                    clean_err[k] = str(v)
                else:
                    clean_err[k] = v
            sanitized.append(clean_err)
        else:
            sanitized.append(str(err))
    return sanitized


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Standardize schema validation errors with correlation request_id.
    """
    req_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or request_id_ctx.get("-")
    )
    if not req_id or req_id == "-":
        req_id = str(uuid.uuid4())
    logger.warning("Request validation error on %s %s: %s", request.method, request.url.path, exc.errors())
    sanitized_errors = jsonable_encoder(
        _sanitize_validation_errors(exc.errors()),
        custom_encoder={Exception: str},
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": sanitized_errors,
            "request_id": req_id,
        },
        headers={"X-Request-ID": req_id},
    )


@app.exception_handler(IncidentNotFoundError)
async def incident_not_found_handler(request: Request, exc: IncidentNotFoundError):
    """
    Centralized handler for IncidentNotFoundError -> HTTP 404.
    """
    req_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or request_id_ctx.get("-")
    )
    if not req_id or req_id == "-":
        req_id = str(uuid.uuid4())
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "detail": str(exc),
            "request_id": req_id,
        },
        headers={"X-Request-ID": req_id},
    )


@app.exception_handler(IncidentConflictError)
async def incident_conflict_handler(request: Request, exc: IncidentConflictError):
    """
    Centralized handler for IncidentConflictError -> HTTP 409.
    """
    req_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or request_id_ctx.get("-")
    )
    if not req_id or req_id == "-":
        req_id = str(uuid.uuid4())
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": str(exc),
            "request_id": req_id,
        },
        headers={"X-Request-ID": req_id},
    )


@app.exception_handler(IncidentDatabaseError)
async def incident_database_error_handler(request: Request, exc: IncidentDatabaseError):
    """
    Centralized handler for IncidentDatabaseError -> HTTP 500 without leaking SQL.
    """
    req_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or request_id_ctx.get("-")
    )
    if not req_id or req_id == "-":
        req_id = str(uuid.uuid4())
    logger.error("Incident database error: %s [req_id=%s]", exc, req_id)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "A database error occurred. Please contact system support.",
            "request_id": req_id,
        },
        headers={"X-Request-ID": req_id},
    )


@app.exception_handler(IncidentValidationError)
async def incident_validation_error_handler(request: Request, exc: IncidentValidationError):
    """
    Centralized handler for IncidentValidationError -> HTTP 422.
    """
    req_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or request_id_ctx.get("-")
    )
    if not req_id or req_id == "-":
        req_id = str(uuid.uuid4())
    logger.warning("Incident validation error: %s [req_id=%s]", exc, req_id)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": str(exc),
            "request_id": req_id,
        },
        headers={"X-Request-ID": req_id},
    )


@app.exception_handler(IncidentInvalidTransitionError)
async def incident_invalid_transition_handler(request: Request, exc: IncidentInvalidTransitionError):
    """
    Centralized handler for IncidentInvalidTransitionError -> HTTP 400 Bad Request.
    """
    req_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or request_id_ctx.get("-")
    )
    if not req_id or req_id == "-":
        req_id = str(uuid.uuid4())
    logger.warning("Invalid incident status transition: %s [req_id=%s]", exc, req_id)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": str(exc),
            "request_id": req_id,
        },
        headers={"X-Request-ID": req_id},
    )


@app.exception_handler(UserAlreadyExistsError)
async def user_already_exists_handler(request: Request, exc: UserAlreadyExistsError):
    """
    Centralized handler for UserAlreadyExistsError -> HTTP 409 Conflict.
    """
    req_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or request_id_ctx.get("-")
    )
    if not req_id or req_id == "-":
        req_id = str(uuid.uuid4())
    logger.warning("User registration conflict: %s [req_id=%s]", exc, req_id)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": str(exc),
            "request_id": req_id,
        },
        headers={"X-Request-ID": req_id},
    )


@app.exception_handler(InvalidCredentialsError)
async def invalid_credentials_handler(request: Request, exc: InvalidCredentialsError):
    """
    Centralized handler for InvalidCredentialsError -> HTTP 401 Unauthorized with Bearer header.
    """
    req_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or request_id_ctx.get("-")
    )
    if not req_id or req_id == "-":
        req_id = str(uuid.uuid4())
    logger.warning("Authentication failure: %s [req_id=%s]", exc, req_id)
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={
            "detail": str(exc),
            "request_id": req_id,
        },
        headers={
            "X-Request-ID": req_id,
            "WWW-Authenticate": "Bearer",
        },
    )


@app.exception_handler(UserInactiveError)
async def user_inactive_handler(request: Request, exc: UserInactiveError):
    """
    Centralized handler for UserInactiveError -> HTTP 403 Forbidden.
    """
    req_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or request_id_ctx.get("-")
    )
    if not req_id or req_id == "-":
        req_id = str(uuid.uuid4())
    logger.warning("Inactive user access attempt: %s [req_id=%s]", exc, req_id)
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "detail": str(exc),
            "request_id": req_id,
        },
        headers={"X-Request-ID": req_id},
    )


@app.exception_handler(WorkspaceNotFoundError)
async def workspace_not_found_handler(request: Request, exc: WorkspaceNotFoundError):
    req_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc), "request_id": req_id},
        headers={"X-Request-ID": req_id},
    )


@app.exception_handler(WorkspaceAccessDeniedError)
async def workspace_access_denied_handler(request: Request, exc: WorkspaceAccessDeniedError):
    req_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": str(exc), "request_id": req_id},
        headers={"X-Request-ID": req_id},
    )


@app.exception_handler(LastAdminError)
async def last_admin_handler(request: Request, exc: LastAdminError):
    req_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc), "request_id": req_id},
        headers={"X-Request-ID": req_id},
    )


@app.exception_handler(DuplicateMemberError)
async def duplicate_member_handler(request: Request, exc: DuplicateMemberError):
    req_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc), "request_id": req_id},
        headers={"X-Request-ID": req_id},
    )


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

# Authentication endpoints (Milestone 14: /auth/* and /api/v1/auth/*)
app.include_router(auth_router.router)
app.include_router(auth_router.router, prefix="/api/v1")

# Team Workspaces API (Milestone 17: Multi-tenant RBAC Workspaces)
app.include_router(
    workspaces_router.router,
    prefix="/api/v1",
)

# Inbound Webhooks API (Milestone 19: Datadog & PagerDuty Alert Ingestion)
app.include_router(
    webhooks_router.router,
    prefix="/api/v1",
)

# Incidents API (Milestone 14 & 17: Protected by JWT Bearer token & owner/workspace-scoped)
app.include_router(
    incidents_router.router,
    prefix="/api/v1",
)

# Events, jobs, investigations, and knowledge routers are mounted under /api/v1
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


@app.get("/metrics", tags=["ops"])
async def get_metrics() -> dict[str, Any]:
    """
    Lightweight operational telemetry endpoint.
    Returns request counts, 4xx/5xx error rates, uptime, and latency statistics.
    Never exposes internal secrets or database credentials.
    """
    return get_metrics_snapshot()

