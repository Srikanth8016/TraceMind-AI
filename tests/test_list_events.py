"""
tests/test_list_events.py — Tests for GET /api/v1/events (Milestone 4).

All tests run against an in-memory SQLite database via the dependency override
in conftest.py. No real PostgreSQL server is required.

Test categories covered:
1. Default pagination (limit=20, offset=0, total calculation)
2. Response schema stability (items, limit, offset, total)
3. Filtering by level
4. Filtering by service_name
5. Filtering by environment
6. Combined filters
7. Offset and limit pagination behavior
8. Total count accuracy (before pagination slice)
9. Empty results handling
10. Deterministic ordering (timestamp DESC, id DESC)
11. Query parameter validation (HTTP 422 on invalid level, limit, offset, lengths)
12. Route coexistence (GET list, POST create, GET detail, GET health)
"""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.models.event import Event
from tests.conftest import TestingSessionLocal, VALID_PAYLOAD


# ---------------------------------------------------------------------------
# Fixture: Seed test dataset
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def setup_events_dataset():
    """
    Populate a known dataset of 25 events with varied services, environments,
    levels, and timestamps to thoroughly test filtering, sorting, and pagination.
    """
    base_time = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
    events_to_insert = []

    # 10 events for service-auth
    # - 5 INFO (production)
    # - 3 WARNING (staging)
    # - 2 ERROR (production)
    for i in range(5):
        events_to_insert.append(
            Event(
                id=uuid.uuid4(),
                service_name="service-auth",
                environment="production",
                level="INFO",
                message=f"Auth info log {i}",
                timestamp=base_time + timedelta(minutes=i),
            )
        )
    for i in range(3):
        events_to_insert.append(
            Event(
                id=uuid.uuid4(),
                service_name="service-auth",
                environment="staging",
                level="WARNING",
                message=f"Auth warning log {i}",
                timestamp=base_time + timedelta(minutes=5 + i),
            )
        )
    for i in range(2):
        events_to_insert.append(
            Event(
                id=uuid.uuid4(),
                service_name="service-auth",
                environment="production",
                level="ERROR",
                message=f"Auth error log {i}",
                timestamp=base_time + timedelta(minutes=8 + i),
            )
        )

    # 10 events for service-payment (all production)
    # - 4 INFO
    # - 4 ERROR
    # - 2 CRITICAL
    for i in range(4):
        events_to_insert.append(
            Event(
                id=uuid.uuid4(),
                service_name="service-payment",
                environment="production",
                level="INFO",
                message=f"Payment info log {i}",
                timestamp=base_time + timedelta(minutes=10 + i),
            )
        )
    for i in range(4):
        events_to_insert.append(
            Event(
                id=uuid.uuid4(),
                service_name="service-payment",
                environment="production",
                level="ERROR",
                message=f"Payment error log {i}",
                timestamp=base_time + timedelta(minutes=14 + i),
            )
        )
    # Two CRITICAL events with the EXACT SAME timestamp to verify id.desc tie-breaking
    # Use hex digits containing letters (a-f) to prevent SQLite's NUMERIC column affinity
    # from coercing an all-numeric UUID string into a scientific-notation float (1e+32).
    tie_time = base_time + timedelta(minutes=18)
    id_lower = uuid.UUID("aaaaaaaa-1111-1111-1111-111111111111")
    id_higher = uuid.UUID("ffffffff-9999-9999-9999-999999999999")
    events_to_insert.append(
        Event(
            id=id_lower,
            service_name="service-payment",
            environment="production",
            level="CRITICAL",
            message="Payment critical failure low id",
            timestamp=tie_time,
        )
    )
    events_to_insert.append(
        Event(
            id=id_higher,
            service_name="service-payment",
            environment="production",
            level="CRITICAL",
            message="Payment critical failure high id",
            timestamp=tie_time,
        )
    )

    # 5 events for service-worker (all staging)
    # - 3 DEBUG
    # - 2 INFO
    for i in range(3):
        events_to_insert.append(
            Event(
                id=uuid.uuid4(),
                service_name="service-worker",
                environment="staging",
                level="DEBUG",
                message=f"Worker debug log {i}",
                timestamp=base_time + timedelta(minutes=20 + i),
            )
        )
    for i in range(2):
        events_to_insert.append(
            Event(
                id=uuid.uuid4(),
                service_name="service-worker",
                environment="staging",
                level="INFO",
                message=f"Worker info log {i}",
                timestamp=base_time + timedelta(minutes=23 + i),
            )
        )

    # Clear table and seed
    with TestingSessionLocal() as session:
        session.execute(delete(Event))
        session.add_all(events_to_insert)
        session.commit()

    yield

    # Clean up after module
    with TestingSessionLocal() as session:
        session.execute(delete(Event))
        session.commit()


