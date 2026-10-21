"""
tests/test_demo_mode.py — Verification of zero-budget demo deployment mode.

Verifies:
1. Demo mode configuration validation (allows single-process execution without Celery/Redis).
2. Security enforcement in demo mode (strict API key validation still enforced).
3. Neon connection string normalization (postgres:// and postgresql:// -> postgresql+psycopg://).
4. Readiness probe in demo mode (GET /ready returns 200 without Redis).
5. Event ingestion and in-process background task execution in demo mode.
6. Investigation job creation and report persistence in demo mode.
7. Job failure handling and status persistence in demo mode.
"""

from datetime import datetime, timezone
import uuid
from fastapi.testclient import TestClient
import pytest

from app.config import AppEnvironment, Settings
from app.database import SessionLocal
from app.models.event import Event
from app.models.incident import Incident, IncidentStatus
from app.models.investigation import InvestigationJob, InvestigationStatus
from app.models.job import JobStatus, ProcessingJob
from app.services.embedding import MockEmbeddingProvider, set_embedding_provider_override
from app.services.llm import MockLLMProvider, set_llm_provider_override
from tests.conftest import TEST_API_KEY


@pytest.fixture(autouse=True)
def ensure_deterministic_mocks():
    """Ensure clean mock providers for demo mode tests."""
    mock_llm = MockLLMProvider()
    mock_emb = MockEmbeddingProvider()
    set_llm_provider_override(mock_llm)
    set_embedding_provider_override(mock_emb)
    yield
    set_llm_provider_override(None)
    set_embedding_provider_override(None)


@pytest.mark.integration
class TestDemoModeConfiguration:
    """Verifies configuration rules and Neon connection string normalization."""

    def test_demo_mode_settings_validation(self) -> None:
        cfg = Settings(
            ENVIRONMENT=AppEnvironment.PRODUCTION,
            DEMO_MODE=True,
            TRACEMIND_API_KEY="prod-super-secret-key-32charslong",
            DATABASE_URL="postgres://alex:secret123@ep-cool-fog.us-east-2.aws.neon.tech/neondb?sslmode=require",
        )
        assert cfg.DEMO_MODE is True
        assert cfg.DATABASE_URL.startswith("postgresql+psycopg://")
        assert "sslmode=require" in cfg.DATABASE_URL

    def test_demo_mode_still_enforces_production_api_key_security(self) -> None:
        with pytest.raises(ValueError, match="Production security violation"):
            Settings(
                ENVIRONMENT=AppEnvironment.PRODUCTION,
                DEMO_MODE=True,
                TRACEMIND_API_KEY="dev-api-key-tracemind-32bytes",
            )

    def test_neon_url_normalization(self) -> None:
        raw_neon_url = "postgresql://tracemind_owner:secret@ep-mute-wave-12345.us-east-2.aws.neon.tech/tracemind?sslmode=require"
        cfg = Settings(DATABASE_URL=raw_neon_url)
        assert cfg.DATABASE_URL.startswith("postgresql+psycopg://")
        assert "sslmode=require" in cfg.DATABASE_URL


@pytest.mark.integration
class TestDemoModeProbesAndExecution:
    """Verifies API endpoints, readiness checks, and in-process execution in demo mode."""

    def test_readiness_probe_in_demo_mode_does_not_require_redis(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.config import get_settings
        settings = get_settings()

        monkeypatch.setattr(settings, "DEMO_MODE", True)
        monkeypatch.setattr("app.main.check_db_connection", lambda: True)
        monkeypatch.setattr("app.main.check_redis_connection", lambda: False)

        resp = client.get("/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["database"] == "healthy"
        assert "demo mode" in body["redis"]

    def test_demo_mode_event_ingestion_and_investigation_lifecycle(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "DEMO_MODE", True)

        # 1. Ingest event in demo mode
        event_payload = {
            "service_name": "checkout-service",
            "environment": "demo",
            "level": "ERROR",
            "message": "ConnectionRefusedError: Failed to connect to payment cluster",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        resp = client.post("/api/v1/events", json=event_payload)
        assert resp.status_code == 202
        body = resp.json()
        event_id = body["event_id"]
        job_id = body["job_id"]

        # 2. In demo mode via TestClient, BackgroundTasks run during request teardown
        # Verify job and incident were created in database
        with SessionLocal() as db:
            job = db.get(ProcessingJob, uuid.UUID(job_id))
            assert job is not None
            assert job.status == JobStatus.COMPLETED.value

            incidents = db.query(Incident).filter(Incident.service_name == "checkout-service").all()
            assert len(incidents) >= 1
            incident_id = str(incidents[0].id)

        # 3. Trigger investigation in demo mode
        inv_resp = client.post(f"/api/v1/incidents/{incident_id}/investigate")
        assert inv_resp.status_code == 202
        inv_body = inv_resp.json()
        inv_job_id = inv_body["id"]

        # 4. Fetch completed investigation report
        get_inv_resp = client.get(f"/api/v1/investigations/{inv_job_id}")
        assert get_inv_resp.status_code == 200
        inv_data = get_inv_resp.json()
        assert inv_data["id"] == inv_job_id
        assert inv_data["status"] == "COMPLETED"
        assert inv_data["report"] is not None
        assert "executive_summary" in inv_data["report"]
        assert len(inv_data["report"]["hypotheses"]) >= 1

    def test_demo_mode_failed_task_persists_failure_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Verify that if an in-process task encounters a terminal failure,
        the job status is safely persisted as FAILED in PostgreSQL.
        """
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

        from app.services.task_dispatcher import _run_sync_investigation_task
        _run_sync_investigation_task(dummy_job_id, dummy_inc_id)

        with SessionLocal() as db:
            updated_job = db.get(InvestigationJob, uuid.UUID(dummy_job_id))
            assert updated_job.status == InvestigationStatus.FAILED.value
            assert "Associated incident" in updated_job.error_message
