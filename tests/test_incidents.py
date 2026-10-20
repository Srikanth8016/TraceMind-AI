"""
tests/test_incidents.py — Tests for Milestone 7 (Deterministic incident grouping and event correlation).

Verifies:
1. Deterministic fingerprint stability and selective volatility normalization.
2. Distinct fingerprints for different services and environments.
3. Preservation of semantic numbers (HTTP status codes, ports) during normalization.
4. Grouping of matching ERROR and CRITICAL events into a single incident.
5. Incrementation of event_count and advancement of last_seen_at.
6. Incident severity escalation from ERROR to CRITICAL.
7. Non-error events (INFO, WARNING, DEBUG) do not create or link to incidents.
8. Time-window expiry: events separated by more than correlation window start a new incident.
9. Lifecycle handling: RESOLVED incidents do not absorb new events (a new OPEN incident is created).
10. Idempotency: re-running correlation on the same event never increments event_count twice.
11. Authentication enforcement on all /api/v1/incidents endpoints (401 without key).
12. GET /api/v1/incidents list, pagination, and multi-field filtering.
13. GET /api/v1/incidents/{incident_id} detail and 404 handling.
14. GET /api/v1/incidents/{incident_id}/events list, pagination, and 404 handling.
"""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models.event import Event
from app.models.incident import Incident, IncidentStatus
from app.services.correlation import correlate_event_to_incident
from app.services.fingerprint import (
    extract_incident_title,
    generate_fingerprint,
    normalize_error_message,
)
from tests.conftest import TEST_API_KEY, VALID_PAYLOAD


# ===========================================================================
# 1. Fingerprint Stability & Normalization Unit Tests
# ===========================================================================

class TestFingerprintStability:
    """Verifies that error signatures are normalized accurately and deterministically."""

    def test_deterministic_output(self) -> None:
        fp1 = generate_fingerprint("payment-service", "production", "Database connection lost")
        fp2 = generate_fingerprint("payment-service", "production", "Database connection lost")
        assert fp1 == fp2
        assert len(fp1) == 64

    def test_volatile_uuid_normalized(self) -> None:
        msg1 = "User 550e8400-e29b-41d4-a716-446655440000 charge failed"
        msg2 = "User a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d charge failed"
        assert normalize_error_message(msg1) == "User <UUID> charge failed"
        assert generate_fingerprint("pay", "prod", msg1) == generate_fingerprint("pay", "prod", msg2)

    def test_volatile_hex_pointers_normalized(self) -> None:
        msg1 = "Segmentation fault at address 0x7ffd58e124a0"
        msg2 = "Segmentation fault at address 0x0000000104a3b890"
        assert normalize_error_message(msg1) == "Segmentation fault at address <HEX>"
        assert generate_fingerprint("core", "prod", msg1) == generate_fingerprint("core", "prod", msg2)

    def test_volatile_datetimes_normalized(self) -> None:
        msg1 = "Operation timed out at 2026-10-20T17:30:00Z after 30s"
        msg2 = "Operation timed out at 2024-06-15 14:30:00.123+00:00 after 30s"
        assert generate_fingerprint("api", "prod", msg1) == generate_fingerprint("api", "prod", msg2)

    def test_volatile_ips_and_entity_ids_normalized(self) -> None:
        msg1 = "Connection refused to host 10.0.0.1 for user_id=1024"
        msg2 = "Connection refused to host 192.168.1.50 for user_id=98765"
        assert generate_fingerprint("svc", "staging", msg1) == generate_fingerprint("svc", "staging", msg2)

    def test_preserves_http_status_codes_and_semantic_numbers(self) -> None:
        # HTTP 500 and HTTP 404 must NOT map to the same fingerprint
        fp_500 = generate_fingerprint("api", "prod", "HTTP 500 Internal Server Error in /checkout")
        fp_404 = generate_fingerprint("api", "prod", "HTTP 404 Not Found in /checkout")
        assert fp_500 != fp_404

    def test_different_services_and_environments_produce_distinct_fingerprints(self) -> None:
        msg = "NullPointerException in PaymentProcessor.charge()"
        fp_prod_pay = generate_fingerprint("payment-service", "production", msg)
        fp_stag_pay = generate_fingerprint("payment-service", "staging", msg)
        fp_prod_auth = generate_fingerprint("auth-service", "production", msg)

        assert fp_prod_pay != fp_stag_pay
        assert fp_prod_pay != fp_prod_auth

    def test_title_extraction(self) -> None:
        title = extract_incident_title("NullPointerException in PaymentProcessor\n   at line 42")
        assert title == "NullPointerException in PaymentProcessor"


