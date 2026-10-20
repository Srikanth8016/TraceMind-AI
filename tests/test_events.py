"""
Tests for POST /api/v1/events and GET /api/v1/events/{event_id} — Milestone 3.

All tests run against an in-memory SQLite database via the dependency override
in conftest.py.  No real PostgreSQL server is required.

Test organisation
-----------------
Each test class covers a single behavioural concern:
  TestCreateEventSuccess     — happy-path creation + persistence
  TestGetEventSuccess        — successful retrieval
  TestGetEventNotFound       — 404 on unknown UUID
  TestMissingRequiredFields  — Pydantic validation (422)
  TestInvalidSeverityLevel   — enum validation (422)
  TestEmptyMessage           — string constraint validation (422)
  TestTimezoneValidation     — timezone guard (422)
  TestHealthEndpointRegression — ensures /health still works after milestone changes
"""

import uuid

import pytest
from fastapi.testclient import TestClient

# ``client`` and ``VALID_PAYLOAD`` come from conftest.py
from tests.conftest import VALID_PAYLOAD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def post_event(client: TestClient, payload: dict):
    """Thin wrapper so tests stay concise."""
    return client.post("/api/v1/events", json=payload)


# ===========================================================================
# Happy path — creation
# ===========================================================================

class TestCreateEventSuccess:
    """A well-formed payload must be accepted with HTTP 201 and persisted."""

    def test_returns_201(self, client: TestClient) -> None:
        """HTTP 201 or 202 is the accepted status for ingest."""
        response = post_event(client, VALID_PAYLOAD)
        assert response.status_code in (201, 202)

    def test_response_contains_id(self, client: TestClient) -> None:
        """The response must include a server-generated UUID ``id``."""
        response = post_event(client, VALID_PAYLOAD)
        body = response.json()
        assert "id" in body
        # Validate that it is a proper UUID string
        uuid.UUID(body["id"])  # raises ValueError if malformed

    def test_response_contains_created_at(self, client: TestClient) -> None:
        """The response must include a ``created_at`` timestamp set by the DB."""
        response = post_event(client, VALID_PAYLOAD)
        body = response.json()
        assert "created_at" in body
        assert body["created_at"] is not None

    def test_response_fields_match_input(self, client: TestClient) -> None:
        """Each application field in the response must match what we sent."""
        response = post_event(client, VALID_PAYLOAD)
        body = response.json()
        assert body["service_name"] == VALID_PAYLOAD["service_name"]
        assert body["environment"] == VALID_PAYLOAD["environment"]
        assert body["level"] == VALID_PAYLOAD["level"]
        assert body["message"] == VALID_PAYLOAD["message"]

    def test_all_severity_levels_accepted(self, client: TestClient) -> None:
        """Every valid SeverityLevel value must be accepted."""
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            payload = {**VALID_PAYLOAD, "level": level}
            response = post_event(client, payload)
            assert response.status_code in (201, 202), f"Level {level!r} was rejected"

    def test_each_event_gets_unique_id(self, client: TestClient) -> None:
        """Two separate POSTs must produce two different UUIDs."""
        r1 = post_event(client, VALID_PAYLOAD)
        r2 = post_event(client, VALID_PAYLOAD)
        assert r1.json()["id"] != r2.json()["id"]


# ===========================================================================
# Happy path — retrieval
# ===========================================================================

class TestGetEventSuccess:
    """A previously created event must be retrievable by its UUID."""

    def test_get_returns_200(self, client: TestClient) -> None:
        """GET on an existing event_id must return HTTP 200."""
        created = post_event(client, VALID_PAYLOAD).json()
        event_id = created["id"]
        response = client.get(f"/api/v1/events/{event_id}")
        assert response.status_code == 200

    def test_get_returns_correct_event(self, client: TestClient) -> None:
        """The retrieved event must match the original POST payload."""
        created = post_event(client, VALID_PAYLOAD).json()
        event_id = created["id"]
        retrieved = client.get(f"/api/v1/events/{event_id}").json()

        assert retrieved["id"] == event_id
        assert retrieved["service_name"] == VALID_PAYLOAD["service_name"]
        assert retrieved["environment"] == VALID_PAYLOAD["environment"]
        assert retrieved["level"] == VALID_PAYLOAD["level"]
        assert retrieved["message"] == VALID_PAYLOAD["message"]

    def test_get_response_includes_created_at(self, client: TestClient) -> None:
        """GET response must include the ``created_at`` field."""
        created = post_event(client, VALID_PAYLOAD).json()
        retrieved = client.get(f"/api/v1/events/{created['id']}").json()
        assert "created_at" in retrieved
        assert retrieved["created_at"] is not None


# ===========================================================================
# 404 — non-existent event
# ===========================================================================

