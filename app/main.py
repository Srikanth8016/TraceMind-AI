"""
TraceMind AI — FastAPI application entry point.

Milestone 1: Minimal skeleton with a /health liveness probe.
Milestone 2: POST /api/v1/events event ingestion.
Milestone 3: PostgreSQL persistence; /health/db readiness probe added.

Design: /health stays a pure liveness probe (no DB dependency).
        /health/db is a separate readiness probe that checks PostgreSQL.
        Container orchestrators can poll both independently.
"""

from fastapi import Depends, FastAPI

from app.auth import verify_api_key
from app.routers import events as events_router
from app.routers import incidents as incidents_router
from app.routers import investigations as investigations_router
from app.routers import jobs as jobs_router

# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------
# `title` and `version` surface in the auto-generated OpenAPI docs at /docs.
# They are not cosmetic — they become part of the API contract.
app = FastAPI(
    title="TraceMind AI",
    version="0.1.0",
    description="AI-powered software incident investigation platform.",
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
# Events, jobs, incidents, and investigations routers are mounted under /api/v1
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health_check() -> dict[str, str]:
    """
    Liveness probe.

    Returns a simple JSON payload that load balancers, container orchestrators
    (e.g. Kubernetes), and monitoring systems can poll to confirm the service
    is running and reachable.

    Deliberately does NOT check the database — if PostgreSQL goes down we do
    not want the pod restarted (liveness failure kills pods).  Use
    ``/health/db`` as a readiness probe instead.

    Returns
    -------
    dict
        ``{"status": "healthy", "service": "tracemind-ai"}``
    """
    return {"status": "healthy", "service": "tracemind-ai"}


@app.get("/health/db", tags=["ops"])
async def db_health_check() -> dict[str, str]:
    """
    Database readiness probe.

    Security & Access Design (Milestone 5)
    -------------------------------------
    This endpoint is intentionally kept PUBLIC (unauthenticated) so that
    container orchestrators (e.g. Kubernetes, AWS ECS, GCP Cloud Run) can poll
    pod readiness without managing or rotating application client API keys.

    Privacy & Information Leakage:
    - Never returns database credentials, connection strings, or host details.
    - Catches all DB exceptions internally and returns a sanitized status
      ("connected" or "unreachable").
    - Never exposes stack traces or internal query errors.

    Returns
    -------
    dict
        ``{"status": "ok", "database": "connected"}`` on success.
        ``{"status": "degraded", "database": "unreachable"}`` on failure
        (HTTP 503).
    """
    from fastapi.responses import JSONResponse

    from app.database import check_db_connection

    if check_db_connection():
        return {"status": "ok", "database": "connected"}

    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "database": "unreachable"},
    )
