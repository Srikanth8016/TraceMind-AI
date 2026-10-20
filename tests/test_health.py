"""
Tests for the /health endpoint.

We use FastAPI's built-in TestClient (which wraps httpx) to spin up the
application *in-process* — no network port is needed, no server process to
start.  This keeps the test suite fast and hermetic.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """
    A single TestClient shared across all tests in this module.

    ``scope="module"`` means the client (and the ASGI app lifecycle) is
    created once and reused — important once we add startup/shutdown events.
    """
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """Group all /health assertions so pytest output is easy to read."""

    def test_status_code_is_200(self, client: TestClient) -> None:
        """A healthy service must return HTTP 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_content_type_is_json(self, client: TestClient) -> None:
        """The response must be JSON so consumers can parse it reliably."""
        response = client.get("/health")
        assert "application/json" in response.headers["content-type"]

    def test_status_field_is_healthy(self, client: TestClient) -> None:
        """The ``status`` field must equal 'healthy'."""
        response = client.get("/health")
        assert response.json()["status"] == "healthy"

    def test_service_field_identifies_platform(self, client: TestClient) -> None:
        """The ``service`` field must identify this service by name."""
        response = client.get("/health")
        assert response.json()["service"] == "tracemind-ai"

    def test_response_body_exact_shape(self, client: TestClient) -> None:
        """
        The full JSON body must match the documented contract exactly.

        This guards against accidental extra fields leaking into the response,
        which could break consumers that do strict schema validation.
        """
        response = client.get("/health")
        assert response.json() == {"status": "healthy", "service": "tracemind-ai"}
