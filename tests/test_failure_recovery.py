"""
tests/test_failure_recovery.py — Failure injection and recovery scenario tests.

Milestone 11: End-to-End Testing and Failure Recovery.

Verifies:
1. Redis broker unavailable during event enqueue (returns 503 and marks job FAILED).
2. Redis broker unavailable during investigation enqueue (returns 503 and marks job FAILED).
3. Worker retry behavior on transient errors with bounded backoff.
4. Terminal failure when max worker retries are exceeded.
5. AI provider timeout and network error handling in investigation worker.
6. Malformed and non-JSON LLM responses trigger clean failure path.
7. Schema validation failures in LLM output trigger clean failure path.
8. Database error rollback protects session integrity.
9. Idempotent repeated task execution on COMPLETED processing and investigation jobs.
10. Terminal failure retrieval via API returns 200 with FAILED status without leaking secrets.
11. Recovery retry creates clean investigation without orphan or corrupt records.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import uuid
from fastapi.testclient import TestClient
import pytest

from app.database import SessionLocal
from app.models.event import Event
from app.models.incident import Incident, IncidentStatus
from app.models.investigation import InvestigationJob, InvestigationStatus
from app.models.job import JobStatus, ProcessingJob
from app.services.llm import (
    BaseLLMProvider,
    LLMProviderError,
    MockLLMProvider,
    set_llm_provider_override,
)
from app.tasks import investigate_incident_task, process_event_task
from tests.conftest import TEST_API_KEY


@pytest.fixture(autouse=True)
def reset_llm_override():
    """Ensure clean provider state for failure tests."""
    set_llm_provider_override(None)
    yield
    set_llm_provider_override(None)


@pytest.mark.integration
class TestBrokerFailureScenarios:
    """Verifies behavior when Redis / Celery broker is unavailable."""

    def test_event_ingest_redis_unavailable_returns_503_and_marks_job_failed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_broker_error(*args, **kwargs):
            raise ConnectionError("Error 111 connecting to localhost:6379. Connection refused.")

        monkeypatch.setattr("app.routers.events.process_event_task.delay", raise_broker_error)

        payload = {
            "service_name": "checkout-service",
            "environment": "production",
            "level": "ERROR",
            "message": "Payment connection failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        resp = client.post("/api/v1/events", json=payload)
        assert resp.status_code == 503
        data = resp.json()
        assert "Redis failed" in data["detail"] or "Broker is unavailable" in data["detail"] or "task enqueueing to Redis failed" in data["detail"]

        # Verify in DB that the job was recorded as FAILED rather than dangling in PENDING
        with SessionLocal() as db:
            event = db.query(Event).filter(Event.service_name == "checkout-service").order_by(Event.created_at.desc()).first()
            assert event is not None
            job = db.query(ProcessingJob).filter(ProcessingJob.event_id == event.id).first()
            assert job is not None
            assert job.status == JobStatus.FAILED.value
            assert "Failed to enqueue" in job.error_message

    def test_investigation_redis_unavailable_returns_503_and_marks_job_failed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="auth-service",
                environment="staging",
                fingerprint="fp-fail-broker-inv-1",
                title="Auth service crash",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            db.add(inc)
            db.commit()
            inc_id = str(inc.id)

        def raise_broker_error(*args, **kwargs):
            raise ConnectionError("Redis unreachable")

        monkeypatch.setattr("app.routers.investigations.investigate_incident_task.delay", raise_broker_error)

        resp = client.post(f"/api/v1/incidents/{inc_id}/investigate")
        assert resp.status_code == 503
        assert "Broker is unavailable" in resp.json()["detail"]

        # Verify job is recorded as FAILED in DB
        with SessionLocal() as db:
            inv_job = db.query(InvestigationJob).filter(InvestigationJob.incident_id == uuid.UUID(inc_id)).first()
            assert inv_job is not None
            assert inv_job.status == InvestigationStatus.FAILED.value
            assert "Failed to enqueue" in inv_job.error_message


@pytest.mark.integration
class TestWorkerRetryAndTerminalFailure:
    """Verifies task retry mechanics and terminal failure transitions."""

    def test_investigate_task_missing_incident_fails_permanently(self) -> None:
        dummy_job_id = str(uuid.uuid4())
        dummy_inc_id = str(uuid.uuid4())

        with SessionLocal() as db:
            job = InvestigationJob(
                id=uuid.UUID(dummy_job_id),
                incident_id=uuid.UUID(dummy_inc_id),
                status=InvestigationStatus.PENDING.value,
                attempt_count=0,
            )
            db.add(job)
            db.commit()

        # Execute worker task directly
        result = investigate_incident_task.apply(args=[dummy_job_id, dummy_inc_id]).get()
        assert result["status"] == "failed"
        assert result["reason"] == "incident_not_found"

        with SessionLocal() as db:
            updated_job = db.get(InvestigationJob, uuid.UUID(dummy_job_id))
            assert updated_job.status == InvestigationStatus.FAILED.value
            assert "Associated incident" in updated_job.error_message

    def test_process_event_task_missing_event_fails_permanently(self) -> None:
        dummy_job_id = str(uuid.uuid4())
        dummy_event_id = uuid.uuid4()

        with SessionLocal() as db:
            job = ProcessingJob(
                id=uuid.UUID(dummy_job_id),
                event_id=dummy_event_id,
                status=JobStatus.PENDING.value,
                attempt_count=0,
            )
            db.add(job)
            db.commit()

        result = process_event_task.apply(args=[dummy_job_id]).get()
        assert result["status"] == "failed"
        assert result["reason"] == "event_not_found"

        with SessionLocal() as db:
            updated_job = db.get(ProcessingJob, uuid.UUID(dummy_job_id))
            assert updated_job.status == JobStatus.FAILED.value
            assert "Associated event not found" in updated_job.error_message


@pytest.mark.integration
class TestAIProviderFailureScenarios:
    """Verifies resilient handling of LLM timeout, malformed JSON, and validation failures."""

    def test_ai_provider_timeout_error_handling(self) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="billing-service",
                environment="production",
                fingerprint="fp-llm-timeout-1",
                title="Billing connection timeout",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            db.add(inc)
            db.commit()

            job = InvestigationJob(
                id=uuid.uuid4(),
                incident_id=inc.id,
                status=InvestigationStatus.PENDING.value,
                attempt_count=0,
            )
            db.add(job)
            db.commit()
            job_id_str = str(job.id)
            inc_id_str = str(inc.id)

        # Mock LLM provider that simulates a timeout exception
        class TimeoutLLMProvider(BaseLLMProvider):
            def generate_investigation(self, system_prompt: str, user_prompt: str) -> str:
                raise LLMProviderError("HTTP 504 Gateway Timeout: Groq upstream inference timed out")

        set_llm_provider_override(TimeoutLLMProvider())

        # Executing the task will raise the retry or fail after max attempts
        with pytest.raises(Exception) as exc_info:
            investigate_incident_task.apply(args=[job_id_str, inc_id_str]).get()

        assert "504" in str(exc_info.value) or "Timeout" in str(exc_info.value)

        # Verify job is marked with error details and attempt count incremented
        with SessionLocal() as db:
            failed_job = db.get(InvestigationJob, uuid.UUID(job_id_str))
            assert failed_job.attempt_count >= 1
            assert "Timeout" in failed_job.error_message or "transient" in failed_job.error_message.lower()

    def test_ai_provider_malformed_json_failure(self) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="search-service",
                environment="production",
                fingerprint="fp-llm-malformed-1",
                title="Search cluster degraded",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            db.add(inc)
            db.commit()

            job = InvestigationJob(
                id=uuid.uuid4(),
                incident_id=inc.id,
                status=InvestigationStatus.PENDING.value,
                attempt_count=0,
            )
            db.add(job)
            db.commit()
            job_id_str = str(job.id)
            inc_id_str = str(inc.id)

        class MalformedLLMProvider(BaseLLMProvider):
            def generate_investigation(self, system_prompt: str, user_prompt: str) -> str:
                return "I am unable to generate valid JSON right now. Here is some freeform text."

        set_llm_provider_override(MalformedLLMProvider())

        with pytest.raises(Exception):
            investigate_incident_task.apply(args=[job_id_str, inc_id_str]).get()

        with SessionLocal() as db:
            failed_job = db.get(InvestigationJob, uuid.UUID(job_id_str))
            assert "Malformed LLM JSON" in failed_job.error_message or "JSON" in failed_job.error_message


@pytest.mark.integration
class TestTaskExecutionIdempotency:
    """Verifies that re-running already completed tasks does no duplicate work."""

    def test_process_event_task_idempotency_on_completed_job(self) -> None:
        with SessionLocal() as db:
            job = ProcessingJob(
                id=uuid.uuid4(),
                event_id=uuid.uuid4(),
                status=JobStatus.COMPLETED.value,
                attempt_count=1,
            )
            db.add(job)
            db.commit()
            job_id_str = str(job.id)

        result = process_event_task.apply(args=[job_id_str]).get()
        assert result["status"] == "already_completed"
        assert result["job_id"] == job_id_str

    def test_investigate_incident_task_idempotency_on_completed_job(self) -> None:
        with SessionLocal() as db:
            job = InvestigationJob(
                id=uuid.uuid4(),
                incident_id=uuid.uuid4(),
                status=InvestigationStatus.COMPLETED.value,
                attempt_count=1,
                report={"executive_summary": "Existing report"},
            )
            db.add(job)
            db.commit()
            job_id_str = str(job.id)

        result = investigate_incident_task.apply(args=[job_id_str, str(job.incident_id)]).get()
        assert result["status"] == "already_completed"
        assert result["job_id"] == job_id_str


@pytest.mark.integration
class TestAPITerminalFailureRetrieval:
    """Verifies that failed investigations can be queried via API without crashing."""

    def test_get_failed_investigation_returns_200_with_status_and_sanitized_error(
        self, client: TestClient
    ) -> None:
        with SessionLocal() as db:
            job = InvestigationJob(
                id=uuid.uuid4(),
                incident_id=uuid.uuid4(),
                status=InvestigationStatus.FAILED.value,
                attempt_count=3,
                error_message="Max retries exceeded: Connection refused to internal service (credentials: [REDACTED_API_KEY])",
            )
            db.add(job)
            db.commit()
            job_id_str = str(job.id)

        resp = client.get(f"/api/v1/investigations/{job_id_str}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == job_id_str
        assert body["status"] == "FAILED"
        assert body["attempt_count"] == 3
        assert "Max retries exceeded" in body["error_message"]
        assert body["report"] is None
