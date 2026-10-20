"""
tests/test_auth.py — Tests for API-Key authentication and endpoint protection (Milestone 5).

Verifies:
1. Missing X-API-Key header returns HTTP 401.
2. Invalid X-API-Key header returns HTTP 401.
3. Empty / whitespace-only X-API-Key header returns HTTP 401.
4. Valid X-API-Key grants access (HTTP 200 / 201).
5. Unconfigured server key (missing or empty TRACEMIND_API_KEY) fails closed with HTTP 500.
6. Public health endpoints (/health, /health/db) remain accessible without credentials.
7. Health probes continue to function even if server authentication is unconfigured.
8. Authentication executes before request body parsing (401 before 422).
9. OpenAPI specification declares the X-API-Key security scheme.
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import TEST_API_KEY, VALID_PAYLOAD


# ===========================================================================
# 1. Protected endpoint authentication (401 vs 200/201)
# ===========================================================================

class TestEndpointProtection:
    """Verifies that all /api/v1/events routes enforce API key authentication."""

    def test_post_events_missing_key_returns_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        response = unauthenticated_client.post("/api/v1/events", json=VALID_PAYLOAD)
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API Key."}

    def test_get_events_list_missing_key_returns_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        response = unauthenticated_client.get("/api/v1/events")
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API Key."}

    def test_get_event_detail_missing_key_returns_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        some_uuid = str(uuid.uuid4())
        response = unauthenticated_client.get(f"/api/v1/events/{some_uuid}")
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API Key."}

    def test_invalid_api_key_returns_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        headers = {"X-API-Key": "completely-invalid-secret-key"}
        response = unauthenticated_client.get("/api/v1/events", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API Key."}

    def test_empty_api_key_returns_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        headers = {"X-API-Key": ""}
        response = unauthenticated_client.get("/api/v1/events", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API Key."}

    def test_whitespace_api_key_returns_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        headers = {"X-API-Key": "    "}
        response = unauthenticated_client.get("/api/v1/events", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API Key."}

    def test_valid_api_key_allows_listing_events(
        self, unauthenticated_client: TestClient
    ) -> None:
        headers = {"X-API-Key": TEST_API_KEY}
        response = unauthenticated_client.get("/api/v1/events", headers=headers)
        assert response.status_code == 200
        assert "items" in response.json()

    def test_valid_api_key_allows_creating_event(
        self, unauthenticated_client: TestClient
    ) -> None:
        headers = {"X-API-Key": TEST_API_KEY}
        response = unauthenticated_client.post(
            "/api/v1/events", json=VALID_PAYLOAD, headers=headers
        )
        assert response.status_code in (201, 202)
        assert response.json()["service_name"] == VALID_PAYLOAD["service_name"]


# ===========================================================================
# 2. Server configuration fail-closed behavior (500)
# ===========================================================================

class TestServerFailClosed:
    """Verifies that missing server configuration denies access with HTTP 500."""

    def test_missing_server_key_fails_closed(
        self, unauthenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate unconfigured server environment
        monkeypatch.delenv("TRACEMIND_API_KEY", raising=False)

        headers = {"X-API-Key": "some-key"}
        response = unauthenticated_client.get("/api/v1/events", headers=headers)
        assert response.status_code == 500
        assert response.json() == {
            "detail": "Authentication is unconfigured on the server."
        }

    def test_empty_server_key_fails_closed(
        self, unauthenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate whitespace-only server environment variable
        monkeypatch.setenv("TRACEMIND_API_KEY", "   ")

        headers = {"X-API-Key": "some-key"}
        response = unauthenticated_client.get("/api/v1/events", headers=headers)
        assert response.status_code == 500
        assert response.json() == {
            "detail": "Authentication is unconfigured on the server."
        }


# ===========================================================================
# 3. Public health endpoints
# ===========================================================================

class TestPublicHealthEndpoints:
    """Verifies that liveness and readiness probes remain public and unauthenticated."""

    def test_liveness_probe_accessible_without_key(
        self, unauthenticated_client: TestClient
    ) -> None:
        response = unauthenticated_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "service": "tracemind-ai"}

    def test_readiness_probe_accessible_without_key(
        self, unauthenticated_client: TestClient
    ) -> None:
        response = unauthenticated_client.get("/health/db")
        # In test suite with in-memory DB or active test connection:
        assert response.status_code in (200, 503)
        assert "database" in response.json()

    def test_health_endpoints_work_even_if_server_auth_unconfigured(
        self, unauthenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TRACEMIND_API_KEY", raising=False)

        # /health must remain functional so container orchestrators do not kill pods
        health_resp = unauthenticated_client.get("/health")
        assert health_resp.status_code == 200


# ===========================================================================
# 4. Authentication precedence (Auth runs before body validation)
# ===========================================================================

class TestAuthenticationPrecedence:
    """Verifies that authentication runs before request body validation and DB work."""

    def test_unauthenticated_request_fails_with_401_before_schema_validation(
        self, unauthenticated_client: TestClient
    ) -> None:
        # Send a malformed payload that would trigger HTTP 422 if evaluated
        malformed_payload = {"service_name": "", "level": "INVALID"}
        response = unauthenticated_client.post("/api/v1/events", json=malformed_payload)

        # Must fail with 401 Unauthorized, NOT 422 Unprocessable Entity
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API Key."}


# ===========================================================================
# 5. OpenAPI specification integration
# ===========================================================================

class TestOpenAPISecurityDocs:
    """Verifies that OpenAPI documentation advertises the X-API-Key security scheme."""

    def test_openapi_declares_api_key_scheme(
        self, unauthenticated_client: TestClient
    ) -> None:
        response = unauthenticated_client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()

        # Security schemes in components
        security_schemes = schema.get("components", {}).get("securitySchemes", {})
        assert any(
            s.get("type") == "apiKey"
            and s.get("name") == "X-API-Key"
            and s.get("in") == "header"
            for s in security_schemes.values()
        ), "OpenAPI must include apiKey securityScheme for X-API-Key header"

        # Protected routes must have security declared
        events_post_op = schema.get("paths", {}).get("/api/v1/events", {}).get("post", {})
        assert "security" in events_post_op
        assert len(events_post_op["security"]) > 0
