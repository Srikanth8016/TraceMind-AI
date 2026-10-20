"""
TraceMind AI — FastAPI application entry point.

Milestone 1: Minimal skeleton with a /health liveness probe.
All future features (auth, LLM, DB) will be added as separate routers.
"""

from fastapi import FastAPI

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
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health_check() -> dict[str, str]:
    """
    Liveness probe.

    Returns a simple JSON payload that load balancers, container orchestrators
    (e.g. Kubernetes), and monitoring systems can poll to confirm the service
    is running and reachable.

    Returns
    -------
    dict
        ``{"status": "healthy", "service": "tracemind-ai"}``
    """
    return {"status": "healthy", "service": "tracemind-ai"}