# ===========================================================================
# 2. Correlation Engine Unit & State Machine Tests
# ===========================================================================

class TestIncidentCorrelationEngine:
    """Verifies that events correlate into incidents based on fingerprint and time window."""

    def test_non_error_levels_do_not_create_incidents(self) -> None:
        with SessionLocal() as db:
            event = Event(
                id=uuid.uuid4(),
                service_name="auth-service",
                environment="production",
                level="INFO",
                message="User login succeeded",
                timestamp=datetime.now(timezone.utc),
            )
            db.add(event)
            db.commit()

            incident = correlate_event_to_incident(db, event)
            assert incident is None
            assert event.incident_id is None

    def test_two_error_events_same_signature_group_into_one_incident(self) -> None:
        t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 20, 10, 15, 0, tzinfo=timezone.utc)

        with SessionLocal() as db:
            # Event 1
            e1 = Event(
                id=uuid.uuid4(),
                service_name="payment-service",
                environment="production",
                level="ERROR",
                message="Timeout connecting to gateway 10.0.0.1 for order_id=101",
                timestamp=t0,
            )
            db.add(e1)
            db.commit()

            inc1 = correlate_event_to_incident(db, e1)
            db.commit()

            assert inc1 is not None
            assert inc1.event_count == 1
            assert inc1.first_seen_at == t0
            assert inc1.last_seen_at == t0
            assert e1.incident_id == inc1.id

            # Event 2: same normalized error within window
            e2 = Event(
                id=uuid.uuid4(),
                service_name="payment-service",
                environment="production",
                level="ERROR",
                message="Timeout connecting to gateway 10.0.0.2 for order_id=202",
                timestamp=t1,
            )
            db.add(e2)
            db.commit()

            inc2 = correlate_event_to_incident(db, e2)
            db.commit()

            # Must correlate into the same incident
            assert inc2.id == inc1.id
            assert inc2.event_count == 2
            assert inc2.first_seen_at == t0
            assert inc2.last_seen_at == t1
            assert e2.incident_id == inc1.id

    def test_severity_escalates_to_critical(self) -> None:
        t0 = datetime.now(timezone.utc)
        t1 = t0 + timedelta(minutes=5)

        with SessionLocal() as db:
            e1 = Event(
                id=uuid.uuid4(),
                service_name="inventory-service",
                environment="production",
                level="ERROR",
                message="Deadlock detected during inventory check",
                timestamp=t0,
            )
            db.add(e1)
            db.commit()

            inc = correlate_event_to_incident(db, e1)
            db.commit()
            assert inc.severity == "ERROR"

            e2 = Event(
                id=uuid.uuid4(),
                service_name="inventory-service",
                environment="production",
                level="CRITICAL",
                message="Deadlock detected during inventory check",
                timestamp=t1,
            )
            db.add(e2)
            db.commit()

            inc_updated = correlate_event_to_incident(db, e2)
            db.commit()

            assert inc_updated.id == inc.id
            assert inc_updated.severity == "CRITICAL"
            assert inc_updated.event_count == 2

    def test_correlation_time_window_expiry_creates_new_incident(self) -> None:
        t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        # 3 hours later (default window is 1 hour / 3600s)
        t1 = t0 + timedelta(hours=3)

        with SessionLocal() as db:
            e1 = Event(
                id=uuid.uuid4(),
                service_name="search-service",
                environment="staging",
                level="ERROR",
                message="Elasticsearch cluster yellow",
                timestamp=t0,
            )
            db.add(e1)
            db.commit()

            inc1 = correlate_event_to_incident(db, e1)
            db.commit()

            e2 = Event(
                id=uuid.uuid4(),
                service_name="search-service",
                environment="staging",
                level="ERROR",
                message="Elasticsearch cluster yellow",
                timestamp=t1,
            )
            db.add(e2)
            db.commit()

            inc2 = correlate_event_to_incident(db, e2)
            db.commit()

            # Gap exceeded 1 hour, so a new incident must be created
            assert inc1.id != inc2.id
            assert inc1.event_count == 1
            assert inc2.event_count == 1
            assert inc1.fingerprint == inc2.fingerprint

    def test_resolved_incident_does_not_absorb_new_events(self) -> None:
        t0 = datetime.now(timezone.utc)
        t1 = t0 + timedelta(minutes=10)

        with SessionLocal() as db:
            e1 = Event(
                id=uuid.uuid4(),
                service_name="email-service",
                environment="production",
                level="ERROR",
                message="SMTP authentication failed",
                timestamp=t0,
            )
            db.add(e1)
            db.commit()

            inc1 = correlate_event_to_incident(db, e1)
            # Mark first incident as RESOLVED
            inc1.status = IncidentStatus.RESOLVED.value
            db.commit()

            # Second event arrives shortly after
            e2 = Event(
                id=uuid.uuid4(),
                service_name="email-service",
                environment="production",
                level="ERROR",
                message="SMTP authentication failed",
                timestamp=t1,
            )
            db.add(e2)
            db.commit()

            inc2 = correlate_event_to_incident(db, e2)
            db.commit()

            # Resolved incident must NOT be reopened or modified
            assert inc2.id != inc1.id
            assert inc1.status == IncidentStatus.RESOLVED.value
            assert inc2.status == IncidentStatus.OPEN.value
            assert inc2.event_count == 1

    def test_idempotent_reexecution_does_not_increment_count(self) -> None:
        t0 = datetime.now(timezone.utc)

        with SessionLocal() as db:
            e = Event(
                id=uuid.uuid4(),
                service_name="billing-service",
                environment="production",
                level="ERROR",
                message="Stripe charge declined with code=insufficient_funds",
                timestamp=t0,
            )
            db.add(e)
            db.commit()

            inc1 = correlate_event_to_incident(db, e)
            db.commit()
            assert inc1.event_count == 1

            # Second execution with the EXACT same event (e.g. Celery late ACK replay)
            inc2 = correlate_event_to_incident(db, e)
            db.commit()

            assert inc2.id == inc1.id
            assert inc2.event_count == 1  # Did NOT increment to 2


