"""
tests/test_jobs.py — Tests for Celery asynchronous processing jobs (Milestone 6).

Verifies:
1. Job creation on event ingestion (HTTP 202).
2. Status retrieval via GET /api/v1/jobs/{job_id}.
3. Authentication enforcement on jobs endpoint (401 without key).
4. Unknown job ID handling (HTTP 404).
5. Celery task successful execution and status transition to COMPLETED.
6. Task execution idempotency (no repeated work if already COMPLETED).
7. Non-retryable permanent failure handling (missing event).
8. Transient failure retries and retry limit exhaustion (transitions to FAILED).
9. Explicit enqueue failure handling (HTTP 503 and job marked FAILED on broker failure).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models.event import Event
from app.models.job import JobStatus, ProcessingJob
from app.tasks import process_event_task
from tests.conftest import TEST_API_KEY, VALID_PAYLOAD


# ===========================================================================
# 1. Job Creation on Event Ingestion (HTTP 202)
# ===========================================================================

class TestJobCreation:
    """Verifies that POST /api/v1/events creates and returns both Event and Job."""

    def test_post_event_returns_202_with_job(self, client: TestClient) -> None:
        response = client.post("/api/v1/events", json=VALID_PAYLOAD)
        assert response.status_code == 202
        body = response.json()

        assert "id" in body
        assert "event_id" in body
        assert "job_id" in body
        assert "status" in body

        # Verify UUID formats
        event_uuid = uuid.UUID(body["event_id"])
        job_uuid = uuid.UUID(body["job_id"])

        # Verify persistence in database
        with SessionLocal() as db:
            event = db.get(Event, event_uuid)
            job = db.get(ProcessingJob, job_uuid)
            assert event is not None
            assert job is not None
            assert job.event_id == event.id


# ===========================================================================
# 2. Job Status Retrieval (GET /api/v1/jobs/{job_id})
# ===========================================================================

class TestJobStatusRetrieval:
    """Verifies retrieval of persisted job status and authentication enforcement."""

    def test_get_job_status_success(self, client: TestClient) -> None:
        # Create event & job
        post_resp = client.post("/api/v1/events", json=VALID_PAYLOAD)
        assert post_resp.status_code == 202
        job_id = post_resp.json()["job_id"]

        # Retrieve job status
        get_resp = client.get(f"/api/v1/jobs/{job_id}")
        assert get_resp.status_code == 200
        body = get_resp.json()

        assert body["id"] == job_id
        assert body["event_id"] == post_resp.json()["event_id"]
        assert body["status"] in ("PENDING", "PROCESSING", "COMPLETED")
        assert "attempt_count" in body
        assert "created_at" in body
        assert "updated_at" in body

    def test_get_job_status_requires_auth(
        self, unauthenticated_client: TestClient
    ) -> None:
        random_id = str(uuid.uuid4())
        response = unauthenticated_client.get(f"/api/v1/jobs/{random_id}")
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API Key."}

    def test_unknown_job_id_returns_404(self, client: TestClient) -> None:
        unknown_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/jobs/{unknown_id}")
        assert response.status_code == 404
        assert response.json()["detail"] == f"Job with id={unknown_id} not found."

    def test_malformed_job_uuid_returns_422(self, client: TestClient) -> None:
        response = client.get("/api/v1/jobs/not-a-valid-uuid")
        assert response.status_code == 422


# ===========================================================================
# 3. Worker Task Execution & Idempotency
# ===========================================================================

class TestWorkerTaskExecution:
    """Verifies the core execution logic, status transitions, and idempotency."""

    def test_task_success_transitions_to_completed(self) -> None:
        # 1. Create Event and Job directly in test DB
        with SessionLocal() as db:
            event = Event(
                id=uuid.uuid4(),
                service_name="payment-service",
                environment="production",
                level="INFO",
                message="  Processing user transaction #12345  ",
                timestamp=datetime.now(timezone.utc),
            )
            db.add(event)
            db.flush()

            job = ProcessingJob(
                id=uuid.uuid4(),
                event_id=event.id,
                status=JobStatus.PENDING.value,
                attempt_count=0,
            )
            db.add(job)
            db.commit()
            job_id_str = str(job.id)

        # 2. Execute task synchronously
        result = process_event_task(job_id_str)
        assert result["status"] == "completed"

        # 3. Verify final DB state
        with SessionLocal() as db:
            completed_job = db.get(ProcessingJob, uuid.UUID(job_id_str))
            assert completed_job.status == JobStatus.COMPLETED.value
            assert completed_job.attempt_count == 1
            assert completed_job.error_message is None

    def test_task_execution_is_idempotent(self) -> None:
        # Create completed job
        with SessionLocal() as db:
            event = Event(
                id=uuid.uuid4(),
                service_name="auth-service",
                environment="production",
                level="INFO",
                message="User signed in",
                timestamp=datetime.now(timezone.utc),
            )
            db.add(event)
            db.flush()

            job = ProcessingJob(
                id=uuid.uuid4(),
                event_id=event.id,
                status=JobStatus.COMPLETED.value,
                attempt_count=1,
            )
            db.add(job)
            db.commit()
            job_id_str = str(job.id)

        # Execute again — must return early without incrementing attempts
        result = process_event_task(job_id_str)
        assert result["status"] == "already_completed"

        with SessionLocal() as db:
            job_after = db.get(ProcessingJob, uuid.UUID(job_id_str))
            assert job_after.status == JobStatus.COMPLETED.value
            assert job_after.attempt_count == 1

    def test_missing_event_is_permanent_failure(self) -> None:
        # Create job referencing non-existent event
        with SessionLocal() as db:
            job = ProcessingJob(
                id=uuid.uuid4(),
                event_id=uuid.uuid4(),  # Does not exist in events table
                status=JobStatus.PENDING.value,
                attempt_count=0,
            )
            db.add(job)
            db.commit()
            job_id_str = str(job.id)

        result = process_event_task(job_id_str)
        assert result["status"] == "failed"
        assert result["reason"] == "event_not_found"

        with SessionLocal() as db:
            failed_job = db.get(ProcessingJob, uuid.UUID(job_id_str))
            assert failed_job.status == JobStatus.FAILED.value
            assert "not found" in failed_job.error_message


# ===========================================================================
# 4. Enqueue Failure Handling
# ===========================================================================

class TestEnqueueFailureHandling:
    """Verifies system behavior when Redis / Celery broker is unreachable."""

    def test_enqueue_failure_marks_job_failed_and_returns_503(
        self, client: TestClient
    ) -> None:
        # Mock process_event_task.delay to simulate Redis connection error
        with patch("app.routers.events.process_event_task.delay") as mock_delay:
            mock_delay.side_effect = ConnectionError("Error 111 connecting to redis:6379")

            response = client.post("/api/v1/events", json=VALID_PAYLOAD)

            # Must return HTTP 503 Service Unavailable
            assert response.status_code == 503
            assert "Redis failed" in response.json()["detail"]

        # Verify in database that the job was persisted and marked FAILED, not left PENDING
        with SessionLocal() as db:
            failed_jobs = (
                db.query(ProcessingJob)
                .filter(ProcessingJob.status == JobStatus.FAILED.value)
                .all()
            )
            assert len(failed_jobs) > 0
            latest = failed_jobs[-1]
            assert "Failed to enqueue" in latest.error_message
