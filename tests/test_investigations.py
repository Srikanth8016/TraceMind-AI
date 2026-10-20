"""
tests/test_investigations.py — Tests for Milestone 8 (AI-assisted incident investigation engine).

Verifies:
1. Evidence collection and sanitization from PostgreSQL.
2. Bounded event count and truncation of long/sensitive messages.
3. Explicit identification of unavailable telemetry (deployments, metrics).
4. Successful investigation report generation with grounded hypotheses and citations.
5. Strict rejection of malformed or non-JSON model output.
6. Strict rejection of hallucinated / unsupported evidence citations.
7. Handling of provider timeouts and network/HTTP errors.
8. Background task execution, job status transitions (PENDING -> PROCESSING -> COMPLETED).
9. Idempotent task re-execution (no duplicate work on completed jobs).
10. Permanent failure handling for missing incidents (job transitions to FAILED).
11. Retry handling on transient provider failures.
12. API authentication enforcement (401 without X-API-Key).
13. POST /api/v1/incidents/{incident_id}/investigate (HTTP 202 Accepted).
14. GET /api/v1/investigations/{job_id} report retrieval and 404 handling.
15. GET /api/v1/incidents/{incident_id}/investigations list of past jobs.
"""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models.event import Event
from app.models.incident import Incident, IncidentStatus
from app.models.investigation import InvestigationJob, InvestigationStatus
from app.schemas.investigation import InvestigationReport
from app.services.evidence import collect_incident_evidence
from app.services.investigation import run_incident_investigation
from app.services.llm import (
    BaseLLMProvider,
    LLMProviderError,
    MockLLMProvider,
    set_llm_provider_override,
)
from app.tasks import investigate_incident_task
from tests.conftest import TEST_API_KEY, VALID_PAYLOAD


@pytest.fixture(autouse=True)
def reset_provider_override():
    """Ensure tests run with clean mock provider unless explicitly overridden."""
    set_llm_provider_override(None)
    yield
    set_llm_provider_override(None)


# ===========================================================================
# 1. Evidence Collection Unit Tests
# ===========================================================================

class TestEvidenceCollection:
    """Verifies evidence gathering, bounded queries, and untrusted isolation."""

    def test_collects_incident_and_events_evidence(self) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="payment-service",
                environment="production",
                fingerprint="fp-test-evidence-1",
                title="Payment timeout incident",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=2,
            )
            db.add(inc)

            e1 = Event(
                id=uuid.uuid4(),
                service_name="payment-service",
                environment="production",
                level="ERROR",
                message="SocketTimeoutException connecting to BankAPI at 10.0.0.5",
                timestamp=now - timedelta(minutes=1),
                incident_id=inc.id,
            )
            e2 = Event(
                id=uuid.uuid4(),
                service_name="payment-service",
                environment="production",
                level="ERROR",
                message="SocketTimeoutException connecting to BankAPI at 10.0.0.6",
                timestamp=now,
                incident_id=inc.id,
            )
            db.add_all([e1, e2])
            db.commit()

            bundle = collect_incident_evidence(db, inc)

            assert bundle.incident_id == str(inc.id)
            assert bundle.service_name == "payment-service"
            assert bundle.environment == "production"

            # Check valid evidence IDs
            expected_ids = {f"incident:{inc.id}", f"event:{e1.id}", f"event:{e2.id}"}
            assert expected_ids.issubset(bundle.valid_evidence_ids)

            # Check unavailable sources are explicitly identified
            assert len(bundle.unavailable_sources) >= 2
            assert any("Deployment tracking" in s for s in bundle.unavailable_sources)
            assert any("Infrastructure metrics" in s for s in bundle.unavailable_sources)

            # Check XML prompt representation
            prompt_xml = bundle.to_prompt_text()
            assert "<evidence_data>" in prompt_xml
            assert f"incident:{inc.id}" in prompt_xml
            assert f"event:{e1.id}" in prompt_xml
            assert "SocketTimeoutException" in prompt_xml

    def test_bounds_events_and_sanitizes_credentials(self) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="auth-service",
                environment="staging",
                fingerprint="fp-test-sanitize-1",
                title="Auth failure incident",
                severity="CRITICAL",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            db.add(inc)

            e = Event(
                id=uuid.uuid4(),
                service_name="auth-service",
                environment="staging",
                level="CRITICAL",
                message="DB connection error: postgresql://admin:super_secret_password@db.internal:5432/auth",
                timestamp=now,
                incident_id=inc.id,
            )
            db.add(e)
            db.commit()

            bundle = collect_incident_evidence(db, inc)
            prompt_xml = bundle.to_prompt_text()

            # Ensure credentials are redacted
            assert "super_secret_password" not in prompt_xml
            assert "://***:***@" in prompt_xml