# ===========================================================================
# 3. End-to-End API Ingestion & Background Correlation Tests
# ===========================================================================

class TestEndToEndAsyncCorrelation:
    """Verifies that POST /api/v1/events triggers Celery task and correlates into an incident."""

    def test_post_error_events_creates_and_links_incident(self, client: TestClient) -> None:
        error_payload = {
            "service_name": "checkout-service",
            "environment": "production",
            "level": "ERROR",
            "message": "Out of memory in CheckoutService.process() for order_id=5001",
            "timestamp": "2026-10-20T12:00:00+00:00",
        }

        # Event 1
        r1 = client.post("/api/v1/events", json=error_payload)
        assert r1.status_code == 202
        event_id1 = r1.json()["event_id"]

        # Event 2 (different volatile order_id=5002)
        error_payload2 = dict(error_payload)
        error_payload2["message"] = "Out of memory in CheckoutService.process() for order_id=5002"
        error_payload2["timestamp"] = "2026-10-20T12:10:00+00:00"

        r2 = client.post("/api/v1/events", json=error_payload2)
        assert r2.status_code == 202
        event_id2 = r2.json()["event_id"]

        # Because celery is eager in test mode, correlation ran immediately
        with SessionLocal() as db:
            e1 = db.get(Event, uuid.UUID(event_id1))
            e2 = db.get(Event, uuid.UUID(event_id2))

            assert e1.incident_id is not None
            assert e2.incident_id is not None
            assert e1.incident_id == e2.incident_id

            incident = db.get(Incident, e1.incident_id)
            assert incident is not None
            assert incident.event_count == 2
            assert incident.service_name == "checkout-service"
            assert incident.status == IncidentStatus.OPEN.value


# ===========================================================================
# 4. Authenticated Incidents API Endpoints Tests
# ===========================================================================