class TestGetEventNotFound:
    """Requesting an unknown UUID must return HTTP 404."""

    def test_unknown_uuid_returns_404(self, client: TestClient) -> None:
        """A freshly generated UUID that was never stored must 404."""
        random_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/events/{random_id}")
        assert response.status_code == 404

    def test_404_response_contains_detail(self, client: TestClient) -> None:
        """The 404 body must include a ``detail`` field (FastAPI convention)."""
        random_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/events/{random_id}")
        body = response.json()
        assert "detail" in body

    def test_malformed_uuid_returns_422(self, client: TestClient) -> None:
        """
        A path parameter that is not a valid UUID string must return 422.

        FastAPI validates the ``uuid.UUID`` type annotation automatically
        before the route handler is called.
        """
        response = client.get("/api/v1/events/not-a-uuid-at-all")
        assert response.status_code == 422


# ===========================================================================
# Validation — missing required fields → 422
# ===========================================================================

class TestMissingRequiredFields:
    """Omitting any required field must produce HTTP 422."""

    @pytest.mark.parametrize("missing_field", [
        "service_name",
        "environment",
        "level",
        "message",
        "timestamp",
    ])
    def test_missing_field_returns_422(
        self, client: TestClient, missing_field: str
    ) -> None:
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != missing_field}
        response = post_event(client, payload)
        assert response.status_code == 422, (
            f"Expected 422 when '{missing_field}' is absent, got {response.status_code}"
        )


# ===========================================================================
# Validation — invalid severity level → 422
# ===========================================================================

class TestInvalidSeverityLevel:
    """An unrecognised severity string must be rejected."""

    def test_unknown_level_returns_422(self, client: TestClient) -> None:
        payload = {**VALID_PAYLOAD, "level": "VERBOSE"}
        assert post_event(client, payload).status_code == 422

    def test_lowercase_level_returns_422(self, client: TestClient) -> None:
        """Enum matching is case-sensitive; 'error' is not 'ERROR'."""
        payload = {**VALID_PAYLOAD, "level": "error"}
        assert post_event(client, payload).status_code == 422

    def test_empty_level_returns_422(self, client: TestClient) -> None:
        payload = {**VALID_PAYLOAD, "level": ""}
        assert post_event(client, payload).status_code == 422


# ===========================================================================
# Validation — empty / too-long message → 422
# ===========================================================================

class TestEmptyMessage:
    """String length constraints on ``message`` must be enforced."""

    def test_empty_message_returns_422(self, client: TestClient) -> None:
        payload = {**VALID_PAYLOAD, "message": ""}
        assert post_event(client, payload).status_code == 422

    def test_message_too_long_returns_422(self, client: TestClient) -> None:
        """5001-character message exceeds max_length=5000."""
        payload = {**VALID_PAYLOAD, "message": "x" * 5001}
        assert post_event(client, payload).status_code == 422

    def test_message_at_max_length_is_accepted(self, client: TestClient) -> None:
        """Exactly 5000 characters is the boundary — must pass."""
        payload = {**VALID_PAYLOAD, "message": "x" * 5000}
        assert post_event(client, payload).status_code in (201, 202)


# ===========================================================================
# Validation — timezone-naive timestamp → 422
# ===========================================================================

class TestTimezoneValidation:
    """A timestamp without timezone info is ambiguous and must be rejected."""

    def test_naive_timestamp_returns_422(self, client: TestClient) -> None:
        payload = {**VALID_PAYLOAD, "timestamp": "2024-06-15T14:30:00"}
        assert post_event(client, payload).status_code == 422

    def test_aware_timestamp_with_positive_offset_is_accepted(
        self, client: TestClient
    ) -> None:
        """A non-UTC but still timezone-aware timestamp must be accepted."""
        payload = {**VALID_PAYLOAD, "timestamp": "2024-06-15T14:30:00+05:30"}
        assert post_event(client, payload).status_code in (201, 202)

    def test_aware_utc_z_suffix_is_accepted(self, client: TestClient) -> None:
        """The 'Z' suffix (UTC) is valid ISO-8601 and must be accepted."""
        payload = {**VALID_PAYLOAD, "timestamp": "2024-06-15T14:30:00Z"}
        assert post_event(client, payload).status_code in (201, 202)


# ===========================================================================
# Regression guard — /health must still work
# ===========================================================================

class TestHealthEndpointRegression:
    """
    Ensures that Milestone 3 changes did not shadow or break /health.

    The liveness probe must remain DB-free.
    """

    def test_health_returns_200(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200

    def test_health_body_unchanged(self, client: TestClient) -> None:
        assert client.get("/health").json() == {
            "status": "healthy",
            "service": "tracemind-ai",
        }