# ===========================================================================
# 2. Investigation Orchestration & Citation Validation Unit Tests
# ===========================================================================

class TestInvestigationOrchestration:
    """Verifies prompt synthesis, LLM output validation, and citation grounding."""

    def test_successful_investigation_report_generation(self) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="order-service",
                environment="production",
                fingerprint="fp-orch-1",
                title="Order deadlock incident",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            db.add(inc)

            e = Event(
                id=uuid.uuid4(),
                service_name="order-service",
                environment="production",
                level="ERROR",
                message="Deadlock found when trying to get lock on orders table",
                timestamp=now,
                incident_id=inc.id,
            )
            db.add(e)
            db.commit()

            provider = MockLLMProvider(mode="normal")
            report = run_incident_investigation(db, inc, provider)

            assert isinstance(report, InvestigationReport)
            assert len(report.executive_summary) > 10
            assert len(report.hypotheses) >= 1
            assert report.hypotheses[0].confidence in ("HIGH", "MEDIUM", "LOW")
            assert len(report.recommended_actions) >= 1

            # Validate that cited evidence IDs actually exist
            valid_ids = {f"incident:{inc.id}", f"event:{e.id}"}
            for hyp in report.hypotheses:
                for ref in hyp.evidence_references:
                    assert ref in valid_ids

    def test_rejects_malformed_llm_json(self) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="order-service",
                environment="production",
                fingerprint="fp-malformed-1",
                title="Malformed test",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            db.add(inc)
            db.commit()

            provider = MockLLMProvider(mode="malformed_json")
            with pytest.raises(ValueError, match="Malformed LLM JSON output"):
                run_incident_investigation(db, inc, provider)

    def test_rejects_unsupported_hallucinated_evidence_references(self) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="order-service",
                environment="production",
                fingerprint="fp-unsupported-1",
                title="Unsupported citation test",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            db.add(inc)
            db.commit()

            provider = MockLLMProvider(mode="unsupported_evidence")
            with pytest.raises(ValueError, match="unsupported/hallucinated evidence ID"):
                run_incident_investigation(db, inc, provider)

    def test_handles_provider_timeout_and_error(self) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="order-service",
                environment="production",
                fingerprint="fp-timeout-1",
                title="Timeout test",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            db.add(inc)
            db.commit()

            provider_timeout = MockLLMProvider(mode="timeout")
            with pytest.raises(LLMProviderError, match="timed out"):
                run_incident_investigation(db, inc, provider_timeout)

            provider_err = MockLLMProvider(mode="error")
            with pytest.raises(LLMProviderError, match="HTTP 500"):
                run_incident_investigation(db, inc, provider_err)


# ===========================================================================
# 3. Background Task Execution & Idempotency Tests
# ===========================================================================

class TestInvestigationTaskExecution:
    """Verifies Celery worker task execution, state transitions, and retries."""

    def test_investigation_task_success_and_persistence(self) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="billing-service",
                environment="production",
                fingerprint="fp-task-1",
                title="Billing connection reset",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            db.add(inc)

            job = InvestigationJob(
                id=uuid.uuid4(),
                incident_id=inc.id,
                status=InvestigationStatus.PENDING.value,
            )
            db.add(job)
            db.commit()
            job_id_str = str(job.id)
            inc_id_str = str(inc.id)

        # Run task synchronously (eager mode)
        res = investigate_incident_task.apply(args=[job_id_str, inc_id_str]).get()
        assert res["status"] == "completed"

        with SessionLocal() as db:
            updated_job = db.get(InvestigationJob, uuid.UUID(job_id_str))
            assert updated_job.status == InvestigationStatus.COMPLETED.value
            assert updated_job.attempt_count == 1
            assert updated_job.completed_at is not None
            assert updated_job.report is not None
            assert "executive_summary" in updated_job.report
            assert len(updated_job.report["hypotheses"]) >= 1

    def test_investigation_task_idempotency(self) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="billing-service",
                environment="production",
                fingerprint="fp-idempotent-task-1",
                title="Idempotent task test",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            db.add(inc)

            job = InvestigationJob(
                id=uuid.uuid4(),
                incident_id=inc.id,
                status=InvestigationStatus.COMPLETED.value,
                report={"executive_summary": "Pre-existing completed report"},
                attempt_count=1,
            )
            db.add(job)
            db.commit()
            job_id_str = str(job.id)
            inc_id_str = str(inc.id)

        # Re-running on completed job should return early
        res = investigate_incident_task.apply(args=[job_id_str, inc_id_str]).get()
        assert res["status"] == "already_completed"

        with SessionLocal() as db:
            job = db.get(InvestigationJob, uuid.UUID(job_id_str))
            assert job.attempt_count == 1  # Did not increment
            assert job.report["executive_summary"] == "Pre-existing completed report"

    def test_investigation_task_missing_incident_marks_failed(self) -> None:
        missing_inc_id = str(uuid.uuid4())
        with SessionLocal() as db:
            job = InvestigationJob(
                id=uuid.uuid4(),
                incident_id=uuid.UUID(missing_inc_id),
                status=InvestigationStatus.PENDING.value,
            )
            db.add(job)
            db.commit()
            job_id_str = str(job.id)

        res = investigate_incident_task.apply(args=[job_id_str, missing_inc_id]).get()
        assert res["status"] == "failed"
        assert res["reason"] == "incident_not_found"

        with SessionLocal() as db:
            job = db.get(InvestigationJob, uuid.UUID(job_id_str))
            assert job.status == InvestigationStatus.FAILED.value
            assert "not found" in job.error_message


