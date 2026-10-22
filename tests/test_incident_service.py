"""
tests/test_incident_service.py — Unit and service-level tests for IncidentService.

Milestone 12: Production-Ready Backend Architecture.
Verifies:
1. IncidentService list_incidents pagination and deterministic ordering.
2. IncidentService multi-field filtering (service_name, environment, severity, status).
3. IncidentService get_incident_by_id for existing and non-existing records.
4. IncidentService list_incident_events with child events and non-existent parent handling.
5. Router integration with IncidentService via dependency injection.
"""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi.testclient import TestClient

from app.models.event import Event
from app.models.incident import Incident, IncidentStatus
from app.schemas.incident import IncidentCreate, IncidentStatusUpdate, IncidentUpdate
from app.services.incident_service import (
    IncidentConflictError,
    IncidentDatabaseError,
    IncidentInvalidTransitionError,
    IncidentNotFoundError,
    IncidentService,
    IncidentValidationError,
)
from unittest.mock import MagicMock
from sqlalchemy.exc import SQLAlchemyError
from tests.conftest import TestingSessionLocal


class TestIncidentServiceUnit:
    """Direct unit tests for IncidentService business logic and queries."""

    def test_create_incident_success(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            data = IncidentCreate(
                title="Service created incident",
                service_name="payment-svc",
                environment="production",
                severity="CRITICAL",
                status=IncidentStatus.OPEN,
            )
            created = service.create_incident(data)
            assert created.id is not None
            assert created.title == "Service created incident"
            assert created.service_name == "payment-svc"
            assert created.severity == "CRITICAL"
            assert created.event_count == 1
            assert created.fingerprint is not None

            # Verify it is persisted in DB
            from_db = db.get(Incident, created.id)
            assert from_db is not None
            assert from_db.title == "Service created incident"

    def test_list_incidents_empty_and_populated(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            now = datetime.now(timezone.utc)
            svc_name = f"unit-svc-{uuid.uuid4().hex[:6]}"

            # Add two incidents
            inc1 = Incident(
                id=uuid.uuid4(),
                service_name=svc_name,
                environment="production",
                fingerprint=f"fp-1-{uuid.uuid4().hex}",
                title="Service test incident 1",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now - timedelta(minutes=10),
                last_seen_at=now - timedelta(minutes=10),
                event_count=1,
            )
            inc2 = Incident(
                id=uuid.uuid4(),
                service_name=svc_name,
                environment="production",
                fingerprint=f"fp-2-{uuid.uuid4().hex}",
                title="Service test incident 2",
                severity="CRITICAL",
                status=IncidentStatus.ACKNOWLEDGED.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=5,
            )
            db.add_all([inc1, inc2])
            db.commit()

            # Test list with service filter
            items, total = service.list_incidents(service_name=svc_name)
            assert total == 2
            assert len(items) == 2
            # Deterministic ordering: inc2 has later last_seen_at, so it comes first
            assert items[0].id == inc2.id
            assert items[1].id == inc1.id

    def test_filter_by_severity_and_status(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            now = datetime.now(timezone.utc)
            svc_name = f"filter-svc-{uuid.uuid4().hex[:6]}"

            inc_err = Incident(
                id=uuid.uuid4(),
                service_name=svc_name,
                environment="staging",
                fingerprint=f"fp-err-{uuid.uuid4().hex}",
                title="Error incident",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            inc_crit = Incident(
                id=uuid.uuid4(),
                service_name=svc_name,
                environment="staging",
                fingerprint=f"fp-crit-{uuid.uuid4().hex}",
                title="Critical incident",
                severity="CRITICAL",
                status=IncidentStatus.RESOLVED.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=2,
            )
            db.add_all([inc_err, inc_crit])
            db.commit()

            # Filter by severity CRITICAL
            items, total = service.list_incidents(service_name=svc_name, severity="CRITICAL")
            assert total == 1
            assert items[0].id == inc_crit.id

            # Filter by status OPEN
            items, total = service.list_incidents(service_name=svc_name, status_filter=IncidentStatus.OPEN)
            assert total == 1
            assert items[0].id == inc_err.id

    def test_get_incident_by_id(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            now = datetime.now(timezone.utc)
            target_id = uuid.uuid4()

            inc = Incident(
                id=target_id,
                service_name="get-id-svc",
                environment="production",
                fingerprint=f"fp-get-{uuid.uuid4().hex}",
                title="Target incident",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            db.add(inc)
            db.commit()

            found = service.get_incident_by_id(target_id)
            assert found is not None
            assert found.id == target_id
            assert found.title == "Target incident"

            # Non-existent ID returns None
            not_found = service.get_incident_by_id(uuid.uuid4())
            assert not_found is None

    def test_list_incident_events_parent_found_and_not_found(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            now = datetime.now(timezone.utc)
            inc_id = uuid.uuid4()

            inc = Incident(
                id=inc_id,
                service_name="event-parent-svc",
                environment="production",
                fingerprint=f"fp-events-{uuid.uuid4().hex}",
                title="Parent incident",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=2,
            )
            db.add(inc)

            e1 = Event(
                id=uuid.uuid4(),
                service_name="event-parent-svc",
                environment="production",
                level="ERROR",
                message="Older event",
                timestamp=now - timedelta(minutes=5),
                incident_id=inc_id,
            )
            e2 = Event(
                id=uuid.uuid4(),
                service_name="event-parent-svc",
                environment="production",
                level="ERROR",
                message="Newer event",
                timestamp=now,
                incident_id=inc_id,
            )
            db.add_all([e1, e2])
            db.commit()

            # Existing parent incident returns events list ordered by timestamp desc
            result = service.list_incident_events(inc_id)
            assert result is not None
            events, total = result
            assert total == 2
            assert len(events) == 2
            assert events[0].message == "Newer event"
            assert events[1].message == "Older event"

            # Unknown parent returns None
            unknown_result = service.list_incident_events(uuid.uuid4())
            assert unknown_result is None

    def test_update_incident_status_success(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            inc = service.create_incident(
                IncidentCreate(
                    title="Status update test",
                    service_name="status-svc",
                    status=IncidentStatus.OPEN,
                )
            )
            assert inc.status == "OPEN"

            # 1. Update to ACKNOWLEDGED
            updated = service.update_incident_status(inc.id, IncidentStatus.ACKNOWLEDGED)
            assert updated.status == "ACKNOWLEDGED"

            # 2. Update to RESOLVED
            resolved = service.update_incident_status(inc.id, IncidentStatus.RESOLVED)
            assert resolved.status == "RESOLVED"

    def test_update_incident_status_not_found_raises_domain_exception(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            unknown_id = uuid.uuid4()
            with pytest.raises(IncidentNotFoundError) as exc_info:
                service.update_incident_status(unknown_id, IncidentStatus.RESOLVED)
            assert str(unknown_id) in str(exc_info.value)

    def test_session_rollback_preserves_session_integrity(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            # Create a valid incident
            inc = service.create_incident(
                IncidentCreate(
                    title="Pre-rollback incident",
                    service_name="rollback-svc",
                )
            )

            # Trigger an update on a non-existent incident which causes a rollback
            try:
                service.update_incident_status(uuid.uuid4(), IncidentStatus.RESOLVED)
            except IncidentNotFoundError:
                pass

            # Verify the session is still active and can execute subsequent queries cleanly
            refetched = service.get_incident_by_id(inc.id)
            assert refetched is not None
            assert refetched.title == "Pre-rollback incident"

    def test_create_incident_db_failure_rolls_back_and_raises_masked_error(self) -> None:
        mock_db = MagicMock()
        mock_db.commit.side_effect = SQLAlchemyError("Simulated database connection loss")
        service = IncidentService(mock_db)

        with pytest.raises(IncidentDatabaseError) as exc_info:
            service.create_incident(
                IncidentCreate(
                    title="Simulated failure incident",
                    service_name="failure-svc",
                )
            )

        # Verify rollback was called and internal SQL error was masked
        mock_db.rollback.assert_called_once()
        assert "Database operation failed while creating incident." in str(exc_info.value)
        assert "connection loss" not in str(exc_info.value)

    def test_update_incident_db_failure_rolls_back_and_raises_masked_error(self) -> None:
        mock_db = MagicMock()
        mock_incident = Incident(
            id=uuid.uuid4(),
            service_name="failure-svc",
            environment="production",
            fingerprint="fp-sim",
            title="Update failure test",
            severity="ERROR",
            status="OPEN",
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
            event_count=1,
        )
        mock_db.execute.return_value.scalars.return_value.first.return_value = mock_incident
        mock_db.commit.side_effect = SQLAlchemyError("Deadlock detected during commit")
        service = IncidentService(mock_db)

        with pytest.raises(IncidentDatabaseError) as exc_info:
            service.update_incident_status(mock_incident.id, IncidentStatus.RESOLVED)

        # Verify rollback occurred and internal SQL details masked
        mock_db.rollback.assert_called_once()
        assert "Database error occurred while updating incident status." in str(exc_info.value)
        assert "Deadlock" not in str(exc_info.value)

    def test_update_incident_service_success(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            inc = service.create_incident(
                IncidentCreate(
                    title="Pre-update title",
                    severity="ERROR",
                    service_name="up-svc",
                )
            )

            updated = service.update_incident(
                inc.id,
                IncidentUpdate(title="Post-update title", severity="CRITICAL", status=IncidentStatus.ACKNOWLEDGED),
            )
            assert updated.title == "Post-update title"
            assert updated.severity == "CRITICAL"
            assert updated.status == "ACKNOWLEDGED"

    def test_update_incident_service_not_found_raises(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            with pytest.raises(IncidentNotFoundError):
                service.update_incident(uuid.uuid4(), IncidentUpdate(title="Nonexistent"))

    def test_delete_incident_service_success_preserves_events(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            inc = service.create_incident(
                IncidentCreate(title="To be deleted", service_name="del-svc")
            )
            event = Event(
                id=uuid.uuid4(),
                service_name="del-svc",
                environment="production",
                level="ERROR",
                message="Linked event before deletion",
                timestamp=datetime.now(timezone.utc),
                incident_id=inc.id,
            )
            db.add(event)
            db.commit()

            # Delete the incident
            success = service.delete_incident(inc.id)
            assert success is True

            # Verify incident is gone
            assert service.get_incident_by_id(inc.id) is None

            # Verify event is NOT deleted, but its incident_id is now None (ondelete="SET NULL")
            refetched_event = db.get(Event, event.id)
            assert refetched_event is not None
            assert refetched_event.incident_id is None

    def test_delete_incident_service_not_found_raises(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            with pytest.raises(IncidentNotFoundError):
                service.delete_incident(uuid.uuid4())


class TestIncidentRouterIntegration:
    """Verifies that the refactored router delegates seamlessly to IncidentService."""

    def test_router_list_incidents(self, client: TestClient) -> None:
        res = client.get("/api/v1/incidents?limit=5")
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert "total" in data

    def test_router_create_incident_success(self, client: TestClient) -> None:
        payload = {
            "title": "API Created Incident",
            "service_name": "billing-service",
            "environment": "production",
            "severity": "CRITICAL",
        }
        res = client.post("/api/v1/incidents", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["title"] == "API Created Incident"
        assert data["severity"] == "CRITICAL"
        assert data["service_name"] == "billing-service"
        assert "id" in data
        assert "fingerprint" in data

    def test_router_create_incident_invalid_severity_returns_422(self, client: TestClient) -> None:
        payload = {
            "title": "Invalid Severity Incident",
            "severity": "INVALID_SEVERITY",
        }
        res = client.post("/api/v1/incidents", json=payload)
        assert res.status_code == 422

    def test_router_create_incident_missing_title_returns_422(self, client: TestClient) -> None:
        payload = {
            "severity": "ERROR",
        }
        res = client.post("/api/v1/incidents", json=payload)
        assert res.status_code == 422

    def test_router_list_incidents_severity_filtering(self, client: TestClient) -> None:
        # Create one ERROR and one CRITICAL incident
        client.post("/api/v1/incidents", json={"title": "Err 1", "severity": "ERROR", "service_name": "svc-filter"})
        client.post("/api/v1/incidents", json={"title": "Crit 1", "severity": "CRITICAL", "service_name": "svc-filter"})

        res_crit = client.get("/api/v1/incidents?service_name=svc-filter&severity=CRITICAL")
        assert res_crit.status_code == 200
        data_crit = res_crit.json()
        assert data_crit["total"] == 1
        assert data_crit["items"][0]["severity"] == "CRITICAL"

    def test_router_get_incident_404(self, client: TestClient) -> None:
        unknown_id = str(uuid.uuid4())
        res = client.get(f"/api/v1/incidents/{unknown_id}")
        assert res.status_code == 404
        assert f"Incident with id={unknown_id} not found." in res.json()["detail"]

    def test_router_patch_incident_status_success(self, client: TestClient) -> None:
        # Create an incident
        created = client.post(
            "/api/v1/incidents",
            json={"title": "Status test incident", "service_name": "patch-svc"},
        ).json()
        inc_id = created["id"]
        assert created["status"] == "OPEN"

        # Patch to ACKNOWLEDGED
        res_ack = client.patch(f"/api/v1/incidents/{inc_id}/status", json={"status": "ACKNOWLEDGED"})
        assert res_ack.status_code == 200
        assert res_ack.json()["status"] == "ACKNOWLEDGED"

        # Patch to RESOLVED
        res_res = client.patch(f"/api/v1/incidents/{inc_id}/status", json={"status": "RESOLVED"})
        assert res_res.status_code == 200
        assert res_res.json()["status"] == "RESOLVED"

    def test_router_patch_incident_status_not_found_404(self, client: TestClient) -> None:
        unknown_id = str(uuid.uuid4())
        res = client.patch(f"/api/v1/incidents/{unknown_id}/status", json={"status": "RESOLVED"})
        assert res.status_code == 404
        assert f"Incident with id={unknown_id} not found." in res.json()["detail"]

    def test_router_patch_incident_status_invalid_enum_422(self, client: TestClient) -> None:
        # Malformed / invalid status enum
        res = client.patch(
            f"/api/v1/incidents/{uuid.uuid4()}/status",
            json={"status": "INVALID_STATE"},
        )
        assert res.status_code == 422
        # Verify correlation request_id is attached to validation errors
        data = res.json()
        assert "request_id" in data
        assert "X-Request-ID" in res.headers

    def test_error_response_preserves_custom_request_id(self, client: TestClient) -> None:
        custom_req_id = "test-custom-correlation-id-777"
        headers = dict(client.headers)
        headers["X-Request-ID"] = custom_req_id
        res = client.get(
            f"/api/v1/incidents/{uuid.uuid4()}",
            headers=headers,
        )
        assert res.status_code == 404
        data = res.json()
        assert data["request_id"] == custom_req_id
        assert res.headers["X-Request-ID"] == custom_req_id

    def test_router_handles_db_failure_with_safe_500(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Simulate unexpected database error in IncidentService.create_incident
        def mock_create_failure(*args, **kwargs):
            raise IncidentDatabaseError("Simulated pool disconnection")

        monkeypatch.setattr(IncidentService, "create_incident", mock_create_failure)

        payload = {
            "title": "DB Failure Endpoint Test",
            "service_name": "db-fail-svc",
            "severity": "ERROR",
        }
        res = client.post("/api/v1/incidents", json=payload)
        assert res.status_code == 500
        data = res.json()
        assert "A database error occurred." in data["detail"]
        assert "request_id" in data
        assert "disconnection" not in data["detail"]

    def test_router_create_incident_invalid_title_length_422(self, client: TestClient) -> None:
        # Title exceeds 255 characters
        res = client.post("/api/v1/incidents", json={"title": "T" * 256, "severity": "ERROR"})
        assert res.status_code == 422

    def test_router_create_incident_invalid_description_length_422(self, client: TestClient) -> None:
        # Description exceeds 2000 characters
        res = client.post(
            "/api/v1/incidents",
            json={"title": "Valid Title", "description": "D" * 2001, "severity": "ERROR"},
        )
        assert res.status_code == 422

    def test_router_get_incident_success(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/incidents",
            json={"title": "Get by ID success test", "severity": "CRITICAL", "service_name": "get-svc"},
        ).json()
        inc_id = created["id"]

        res = client.get(f"/api/v1/incidents/{inc_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == inc_id
        assert data["title"] == "Get by ID success test"
        assert data["severity"] == "CRITICAL"

    def test_router_list_incidents_pagination_skip_and_limit(self, client: TestClient) -> None:
        # Create 5 incidents with unique service name
        svc = f"skip-limit-svc-{uuid.uuid4().hex[:6]}"
        for i in range(5):
            client.post("/api/v1/incidents", json={"title": f"Incident {i}", "service_name": svc})

        # Test limit=2, skip=2
        res = client.get(f"/api/v1/incidents?service_name={svc}&limit=2&skip=2")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["offset"] == 2
        assert data["limit"] == 2

    def test_regression_health_endpoints_remain_functional(self, unauthenticated_client: TestClient) -> None:
        # Liveness probe
        res_liveness = unauthenticated_client.get("/health")
        assert res_liveness.status_code == 200
        assert res_liveness.json()["status"] == "healthy"

        # Readiness probe
        res_ready = unauthenticated_client.get("/ready")
        assert res_ready.status_code == 200
        assert "status" in res_ready.json()

    def test_router_put_update_incident_success(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/incidents",
            json={"title": "Original Title", "severity": "ERROR", "service_name": "put-svc"},
        ).json()
        inc_id = created["id"]

        # Full / field update via PUT
        res = client.put(
            f"/api/v1/incidents/{inc_id}",
            json={"title": "Updated via PUT", "severity": "CRITICAL", "status": "ACKNOWLEDGED"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["title"] == "Updated via PUT"
        assert data["severity"] == "CRITICAL"
        assert data["status"] == "ACKNOWLEDGED"

    def test_router_patch_update_incident_partial_success(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/incidents",
            json={"title": "Before Partial Patch", "severity": "ERROR", "service_name": "patch-partial-svc"},
        ).json()
        inc_id = created["id"]

        # Partial update modifying only the title via PATCH
        res = client.patch(
            f"/api/v1/incidents/{inc_id}",
            json={"title": "After Partial Patch"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["title"] == "After Partial Patch"
        # Severity must remain unchanged
        assert data["severity"] == "ERROR"

    def test_router_put_update_incident_not_found_404(self, client: TestClient) -> None:
        unknown_id = str(uuid.uuid4())
        res = client.put(
            f"/api/v1/incidents/{unknown_id}",
            json={"title": "Nonexistent incident"},
        )
        assert res.status_code == 404
        assert f"Incident with id={unknown_id} not found." in res.json()["detail"]

    def test_router_put_update_incident_invalid_severity_422(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/incidents",
            json={"title": "Valid Incident", "service_name": "val-svc"},
        ).json()
        inc_id = created["id"]

        res = client.put(
            f"/api/v1/incidents/{inc_id}",
            json={"severity": "INVALID_SEVERITY_LEVEL"},
        )
        assert res.status_code == 422

    def test_router_delete_incident_success_and_subsequent_404(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/incidents",
            json={"title": "Incident to be deleted", "service_name": "del-api-svc"},
        ).json()
        inc_id = created["id"]

        # 1. Delete incident -> returns 204 No Content
        res_del = client.delete(f"/api/v1/incidents/{inc_id}")
        assert res_del.status_code == 204
        assert res_del.text == ""

        # 2. Confirm deletion through subsequent GET -> returns 404 Not Found
        res_get = client.get(f"/api/v1/incidents/{inc_id}")
        assert res_get.status_code == 404

    def test_router_delete_incident_not_found_404(self, client: TestClient) -> None:
        unknown_id = str(uuid.uuid4())
        res = client.delete(f"/api/v1/incidents/{unknown_id}")
        assert res.status_code == 404
        assert f"Incident with id={unknown_id} not found." in res.json()["detail"]


class TestIncidentSearchAndFiltering:
    """
    Milestone 13.2: Production-grade search, filtering, sorting, and pagination tests.
    """

    def test_search_by_title_substring_case_insensitive(self, client: TestClient) -> None:
        svc = f"search-svc-{uuid.uuid4().hex[:6]}"
        client.post("/api/v1/incidents", json={"title": "Payment gateway timeout in checkout", "service_name": svc, "severity": "ERROR"})
        client.post("/api/v1/incidents", json={"title": "Database connection pool saturated", "service_name": svc, "severity": "ERROR"})
        client.post("/api/v1/incidents", json={"title": "PAYMENT refund failed on Stripe", "service_name": svc, "severity": "CRITICAL"})

        # Lowercase search matching 2 payment items
        res = client.get(f"/api/v1/incidents?service_name={svc}&search=payment")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 2
        titles = [i["title"] for i in data["items"]]
        assert "Payment gateway timeout in checkout" in titles
        assert "PAYMENT refund failed on Stripe" in titles

        # Uppercase search matching specific item
        res_upper = client.get(f"/api/v1/incidents?service_name={svc}&search=GATEWAY")
        assert res_upper.status_code == 200
        assert res_upper.json()["total"] == 1
        assert res_upper.json()["items"][0]["title"] == "Payment gateway timeout in checkout"

    def test_search_empty_term_handling(self, client: TestClient) -> None:
        svc = f"search-empty-{uuid.uuid4().hex[:6]}"
        client.post("/api/v1/incidents", json={"title": "Item 1", "service_name": svc, "severity": "ERROR"})
        client.post("/api/v1/incidents", json={"title": "Item 2", "service_name": svc, "severity": "ERROR"})

        # Empty and whitespace-only searches should return all items without error
        res_empty = client.get(f"/api/v1/incidents?service_name={svc}&search=")
        assert res_empty.status_code == 200
        assert res_empty.json()["total"] == 2

        res_spaces = client.get(f"/api/v1/incidents?service_name={svc}&search=   ")
        assert res_spaces.status_code == 200
        assert res_spaces.json()["total"] == 2

    def test_severity_filtering_case_insensitive(self, client: TestClient) -> None:
        svc = f"sev-svc-{uuid.uuid4().hex[:6]}"
        client.post("/api/v1/incidents", json={"title": "Crit alert", "service_name": svc, "severity": "CRITICAL"})
        client.post("/api/v1/incidents", json={"title": "Err alert", "service_name": svc, "severity": "ERROR"})

        # Filter by lowercase "critical"
        res_crit = client.get(f"/api/v1/incidents?service_name={svc}&severity=critical")
        assert res_crit.status_code == 200
        assert res_crit.json()["total"] == 1
        assert res_crit.json()["items"][0]["severity"] == "CRITICAL"

        # Filter by uppercase "ERROR"
        res_err = client.get(f"/api/v1/incidents?service_name={svc}&severity=ERROR")
        assert res_err.status_code == 200
        assert res_err.json()["total"] == 1
        assert res_err.json()["items"][0]["severity"] == "ERROR"

    def test_combined_search_and_severity_filtering(self, client: TestClient) -> None:
        svc = f"comb-svc-{uuid.uuid4().hex[:6]}"
        client.post("/api/v1/incidents", json={"title": "Auth token expired", "service_name": svc, "severity": "ERROR"})
        client.post("/api/v1/incidents", json={"title": "Auth service down", "service_name": svc, "severity": "CRITICAL"})
        client.post("/api/v1/incidents", json={"title": "Billing sync lag", "service_name": svc, "severity": "CRITICAL"})

        res = client.get(f"/api/v1/incidents?service_name={svc}&search=auth&severity=critical")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Auth service down"
        assert data["items"][0]["severity"] == "CRITICAL"

    def test_pagination_page_boundaries_and_skip(self, client: TestClient) -> None:
        svc = f"page-svc-{uuid.uuid4().hex[:6]}"
        for i in range(5):
            client.post("/api/v1/incidents", json={"title": f"Incident {i}", "service_name": svc, "severity": "ERROR"})

        # Page 1: skip 0, limit 2
        p1 = client.get(f"/api/v1/incidents?service_name={svc}&limit=2&skip=0&sort_by=title&order=asc").json()
        assert p1["total"] == 5
        assert len(p1["items"]) == 2
        assert [x["title"] for x in p1["items"]] == ["Incident 0", "Incident 1"]

        # Page 2: skip 2, limit 2
        p2 = client.get(f"/api/v1/incidents?service_name={svc}&limit=2&skip=2&sort_by=title&order=asc").json()
        assert len(p2["items"]) == 2
        assert [x["title"] for x in p2["items"]] == ["Incident 2", "Incident 3"]

        # Page 3: skip 4, limit 2
        p3 = client.get(f"/api/v1/incidents?service_name={svc}&limit=2&skip=4&sort_by=title&order=asc").json()
        assert len(p3["items"]) == 1
        assert [x["title"] for x in p3["items"]] == ["Incident 4"]

    def test_sorting_ascending_and_descending(self, client: TestClient) -> None:
        svc = f"sort-svc-{uuid.uuid4().hex[:6]}"
        client.post("/api/v1/incidents", json={"title": "Alpha error", "service_name": svc, "severity": "ERROR"})
        client.post("/api/v1/incidents", json={"title": "Beta error", "service_name": svc, "severity": "ERROR"})
        client.post("/api/v1/incidents", json={"title": "Gamma error", "service_name": svc, "severity": "ERROR"})

        # Sort by title ASC
        res_asc = client.get(f"/api/v1/incidents?service_name={svc}&sort_by=title&order=asc")
        assert res_asc.status_code == 200
        titles_asc = [x["title"] for x in res_asc.json()["items"]]
        assert titles_asc == ["Alpha error", "Beta error", "Gamma error"]

        # Sort by title DESC
        res_desc = client.get(f"/api/v1/incidents?service_name={svc}&sort_by=title&order=desc")
        assert res_desc.status_code == 200
        titles_desc = [x["title"] for x in res_desc.json()["items"]]
        assert titles_desc == ["Gamma error", "Beta error", "Alpha error"]

    def test_stable_tie_breaker_for_identical_timestamps(self, client: TestClient) -> None:
        svc = f"tie-svc-{uuid.uuid4().hex[:6]}"
        fixed_time = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)
        ids = []
        with TestingSessionLocal() as db:
            for i in range(3):
                inc = Incident(
                    id=uuid.uuid4(),
                    service_name=svc,
                    environment="production",
                    fingerprint=f"fp-tie-{i}-{uuid.uuid4().hex[:8]}",
                    title=f"Same timestamp incident {i}",
                    severity="ERROR",
                    status="OPEN",
                    first_seen_at=fixed_time,
                    last_seen_at=fixed_time,
                    created_at=fixed_time,
                    updated_at=fixed_time,
                    event_count=1,
                )
                db.add(inc)
                ids.append(inc.id)
            db.commit()

        # Query all sorted by created_at DESC with tie-breaker by id DESC
        res = client.get(f"/api/v1/incidents?service_name={svc}&sort_by=created_at&order=desc")
        assert res.status_code == 200
        returned_ids = [uuid.UUID(x["id"]) for x in res.json()["items"]]
        assert len(returned_ids) == 3
        # Check that it matches deterministic sorted order of ids descending
        expected_ids = sorted(ids, reverse=True)
        assert returned_ids == expected_ids

    def test_invalid_sort_by_returns_422(self, client: TestClient) -> None:
        res = client.get("/api/v1/incidents?sort_by=drop_table_users")
        assert res.status_code == 422

    def test_invalid_order_returns_422(self, client: TestClient) -> None:
        res = client.get("/api/v1/incidents?order=sideways")
        assert res.status_code == 422

    def test_invalid_severity_returns_422(self, client: TestClient) -> None:
        res = client.get("/api/v1/incidents?severity=not_a_valid_severity")
        assert res.status_code == 422

    def test_empty_result_set(self, client: TestClient) -> None:
        res = client.get("/api/v1/incidents?search=nonexistent_search_query_987654321")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_service_layer_invalid_sort_raises_validation_error(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            with pytest.raises(IncidentValidationError) as exc_info:
                service.list_incidents(sort_by="unapproved_column")
            assert "Invalid sort field" in str(exc_info.value)


class TestIncidentStatusWorkflow:
    """
    Milestone 13.3: Production incident status lifecycle and workflow management tests.
    """

    def test_new_incident_default_status_is_open(self, client: TestClient) -> None:
        res = client.post(
            "/api/v1/incidents",
            json={"title": "Default status check", "service_name": "wf-default-svc"},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "OPEN"

    def test_valid_status_progression(self, client: TestClient) -> None:
        # 1. Create incident (starts OPEN)
        inc = client.post(
            "/api/v1/incidents",
            json={"title": "Progression workflow check", "service_name": "wf-prog-svc"},
        ).json()
        inc_id = inc["id"]
        assert inc["status"] == "OPEN"

        # 2. OPEN -> INVESTIGATING
        res_inv = client.patch(
            f"/api/v1/incidents/{inc_id}/status",
            json={"status": "investigating"},
        )
        assert res_inv.status_code == 200
        assert res_inv.json()["status"] == "INVESTIGATING"

        # 3. INVESTIGATING -> RESOLVED
        res_res = client.patch(
            f"/api/v1/incidents/{inc_id}/status",
            json={"status": "resolved"},
        )
        assert res_res.status_code == 200
        assert res_res.json()["status"] == "RESOLVED"

        # 4. RESOLVED -> CLOSED
        res_cls = client.patch(
            f"/api/v1/incidents/{inc_id}/status",
            json={"status": "closed"},
        )
        assert res_cls.status_code == 200
        assert res_cls.json()["status"] == "CLOSED"

    def test_status_reopening_from_resolved_and_closed(self, client: TestClient) -> None:
        inc = client.post(
            "/api/v1/incidents",
            json={"title": "Reopening workflow check", "service_name": "wf-reopen-svc"},
        ).json()
        inc_id = inc["id"]

        # Move to RESOLVED
        client.patch(f"/api/v1/incidents/{inc_id}/status", json={"status": "RESOLVED"})

        # Reopen: RESOLVED -> OPEN
        res_reopen1 = client.patch(f"/api/v1/incidents/{inc_id}/status", json={"status": "OPEN"})
        assert res_reopen1.status_code == 200
        assert res_reopen1.json()["status"] == "OPEN"

        # Move OPEN -> RESOLVED -> CLOSED
        client.patch(f"/api/v1/incidents/{inc_id}/status", json={"status": "RESOLVED"})
        client.patch(f"/api/v1/incidents/{inc_id}/status", json={"status": "CLOSED"})

        # Reopen: CLOSED -> OPEN
        res_reopen2 = client.patch(f"/api/v1/incidents/{inc_id}/status", json={"status": "OPEN"})
        assert res_reopen2.status_code == 200
        assert res_reopen2.json()["status"] == "OPEN"

    def test_invalid_status_value_returns_422(self, client: TestClient) -> None:
        inc = client.post(
            "/api/v1/incidents",
            json={"title": "Invalid enum check", "service_name": "wf-err-svc"},
        ).json()
        res = client.patch(
            f"/api/v1/incidents/{inc['id']}/status",
            json={"status": "INVALID_STATE_VALUE"},
        )
        assert res.status_code == 422
        assert "request_id" in res.json()

    def test_missing_incident_returns_404(self, client: TestClient) -> None:
        unknown_id = str(uuid.uuid4())
        res = client.patch(
            f"/api/v1/incidents/{unknown_id}/status",
            json={"status": "INVESTIGATING"},
        )
        assert res.status_code == 404
        assert f"Incident with id={unknown_id} not found." in res.json()["detail"]

    def test_invalid_workflow_transition_returns_400(self, client: TestClient) -> None:
        inc = client.post(
            "/api/v1/incidents",
            json={"title": "Disallowed transition check", "service_name": "wf-rule-svc"},
        ).json()
        inc_id = inc["id"]

        # Move OPEN -> RESOLVED
        client.patch(f"/api/v1/incidents/{inc_id}/status", json={"status": "RESOLVED"})

        # Disallowed: RESOLVED -> INVESTIGATING (must reopen to OPEN first)
        res_invalid_1 = client.patch(
            f"/api/v1/incidents/{inc_id}/status",
            json={"status": "INVESTIGATING"},
        )
        assert res_invalid_1.status_code == 400
        assert "Cannot transition incident status from 'RESOLVED' to 'INVESTIGATING'" in res_invalid_1.json()["detail"]

        # Move RESOLVED -> CLOSED
        client.patch(f"/api/v1/incidents/{inc_id}/status", json={"status": "CLOSED"})

        # Disallowed: CLOSED -> INVESTIGATING
        res_invalid_2 = client.patch(
            f"/api/v1/incidents/{inc_id}/status",
            json={"status": "INVESTIGATING"},
        )
        assert res_invalid_2.status_code == 400
        assert "Cannot transition incident status from 'CLOSED' to 'INVESTIGATING'" in res_invalid_2.json()["detail"]

        # Disallowed: CLOSED -> RESOLVED
        res_invalid_3 = client.patch(
            f"/api/v1/incidents/{inc_id}/status",
            json={"status": "RESOLVED"},
        )
        assert res_invalid_3.status_code == 400
        assert "Cannot transition incident status from 'CLOSED' to 'RESOLVED'" in res_invalid_3.json()["detail"]

    def test_generic_update_enforces_workflow_rules(self, client: TestClient) -> None:
        inc = client.post(
            "/api/v1/incidents",
            json={"title": "Generic update transition check", "service_name": "wf-gen-svc"},
        ).json()
        inc_id = inc["id"]

        # Move to CLOSED
        client.patch(f"/api/v1/incidents/{inc_id}/status", json={"status": "CLOSED"})

        # Attempt invalid transition via PUT
        res_put_invalid = client.put(
            f"/api/v1/incidents/{inc_id}",
            json={"status": "INVESTIGATING"},
        )
        assert res_put_invalid.status_code == 400
        assert "Cannot transition incident status" in res_put_invalid.json()["detail"]

        # Attempt invalid transition via PATCH
        res_patch_invalid = client.patch(
            f"/api/v1/incidents/{inc_id}",
            json={"status": "RESOLVED"},
        )
        assert res_patch_invalid.status_code == 400
        assert "Cannot transition incident status" in res_patch_invalid.json()["detail"]

        # Valid transition via generic update: CLOSED -> OPEN
        res_put_valid = client.put(
            f"/api/v1/incidents/{inc_id}",
            json={"status": "OPEN", "title": "Reopened via generic PUT"},
        )
        assert res_put_valid.status_code == 200
        assert res_put_valid.json()["status"] == "OPEN"
        assert res_put_valid.json()["title"] == "Reopened via generic PUT"

    def test_status_filtering_case_insensitive(self, client: TestClient) -> None:
        svc = f"wf-filter-{uuid.uuid4().hex[:6]}"
        inc1 = client.post("/api/v1/incidents", json={"title": "Inc 1", "service_name": svc}).json()
        inc2 = client.post("/api/v1/incidents", json={"title": "Inc 2", "service_name": svc}).json()
        client.patch(f"/api/v1/incidents/{inc2['id']}/status", json={"status": "INVESTIGATING"})

        # Lowercase filter ?status=investigating
        res_lower = client.get(f"/api/v1/incidents?service_name={svc}&status=investigating")
        assert res_lower.status_code == 200
        assert res_lower.json()["total"] == 1
        assert res_lower.json()["items"][0]["id"] == inc2["id"]

        # Uppercase filter ?status=INVESTIGATING
        res_upper = client.get(f"/api/v1/incidents?service_name={svc}&status=INVESTIGATING")
        assert res_upper.status_code == 200
        assert res_upper.json()["total"] == 1
        assert res_upper.json()["items"][0]["id"] == inc2["id"]

    def test_service_layer_invalid_transition_raises_domain_error(self) -> None:
        with TestingSessionLocal() as db:
            service = IncidentService(db)
            inc = service.create_incident(
                IncidentCreate(title="Direct service state test", service_name="svc-direct")
            )
            # Move to CLOSED
            service.update_incident_status(inc.id, IncidentStatus.CLOSED)

            # Invalid direct transition
            with pytest.raises(IncidentInvalidTransitionError) as exc_info:
                service.update_incident_status(inc.id, IncidentStatus.INVESTIGATING)
            assert "Cannot transition incident status from 'CLOSED' to 'INVESTIGATING'" in str(exc_info.value)


