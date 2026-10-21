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