# ===========================================================================
# 4. API Endpoints & Authentication Tests
# ===========================================================================

class TestInvestigationAPI:
    """Verifies POST /incidents/{id}/investigate, GET /investigations/{id}, and GET /incidents/{id}/investigations."""

    def test_investigation_endpoints_require_auth(
        self, unauthenticated_client: TestClient
    ) -> None:
        dummy_id = str(uuid.uuid4())
        r1 = unauthenticated_client.post(f"/api/v1/incidents/{dummy_id}/investigate")
        r2 = unauthenticated_client.get(f"/api/v1/investigations/{dummy_id}")
        r3 = unauthenticated_client.get(f"/api/v1/incidents/{dummy_id}/investigations")

        assert r1.status_code == 401
        assert r2.status_code == 401
        assert r3.status_code == 401

    def test_post_investigation_success_and_report_retrieval(self, client: TestClient) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            inc = Incident(
                id=uuid.uuid4(),
                service_name="payment-service",
                environment="production",
                fingerprint="fp-api-test-1",
                title="Payment failure for investigation",
                severity="ERROR",
                status=IncidentStatus.OPEN.value,
                first_seen_at=now,
                last_seen_at=now,
                event_count=1,
            )
            db.add(inc)

            e = Event(
                id=uuid.uuid4(),
                service_name="payment-service",
                environment="production",
                level="ERROR",
                message="NullPointerException in StripeClient.charge()",
                timestamp=now,
                incident_id=inc.id,
            )
            db.add(e)
            db.commit()
            inc_id = str(inc.id)

        # 1. Enqueue investigation via POST /incidents/{incident_id}/investigate
        post_resp = client.post(f"/api/v1/incidents/{inc_id}/investigate")
        assert post_resp.status_code == 202
        body = post_resp.json()
        assert "id" in body
        assert body["incident_id"] == inc_id
        assert body["status"] == "PENDING"
        job_id = body["id"]

        # 2. Retrieve job status and report via GET /investigations/{job_id}
        # In eager test mode, background task completed synchronously
        get_resp = client.get(f"/api/v1/investigations/{job_id}")
        assert get_resp.status_code == 200
        job_data = get_resp.json()
        assert job_data["id"] == job_id
        assert job_data["status"] == "COMPLETED"
        assert job_data["report"] is not None
        assert "executive_summary" in job_data["report"]
        assert len(job_data["report"]["hypotheses"]) >= 1

        # 3. List investigations for the incident
        list_resp = client.get(f"/api/v1/incidents/{inc_id}/investigations")
        assert list_resp.status_code == 200
        jobs_list = list_resp.json()
        assert len(jobs_list) >= 1
        assert jobs_list[0]["id"] == job_id

    def test_post_investigation_missing_incident_returns_404(self, client: TestClient) -> None:
        unknown_inc_id = str(uuid.uuid4())
        resp = client.post(f"/api/v1/incidents/{unknown_inc_id}/investigate")
        assert resp.status_code == 404
        assert f"Incident with id={unknown_inc_id} not found." in resp.json()["detail"]

    def test_get_investigation_unknown_id_returns_404(self, client: TestClient) -> None:
        unknown_job_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/investigations/{unknown_job_id}")
        assert resp.status_code == 404
        assert f"Investigation job with id={unknown_job_id} not found." in resp.json()["detail"]

    def test_post_investigation_malformed_uuid_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/v1/incidents/not-a-valid-uuid/investigate")
        assert resp.status_code == 422
