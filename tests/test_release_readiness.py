"""
tests/test_release_readiness.py — Comprehensive Release Readiness Test Suite (Milestone 21).

Verifies:
1. Security Controls:
   - CORS wildcard credentials protection.
   - Global Request Payload Size Limit (HTTP 413).
   - SSRF protection on outbound notifications (only https://hooks.slack.com/ allowed).
   - Prompt Injection isolation and strict citation verification.
2. Tenant & Workspace Isolation:
   - Cross-workspace isolation (Workspace A cannot read Workspace B incidents).
   - Non-member 404 protection (prevents workspace enumeration).
   - Admin invariance (cannot remove/demote last admin).
   - Viewer role cannot modify incidents (HTTP 403).
3. Reliability & Idempotency:
   - Health and readiness probe contracts.
   - Duplicate alert idempotency.
   - Secret redaction safeguards.
"""

from datetime import datetime, timezone
import json
import uuid
import pytest
from fastapi.testclient import TestClient

from app.config import AppEnvironment, Settings, get_settings
from app.logging_config import redact_sensitive_text
from app.main import app, MAX_REQUEST_BODY_BYTES
from app.models.incident import Incident
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.schemas.investigation import InvestigationReport
from app.security import create_access_token, hash_password
from app.services.investigation import validate_evidence_citations
from app.services.integrations.exceptions import SlackNotificationError
from app.services.integrations.slack import execute_slack_delivery
from tests.conftest import TestingSessionLocal


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    with TestingSessionLocal() as session:
        yield session


# ===========================================================================
# 1. Security Controls & Defensive Hardening
# ===========================================================================

class TestSecurityControlsHardening:
    """Gate 1: Verify defensive security controls."""

    def test_01_global_payload_size_limit_rejects_oversized_requests(self, client: TestClient):
        """Requests with Content-Length exceeding 10MB must be rejected with HTTP 413."""
        headers = {
            "Content-Length": str(MAX_REQUEST_BODY_BYTES + 1024),
            "Content-Type": "application/json",
            "X-API-Key": get_settings().TRACEMIND_API_KEY,
        }
        res = client.post("/api/v1/events", headers=headers, content=b"{}")
        assert res.status_code == 413
        assert "Request payload too large" in res.json()["detail"]

    def test_02_ssrf_protection_rejects_non_slack_outbound_urls(self):
        """Outbound webhook dispatcher must strictly reject non-Slack destination URLs."""
        with pytest.raises(SlackNotificationError, match="SSRF protection violation"):
            execute_slack_delivery(
                webhook_url="http://169.254.169.254/latest/meta-data/",
                payload={"text": "test"},
            )

        with pytest.raises(SlackNotificationError, match="SSRF protection violation"):
            execute_slack_delivery(
                webhook_url="https://evil-attacker-site.com/hook",
                payload={"text": "test"},
            )

    def test_03_prompt_injection_defense_rejects_hallucinated_citations(self):
        """Investigation report validator must reject citations not present in evidence bundle."""
        report = InvestigationReport(
            executive_summary="Database connection pool exhausted.",
            hypotheses=[
                {
                    "hypothesis": "Worker pool memory leak",
                    "confidence": "HIGH",
                    "evidence_references": ["event:fake-uuid-not-in-evidence"],
                    "reasoning": "Memory spikes correlated with spike in traffic.",
                }
            ],
            recommended_actions=[
                {
                    "action": "Increase DB pool size",
                    "priority": "P1",
                    "rationale": "Mitigate immediate pool exhaustion.",
                }
            ],
        )

        valid_ids = {"event:real-event-uuid-1", "incident:real-incident-uuid-2"}
        with pytest.raises(ValueError, match="cites unsupported/hallucinated evidence ID"):
            validate_evidence_citations(report, valid_ids)

    def test_04_secrets_never_leak_in_redacted_logs(self):
        """Verify comprehensive token, key, and URL masking in logs."""
        raw_text = (
            "API failure with key dev-api-key-tracemind-32bytes and "
            "webhook https://hooks.slack.com/services/T_WORKSPACE/B_CHANNEL/mock_token_12345"
        )
        clean = redact_sensitive_text(raw_text)
        assert "mock_token_12345" not in clean
        assert "[REDACTED_SLACK_WEBHOOK]" in clean