class TestIncidentsAPIEndpoints:
    """Verifies GET /api/v1/incidents, /{id}, and /{id}/events."""

    def test_incidents_endpoints_require_authentication(
        self, unauthenticated_client: TestClient
    ) -> None:
        random_id = str(uuid.uuid4())
        r1 = unauthenticated_client.get("/api/v1/incidents")
        r2 = unauthenticated_client.get(f"/api/v1/incidents/{random_id}")
        r3 = unauthenticated_client.get(f"/api/v1/incidents/{random_id}/events")

        assert r1.status_code == 401
        assert r2.status_code == 401
        assert r3.status_code == 401

    def test_get_incidents_list_and_filters(self, client: TestClient) -> None:
        # Seed an incident directly
        now = datetime.now(timezone.utc)
        unique_service = f"test-svc-{uuid.uuid4().hex[:6]}"

        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name=unique_service,
                environment="production",
                fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
                title="Unique Test Incident",
                severity="CRITICAL",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=5,
            )
            db.add(inc)
            db.commit()
            inc_id = str(inc.id)

        # 1. Query without filters
        response = client.get("/api/v1/incidents?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert data["limit"] == 10

        # 2. Query with service_name filter
        response = client.get(f"/api/v1/incidents?service_name={unique_service}")
        assert response.status_code == 200
        filtered = response.json()
        assert filtered["total"] == 1
        assert filtered["items"][0]["id"] == inc_id
        assert filtered["items"][0]["severity"] == "CRITICAL"

        # 3. Query with severity filter
        response = client.get(f"/api/v1/incidents?service_name={unique_service}&severity=ERROR")
        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_get_incident_detail_success_and_404(self, client: TestClient) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="detail-service",
                environment="staging",
                fingerprint="detail-fp-" + uuid.uuid4().hex,
                title="Detail incident title",
                severity="ERROR",
                status=IncidentStatus.ACKNOWLEDGED.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=3,
            )
            db.add(inc)
            db.commit()
            inc_id = str(inc.id)

        # Success 200
        r_ok = client.get(f"/api/v1/incidents/{inc_id}")
        assert r_ok.status_code == 200
        body = r_ok.json()
        assert body["id"] == inc_id
        assert body["status"] == "ACKNOWLEDGED"
        assert body["event_count"] == 3

        # 404 for unknown UUID
        unknown_id = str(uuid.uuid4())
        r_404 = client.get(f"/api/v1/incidents/{unknown_id}")
        assert r_404.status_code == 404
        assert r_404.json()["detail"] == f"Incident with id={unknown_id} not found."

        # 422 for malformed UUID
        r_422 = client.get("/api/v1/incidents/not-a-valid-uuid")
        assert r_422.status_code == 422

    def test_get_incident_events_list_and_404(self, client: TestClient) -> None:
        now = datetime.now(timezone.utc)
        inc_id = uuid.uuid4()

        with SessionLocal() as db:
            inc = Incident(
                id=inc_id,
                service_name="events-subresource-svc",
                environment="production",
                fingerprint="subresource-fp-" + uuid.uuid4().hex,
                title="Subresource events test",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=2,
            )
            db.add(inc)

            e1 = Event(
                id=uuid.uuid4(),
                service_name="events-subresource-svc",
                environment="production",
                level="ERROR",
                message="Subresource error event 1",
                timestamp=now - timedelta(minutes=2),
                incident_id=inc_id,
            )
            e2 = Event(
                id=uuid.uuid4(),
                service_name="events-subresource-svc",
                environment="production",
                level="ERROR",
                message="Subresource error event 2",
                timestamp=now,
                incident_id=inc_id,
            )
            db.add_all([e1, e2])
            db.commit()

        # Success 200
        response = client.get(f"/api/v1/incidents/{inc_id}/events?limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        # Deterministic ordering by timestamp desc (e2 before e1)
        assert body["items"][0]["message"] == "Subresource error event 2"
        assert body["items"][1]["message"] == "Subresource error event 1"

        # 404 for unknown incident
        unknown_id = str(uuid.uuid4())
        r_404 = client.get(f"/api/v1/incidents/{unknown_id}/events")
        assert r_404.status_code == 404
        assert r_404.json()["detail"] == f"Incident with id={unknown_id} not found."
