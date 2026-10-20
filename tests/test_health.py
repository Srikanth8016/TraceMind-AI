"""
Tests for the /health endpoint.

We use FastAPI's built-in TestClient (which wraps httpx) to spin up the
application *in-process* — no network port is needed, no server process to
start.  This keeps the test suite fast and hermetic.

The ``client`` fixture is defined in ``conftest.py`` and shared across all
test modules.  Using the shared fixture ensures the DB dependency override
from conftest is active (so importing app.database does not fail even if
DATABASE_URL points to a real but unreachable PostgreSQL).
"""

import pytest
from fastapi.testclient import TestClient

# ``client`` fixture is defined in tests/conftest.py and injected by pytest.


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
