"""
tests/test_readiness.py — Tests for production liveness and readiness health checks.

Milestone 10: Production Readiness.

Verifies:
1. GET /health liveness probe returns HTTP 200 without DB/Redis dependencies.
2. GET /health/db returns 200 when database is healthy.
3. GET /health/db returns 503 when database is unreachable.
4. GET /ready returns 200 when both database and Redis are reachable.
5. GET /ready returns 503 when database is unreachable.
6. GET /ready returns 503 when Redis is unreachable.
7. Probe responses never leak connection strings, passwords, or credentials.
"""

from fastapi.testclient import TestClient
import pytest

from app.main import app


class TestHealthAndReadiness:
    """Tests for liveness and readiness probes."""

    def test_liveness_health_check_returns_200(self, unauthenticated_client: TestClient) -> None:
        """GET /health must return 200 without requiring auth or DB."""
        resp = unauthenticated_client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy", "service": "tracemind-ai"}

    def test_db_readiness_probe_healthy(self, unauthenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """GET /health/db returns 200 when check_db_connection is True."""
        monkeypatch.setattr("app.main.check_db_connection", lambda: True)
        resp = unauthenticated_client.get("/health/db")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "database": "connected"}

    def test_db_readiness_probe_unhealthy(self, unauthenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """GET /health/db returns 503 when check_db_connection is False."""
        monkeypatch.setattr("app.main.check_db_connection", lambda: False)
        resp = unauthenticated_client.get("/health/db")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unreachable"
        # Confirm no internal connection strings or secrets are leaked
        assert "password" not in str(data)
        assert "postgresql" not in str(data)

    def test_full_readiness_probe_both_healthy(
        self,
        unauthenticated_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GET /ready returns 200 when both DB and Redis are healthy."""
        monkeypatch.setattr("app.main.check_db_connection", lambda: True)
        monkeypatch.setattr("app.main.check_redis_connection", lambda: True)

        resp = unauthenticated_client.get("/ready")
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "ready",
            "database": "healthy",
            "redis": "healthy",
        }

    def test_full_readiness_probe_db_down(
        self,
        unauthenticated_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GET /ready returns 503 when database is down."""
        monkeypatch.setattr("app.main.check_db_connection", lambda: False)
        monkeypatch.setattr("app.main.check_redis_connection", lambda: True)

        resp = unauthenticated_client.get("/ready")
        assert resp.status_code == 503
        assert resp.json() == {
            "status": "unhealthy",
            "database": "unreachable",
            "redis": "healthy",
        }

    def test_full_readiness_probe_redis_down(
        self,
        unauthenticated_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GET /ready returns 503 when Redis is down."""
        monkeypatch.setattr("app.main.check_db_connection", lambda: True)
        monkeypatch.setattr("app.main.check_redis_connection", lambda: False)

        resp = unauthenticated_client.get("/ready")
        assert resp.status_code == 503
        assert resp.json() == {
            "status": "unhealthy",
            "database": "healthy",
            "redis": "unreachable",
        }