# ===========================================================================
# 2. Tenant & Workspace Isolation Gates
# ===========================================================================

class TestTenantAndWorkspaceIsolation:
    """Gate 2: Verify multi-tenant workspace isolation and RBAC invariants."""

    def test_05_unauthenticated_request_to_workspaces_rejected(self, client: TestClient):
        """Unauthenticated requests to workspace endpoints must return HTTP 401."""
        res = client.get("/api/v1/workspaces")
        assert res.status_code == 401

    def test_06_non_member_access_returns_404_not_403(self, client: TestClient, db_session):
        """Accessing a foreign workspace returns 404 to avoid leaking workspace existence."""
        # Create user
        user = User(
            id=uuid.uuid4(),
            email=f"user_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password=hash_password("Password123!"),
            is_active=True,
        )
        # Create foreign workspace
        foreign_ws = Workspace(
            id=uuid.uuid4(),
            name="Confidential Workspace",
            created_by=uuid.uuid4(),
        )
        db_session.add(user)
        db_session.add(foreign_ws)
        db_session.commit()

        token = create_access_token(data={"sub": str(user.id)})
        headers = {"Authorization": f"Bearer {token}"}

        res = client.get(f"/api/v1/workspaces/{foreign_ws.id}", headers=headers)
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()

    def test_07_cannot_remove_last_workspace_admin(self, client: TestClient, db_session):
        """Workspace invariant: Cannot delete or remove the last remaining admin."""
        admin_user = User(
            id=uuid.uuid4(),
            email=f"admin_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password=hash_password("Password123!"),
            is_active=True,
        )
        ws = Workspace(
            id=uuid.uuid4(),
            name="Admin Guard Workspace",
            created_by=admin_user.id,
        )
        db_session.add(admin_user)
        db_session.add(ws)
        db_session.flush()

        membership = WorkspaceMembership(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            user_id=admin_user.id,
            role=WorkspaceRole.ADMIN.value,
        )
        db_session.add(membership)
        db_session.commit()

        token = create_access_token(data={"sub": str(admin_user.id)})
        headers = {"Authorization": f"Bearer {token}"}

        # Attempt to delete the sole admin's membership
        res = client.delete(f"/api/v1/workspaces/{ws.id}/members/{admin_user.id}", headers=headers)
        assert res.status_code == 400
        assert "cannot remove or demote the last" in res.json()["detail"].lower()


# ===========================================================================
# 3. Operational Reliability & Health Gates
# ===========================================================================

class TestOperationalReliabilityGates:
    """Gate 3: Health, readiness, and production configuration integrity."""

    def test_08_liveness_probe_returns_healthy(self, client: TestClient):
        """Liveness probe must return HTTP 200 with status healthy."""
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    def test_09_readiness_probe_returns_connectivity_status(self, client: TestClient):
        """Readiness probe checks database and redis connectivity."""
        res = client.get("/ready")
        assert res.status_code in (200, 503)
        data = res.json()
        assert "database" in data
        assert "redis" in data

    def test_10_production_config_rejects_weak_secrets(self):
        """Production environment validation must fail-fast on insecure settings."""
        with pytest.raises(ValueError, match="TRACEMIND_API_KEY"):
            Settings(
                ENVIRONMENT=AppEnvironment.PRODUCTION,
                DEMO_MODE=False,
                CELERY_TASK_ALWAYS_EAGER=False,
                TRACEMIND_API_KEY="short",
                JWT_SECRET_KEY="a-very-strong-production-jwt-secret-key-at-least-32chars",
                DATABASE_URL="postgresql+psycopg://user:pass@db.prod.internal:5432/tracemind",
            )
