"""
tests/test_logging.py — Tests for request correlation, secret redaction, and error handling.

Milestone 10: Production Readiness.

Verifies:
1. X-Request-ID is generated and returned on all HTTP requests.
2. Inbound X-Request-ID is preserved and propagated.
3. Secret redaction strips API keys, tokens, and database passwords from logs.
4. Global exception handler returns sanitized JSON 500 with request_id and no raw stack trace.
"""

from fastapi.testclient import TestClient
import pytest

from app.logging_config import redact_sensitive_text
from app.main import app


class TestLoggingAndCorrelation:
    """Tests for request correlation and sensitive data redaction."""

    def test_request_id_generated_when_missing(self, unauthenticated_client: TestClient) -> None:
        resp = unauthenticated_client.get("/health")
        assert resp.status_code == 200
        assert "X-Request-ID" in resp.headers
        req_id = resp.headers["X-Request-ID"]
        assert len(req_id) >= 16

    def test_inbound_request_id_preserved(self, unauthenticated_client: TestClient) -> None:
        custom_id = "trace-correlation-id-998877"
        resp = unauthenticated_client.get("/health", headers={"X-Request-ID": custom_id})
        assert resp.status_code == 200
        assert resp.headers["X-Request-ID"] == custom_id

    def test_invalid_request_id_sanitized_and_regenerated(self, unauthenticated_client: TestClient) -> None:
        # Test request ID containing invalid characters (spaces, special characters)
        malformed_id = "bad ID with spaces <script>"
        resp = unauthenticated_client.get("/health", headers={"X-Request-ID": malformed_id})
        assert resp.status_code == 200
        generated_id = resp.headers["X-Request-ID"]
        assert generated_id != malformed_id
        assert len(generated_id) >= 16

        # Test request ID exceeding 64 characters
        oversized_id = "a" * 65
        resp_over = unauthenticated_client.get("/health", headers={"X-Request-ID": oversized_id})
        assert resp_over.status_code == 200
        assert resp_over.headers["X-Request-ID"] != oversized_id

    def test_secret_redaction(self) -> None:
        # Test Groq key redaction
        groq_text = "Encountered error with key gsk_123456789012345678901234567890abcdef during inference"
        assert "[REDACTED_GROQ_KEY]" in redact_sensitive_text(groq_text)
        assert "gsk_123456789012345678901234567890abcdef" not in redact_sensitive_text(groq_text)

        # Test OpenAI key redaction
        openai_text = "API connection failed with token sk-abcdef1234567890abcdef123456"
        assert "[REDACTED_API_KEY]" in redact_sensitive_text(openai_text)

        # Test Bearer token redaction
        bearer_text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.signature"
        assert "Bearer [REDACTED_TOKEN]" in redact_sensitive_text(bearer_text)

        # Test database connection string password redaction
        db_text = "Connecting to postgresql+psycopg://tracemind:super_secret_pw@db.internal:5432/tracemind"
        redacted_db = redact_sensitive_text(db_text)
        assert "super_secret_pw" not in redacted_db
        assert "tracemind:***@" in redacted_db

        # Test JSON password field redaction
        payload_text = '{"username": "admin", "password": "supersecretpassword123"}'
        redacted_payload = redact_sensitive_text(payload_text)
        assert "supersecretpassword123" not in redacted_payload
        assert '"password": "[REDACTED]"' in redacted_payload

    def test_preserved_http_exceptions(self, unauthenticated_client: TestClient) -> None:
        # 401 on protected endpoint without credentials
        resp_401 = unauthenticated_client.get("/auth/me")
        assert resp_401.status_code == 401
        assert "X-Request-ID" in resp_401.headers

        # 404 on nonexistent route
        resp_404 = unauthenticated_client.get("/api/v1/nonexistent-route-xyz")
        assert resp_404.status_code == 404
        assert "X-Request-ID" in resp_404.headers

        # 422 on schema validation error
        resp_422 = unauthenticated_client.post("/auth/login", json={"invalid": "payload"})
        assert resp_422.status_code == 422
        assert "X-Request-ID" in resp_422.headers

    def test_metrics_endpoint_and_duration_measurement(self, unauthenticated_client: TestClient) -> None:
        # Trigger a request to ensure metrics get recorded
        unauthenticated_client.get("/health")

        resp = unauthenticated_client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_requests" in data
        assert data["total_requests"] >= 1
        assert "avg_latency_ms" in data
        assert "uptime_seconds" in data
        assert "status_counts" in data
        assert "X-Request-ID" in resp.headers

    def test_global_exception_handler_returns_safe_500(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Simulate unhandled exception in an endpoint
        def raise_unhandled():
            raise RuntimeError("Database pool deadlock or critical memory fault")

        monkeypatch.setattr("app.main.check_db_connection", raise_unhandled)

        # Starlette TestClient by default re-raises 500 exceptions in Python unless raise_server_exceptions=False
        test_client = TestClient(app, raise_server_exceptions=False)
        resp = test_client.get("/ready", headers={"X-Request-ID": "test-err-req-123"})
        assert resp.status_code == 500
        data = resp.json()
        assert data["detail"] == "Internal server error. Please contact system support."
        assert data["request_id"] == "test-err-req-123"
        # Verify stack trace is NOT exposed in the JSON response
        assert "RuntimeError" not in str(data)
        assert "deadlock" not in str(data)