# ===========================================================================
# 1. Default pagination & response schema
# ===========================================================================

class TestListEventsDefaultPagination:
    """Verifies default limit (20), offset (0), and stable schema shape."""

    def test_default_pagination_params(self, client: TestClient) -> None:
        response = client.get("/api/v1/events")
        assert response.status_code == 200
        body = response.json()

        assert body["limit"] == 20
        assert body["offset"] == 0
        assert body["total"] == 25
        assert len(body["items"]) == 20

    def test_response_item_fields(self, client: TestClient) -> None:
        response = client.get("/api/v1/events")
        assert response.status_code == 200
        first_item = response.json()["items"][0]

        expected_fields = {
            "id",
            "service_name",
            "environment",
            "level",
            "message",
            "timestamp",
            "created_at",
            "incident_id",
        }
        assert set(first_item.keys()) == expected_fields
        # Valid UUID
        uuid.UUID(first_item["id"])


# ===========================================================================
# 2. Filtering
# ===========================================================================

class TestListEventsFiltering:
    """Verifies server-side filtering on level, service_name, environment, and combinations."""

    def test_filter_by_level(self, client: TestClient) -> None:
        # Total CRITICAL events = 2
        response = client.get("/api/v1/events?level=CRITICAL")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        assert all(item["level"] == "CRITICAL" for item in body["items"])

    def test_filter_by_service_name(self, client: TestClient) -> None:
        # Total service-worker events = 5
        response = client.get("/api/v1/events?service_name=service-worker")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 5
        assert len(body["items"]) == 5
        assert all(item["service_name"] == "service-worker" for item in body["items"])

    def test_filter_by_environment(self, client: TestClient) -> None:
        # Total staging events = 3 (auth) + 5 (worker) = 8
        response = client.get("/api/v1/events?environment=staging")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 8
        assert len(body["items"]) == 8
        assert all(item["environment"] == "staging" for item in body["items"])

    def test_combined_filters(self, client: TestClient) -> None:
        # service-auth + production + ERROR = 2 events
        response = client.get(
            "/api/v1/events?service_name=service-auth&environment=production&level=ERROR"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        for item in body["items"]:
            assert item["service_name"] == "service-auth"
            assert item["environment"] == "production"
            assert item["level"] == "ERROR"

    def test_empty_results_no_matching_service(self, client: TestClient) -> None:
        response = client.get("/api/v1/events?service_name=unknown-service")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["items"] == []
        assert body["limit"] == 20
        assert body["offset"] == 0

    def test_empty_results_mismatched_filter(self, client: TestClient) -> None:
        # service-worker has no ERROR events
        response = client.get("/api/v1/events?service_name=service-worker&level=ERROR")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["items"] == []


# ===========================================================================
# 3. Pagination & total count accuracy
# ===========================================================================

class TestListEventsPagination:
    """Verifies limit, offset, and pre-pagination total count behavior."""

    def test_custom_limit_and_offset(self, client: TestClient) -> None:
        response = client.get("/api/v1/events?limit=5&offset=10")
        assert response.status_code == 200
        body = response.json()
        assert body["limit"] == 5
        assert body["offset"] == 10
        assert body["total"] == 25
        assert len(body["items"]) == 5

    def test_last_page_partial(self, client: TestClient) -> None:
        # Total is 25, offset 20 with limit 10 returns remaining 5
        response = client.get("/api/v1/events?limit=10&offset=20")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 25
        assert len(body["items"]) == 5

    def test_offset_beyond_total(self, client: TestClient) -> None:
        response = client.get("/api/v1/events?limit=10&offset=100")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 25
        assert body["items"] == []
        assert body["offset"] == 100

    def test_total_computed_before_limit_offset(self, client: TestClient) -> None:
        # For level=ERROR, total is 6. With limit=2, total must still be 6.
        response = client.get("/api/v1/events?level=ERROR&limit=2&offset=0")
        assert response.status_code == 200
        body = response.json()
        assert body["limit"] == 2
        assert len(body["items"]) == 2
        assert body["total"] == 6


# ===========================================================================
# 4. Deterministic ordering
# ===========================================================================

class TestListEventsOrdering:
    """Verifies timestamp DESC and tie-breaker id DESC ordering."""

    def test_ordered_by_timestamp_descending(self, client: TestClient) -> None:
        response = client.get("/api/v1/events?limit=25")
        assert response.status_code == 200
        items = response.json()["items"]
        timestamps = [item["timestamp"] for item in items]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_deterministic_tie_breaker_id_desc(self, client: TestClient) -> None:
        # We seeded two CRITICAL events with the exact same timestamp
        response = client.get("/api/v1/events?level=CRITICAL")
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 2
        assert items[0]["timestamp"] == items[1]["timestamp"]
        # Higher UUID string must come first
        assert items[0]["id"] > items[1]["id"]


# ===========================================================================
# 5. Query parameter validation (HTTP 422)
# ===========================================================================

class TestListEventsValidation:
    """Verifies that invalid query parameters return HTTP 422."""

    def test_invalid_level_returns_422(self, client: TestClient) -> None:
        response = client.get("/api/v1/events?level=VERBOSE")
        assert response.status_code == 422

    def test_lowercase_level_returns_422(self, client: TestClient) -> None:
        response = client.get("/api/v1/events?level=error")
        assert response.status_code == 422

    def test_limit_zero_returns_422(self, client: TestClient) -> None:
        response = client.get("/api/v1/events?limit=0")
        assert response.status_code == 422

    def test_limit_negative_returns_422(self, client: TestClient) -> None:
        response = client.get("/api/v1/events?limit=-1")
        assert response.status_code == 422

    def test_limit_above_max_returns_422(self, client: TestClient) -> None:
        response = client.get("/api/v1/events?limit=101")
        assert response.status_code == 422

    def test_offset_negative_returns_422(self, client: TestClient) -> None:
        response = client.get("/api/v1/events?offset=-1")
        assert response.status_code == 422

    def test_limit_not_an_integer_returns_422(self, client: TestClient) -> None:
        response = client.get("/api/v1/events?limit=twenty")
        assert response.status_code == 422

    def test_service_name_exceeds_max_length_returns_422(self, client: TestClient) -> None:
        long_service = "a" * 101
        response = client.get(f"/api/v1/events?service_name={long_service}")
        assert response.status_code == 422

    def test_environment_exceeds_max_length_returns_422(self, client: TestClient) -> None:
        long_env = "a" * 51
        response = client.get(f"/api/v1/events?environment={long_env}")
        assert response.status_code == 422


# ===========================================================================
# 6. Route coexistence regression
# ===========================================================================

class TestRouteCoexistence:
    """Ensures static /events route does not conflict with POST, detail GET, or health."""

    def test_post_and_get_detail_and_list_coexist(self, client: TestClient) -> None:
        # 1. POST a new event
        create_resp = client.post("/api/v1/events", json=VALID_PAYLOAD)
        assert create_resp.status_code in (201, 202)
        created_id = create_resp.json()["id"]

        # 2. GET the newly created event by UUID
        detail_resp = client.get(f"/api/v1/events/{created_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["id"] == created_id

        # 3. GET the collection endpoint
        list_resp = client.get("/api/v1/events")
        assert list_resp.status_code == 200
        assert "items" in list_resp.json()

        # 4. Liveness probe still works
        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json() == {"status": "healthy", "service": "tracemind-ai"}
