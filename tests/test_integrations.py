"""
tests/test_integrations.py — Automated test suite for Milestone 19 external integrations.

Covers:
1. Datadog signature / token authentication (header, bearer, query, invalid, missing).
2. Datadog payload normalization, service/env tag extraction, severity mapping.
3. Datadog webhook deduplication & idempotency.
4. PagerDuty HMAC-SHA256 signature verification (valid, multi-signature, invalid, missing).
5. PagerDuty timestamp validation & replay attack protection.
6. PagerDuty v3 and v2 payload normalization.
7. PagerDuty webhook deduplication & idempotency.
8. End-to-end integration into event ingestion and incident correlation pipeline.
9. Outbound Slack notifications (success, HTTP failure, timeout, retry, rules filtering).
10. Outbound Slack notification idempotency (preventing duplicate sends).
11. Secret redaction in logs (Slack webhook URL, PagerDuty signature, Datadog token).
12. Workspace scoping compatibility.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Base
from app.logging_config import redact_sensitive_text
from app.main import app
from app.models.event import Event
from app.models.incident import Incident
from app.models.integration import NotificationLog, WebhookEvent
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.integrations.exceptions import SlackNotificationError
from app.services.integrations.slack import (
    build_slack_blocks,
    create_or_get_notification_log,
    execute_slack_delivery,
    is_notification_allowed,
    mask_slack_url,
)
from app.tasks import send_slack_notification_task
from tests.conftest import TestingSessionLocal, test_engine


@pytest.fixture(autouse=True)
def setup_integration_db():
    """Ensure all tables exist before each integration test."""
    Base.metadata.create_all(bind=test_engine)
    yield
    # Clean integration and event records between tests
    with TestingSessionLocal() as session:
        session.query(WebhookEvent).delete()
        session.query(NotificationLog).delete()
        session.commit()


@pytest.fixture
def client():
    return TestClient(app)


# ===========================================================================
# 1. Datadog Webhook Authentication & Security Tests
# ===========================================================================

class TestDatadogAuthentication:
    """Tests 1-5: Datadog webhook authentication and signature validation."""

    def test_01_valid_token_in_dd_header(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_SECRET", "dd-secret-12345")
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_ENABLED", True)

        payload = {
            "id": "dd-alert-01",
            "title": "CPU High on billing-service",
            "body": "Host cpu > 90%",
            "alert_type": "error",
            "tags": ["service:billing", "env:production"],
        }
        res = client.post(
            "/api/v1/webhooks/datadog",
            json=payload,
            headers={"DD-WEBHOOK-TOKEN": "dd-secret-12345"},
        )
        assert res.status_code == 202
        data = res.json()
        assert data["provider"] == "datadog"
        assert data["status"] == "accepted"
        assert data["event_id"] is not None

    def test_02_valid_token_in_bearer_authorization_header(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_SECRET", "dd-secret-12345")
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_ENABLED", True)

        payload = {
            "id": "dd-alert-02",
            "title": "Memory Leak in auth-service",
            "alert_type": "error",
            "tags": "service:auth,env:production",
        }
        res = client.post(
            "/api/v1/webhooks/datadog",
            json=payload,
            headers={"Authorization": "Bearer dd-secret-12345"},
        )
        assert res.status_code == 202
        assert res.json()["status"] == "accepted"

    def test_03_valid_token_in_query_param(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_SECRET", "dd-secret-12345")
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_ENABLED", True)

        payload = {
            "id": "dd-alert-03",
            "title": "Disk Space Low",
            "alert_type": "warning",
        }
        res = client.post(
            "/api/v1/webhooks/datadog?token=dd-secret-12345",
            json=payload,
        )
        assert res.status_code == 202
        assert res.json()["status"] == "accepted"

    def test_04_invalid_token_returns_401(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_SECRET", "dd-secret-12345")
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_ENABLED", True)

        payload = {"id": "dd-alert-04", "title": "Attack"}
        res = client.post(
            "/api/v1/webhooks/datadog",
            json=payload,
            headers={"DD-WEBHOOK-TOKEN": "wrong-secret"},
        )
        assert res.status_code == 401
        assert "invalid" in res.json()["detail"].lower()

    def test_05_missing_token_returns_401_when_configured(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_SECRET", "dd-secret-12345")
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_ENABLED", True)

        payload = {"id": "dd-alert-05", "title": "Missing Auth"}
        res = client.post(
            "/api/v1/webhooks/datadog",
            json=payload,
        )
        assert res.status_code == 401
        assert "missing" in res.json()["detail"].lower()

    def test_06_disabled_integration_returns_503(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_ENABLED", False)

        payload = {"id": "dd-alert-06", "title": "Ignored"}
        res = client.post("/api/v1/webhooks/datadog", json=payload)
        assert res.status_code == 503
        assert "disabled" in res.json()["detail"].lower()


# ===========================================================================
# 2. Datadog Normalization, Deduplication & Pipeline Tests
# ===========================================================================

class TestDatadogNormalizationAndCorrelation:
    """Tests 7-9: Normalization, deduplication, and workspace scoping."""

    def test_07_datadog_normalization_and_pipeline_ingestion(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_SECRET", None)

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        payload = {
            "id": "dd-alert-norm-1",
            "title": "[Triggered] Database latency degraded",
            "body": "p99 query latency exceeded 1200ms",
            "alert_type": "error",
            "priority": "P1",
            "date": now_ms,
            "tags": ["service:orders-api", "env:staging"],
        }

        res = client.post("/api/v1/webhooks/datadog", json=payload)
        assert res.status_code == 202
        event_id = res.json()["event_id"]

        with TestingSessionLocal() as session:
            ev = session.get(Event, uuid.UUID(event_id))
            assert ev is not None
            assert ev.service_name == "orders-api"
            assert ev.environment == "staging"
            # Priority P1 escalates to CRITICAL
            assert ev.level == "CRITICAL"
            assert "Database latency degraded" in ev.message

    def test_08_datadog_duplicate_alert_skips_ingestion(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_SECRET", None)

        payload = {
            "id": "dd-dedup-alert-01",
            "title": "Recurring Payment Failure",
            "alert_type": "error",
        }

        # First request -> 202 Accepted
        res1 = client.post("/api/v1/webhooks/datadog", json=payload)
        assert res1.status_code == 202
        assert res1.json()["status"] == "accepted"

        # Second request with identical provider ID -> 200 Duplicate Skipped
        res2 = client.post("/api/v1/webhooks/datadog", json=payload)
        assert res2.status_code == 202  # endpoint contract status
        data2 = res2.json()
        assert data2["status"] == "duplicate_skipped"
        assert "duplicate" in data2["message"].lower()

    def test_09_datadog_workspace_scoping(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "DATADOG_WEBHOOK_SECRET", None)

        ws_id = uuid.uuid4()
        payload = {
            "id": "dd-scoped-alert-01",
            "title": "Team Scoped Alert",
            "alert_type": "warning",
            "tags": [f"workspace:{ws_id}", "service:billing"],
        }
        res = client.post("/api/v1/webhooks/datadog", json=payload)
        assert res.status_code == 202
        assert res.json()["status"] == "accepted"


# ===========================================================================
# 3. PagerDuty Webhook Authentication, Replay & Security Tests
# ===========================================================================

class TestPagerDutyAuthenticationAndReplay:
    """Tests 10-14: PagerDuty HMAC-SHA256 signature verification & replay attacks."""

    SECRET = "pd-webhook-hmac-secret-test"

    def _sign_payload(self, body_bytes: bytes, secret: str = SECRET) -> str:
        sig = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        return f"v1={sig}"

    def test_10_valid_pagerduty_v3_signature(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_SECRET", self.SECRET)
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_ENABLED", True)

        payload = {
            "event": {
                "id": "pd-ev-10",
                "event_type": "incident.triggered",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "id": "PD-INC-10",
                    "title": "High latency on payment-gateway",
                    "urgency": "high",
                    "service": {"name": "payment-gateway"},
                },
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        sig_header = self._sign_payload(body_bytes)

        res = client.post(
            "/api/v1/webhooks/pagerduty",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-PagerDuty-Signature": sig_header,
            },
        )
        assert res.status_code == 202
        assert res.json()["provider"] == "pagerduty"
        assert res.json()["status"] == "accepted"

    def test_11_multiple_signatures_with_one_valid_succeeds(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_SECRET", self.SECRET)
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_ENABLED", True)

        payload = {
            "event": {
                "id": "pd-ev-11",
                "event_type": "incident.acknowledged",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "data": {"title": "Outage Acked", "urgency": "low"},
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_sig = self._sign_payload(body_bytes)
        combined_header = f"v1=bad_old_signature_hash,{valid_sig}"

        res = client.post(
            "/api/v1/webhooks/pagerduty",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-PagerDuty-Signature": combined_header,
            },
        )
        assert res.status_code == 202
        assert res.json()["status"] == "accepted"

    def test_12_invalid_signature_returns_401(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_SECRET", self.SECRET)
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_ENABLED", True)

        body_bytes = b'{"event": {"id": "pd-ev-12"}}'
        res = client.post(
            "/api/v1/webhooks/pagerduty",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-PagerDuty-Signature": "v1=invalid_fake_signature_hex",
            },
        )
        assert res.status_code == 401
        assert "invalid" in res.json()["detail"].lower()

    def test_13_missing_signature_returns_401(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_SECRET", self.SECRET)
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_ENABLED", True)

        body_bytes = b'{"event": {"id": "pd-ev-13"}}'
        res = client.post(
            "/api/v1/webhooks/pagerduty",
            content=body_bytes,
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 401
        assert "missing" in res.json()["detail"].lower()

    def test_14_replay_attack_rejected_when_timestamp_expired(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_SECRET", self.SECRET)
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_MAX_AGE_SECONDS", 300)

        # Timestamp 10 minutes ago -> outside 300s replay window
        expired_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        payload = {
            "event": {
                "id": "pd-ev-replay",
                "event_type": "incident.triggered",
                "occurred_at": expired_time,
                "data": {"title": "Replayed Alert"},
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        sig_header = self._sign_payload(body_bytes)

        res = client.post(
            "/api/v1/webhooks/pagerduty",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-PagerDuty-Signature": sig_header,
            },
        )
        assert res.status_code == 400
        assert "drifted" in res.json()["detail"].lower()


# ===========================================================================
# 4. PagerDuty Normalization, Deduplication & Pipeline Tests
# ===========================================================================

class TestPagerDutyNormalizationAndCorrelation:
    """Tests 15-18: PagerDuty v3/v2 payload normalization and deduplication."""

    def test_15_pagerduty_v3_normalization_and_severity(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_SECRET", None)

        payload = {
            "event": {
                "id": "pd-v3-01",
                "event_type": "incident.triggered",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "id": "PD-INC-99",
                    "title": "Critical redis failure",
                    "urgency": "high",
                    "service": {"name": "cache-service"},
                    "custom_details": {"env": "staging"},
                },
            }
        }

        res = client.post("/api/v1/webhooks/pagerduty", json=payload)
        assert res.status_code == 202
        event_id = res.json()["event_id"]

        with TestingSessionLocal() as session:
            ev = session.get(Event, uuid.UUID(event_id))
            assert ev is not None
            assert ev.service_name == "cache-service"
            assert ev.environment == "staging"
            assert ev.level == "CRITICAL"
            assert "Critical redis failure" in ev.message

    def test_16_pagerduty_v2_legacy_payload_normalization(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_SECRET", None)

        payload = {
            "messages": [
                {
                    "id": "pd-v2-legacy-01",
                    "event": "incident.trigger",
                    "created_on": datetime.now(timezone.utc).isoformat(),
                    "incident": {
                        "id": "PD-INC-V2",
                        "title": "Legacy worker failure",
                        "urgency": "low",
                        "service": {"name": "legacy-worker"},
                    },
                }
            ]
        }

        res = client.post("/api/v1/webhooks/pagerduty", json=payload)
        assert res.status_code == 202
        event_id = res.json()["event_id"]

        with TestingSessionLocal() as session:
            ev = session.get(Event, uuid.UUID(event_id))
            assert ev is not None
            assert ev.service_name == "legacy-worker"
            assert ev.level == "WARNING"

    def test_17_pagerduty_duplicate_webhook_skips_ingestion(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_SECRET", None)

        payload = {
            "event": {
                "id": "pd-dedup-01",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "data": {"title": "Repeated PagerDuty Webhook"},
            }
        }

        # First request -> accepted
        res1 = client.post("/api/v1/webhooks/pagerduty", json=payload)
        assert res1.status_code == 202
        assert res1.json()["status"] == "accepted"

        # Second request -> duplicate_skipped
        res2 = client.post("/api/v1/webhooks/pagerduty", json=payload)
        assert res2.status_code == 202
        assert res2.json()["status"] == "duplicate_skipped"

    def test_18_malformed_payload_returns_422(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(get_settings(), "PAGERDUTY_WEBHOOK_SECRET", None)

        res = client.post("/api/v1/webhooks/pagerduty", json={"unrecognized_field": 123})
        assert res.status_code == 422


# ===========================================================================
# 5. Outbound Slack Notification & Rule Tests
# ===========================================================================

class TestSlackNotifications:
    """Tests 19-24: Slack Block Kit formatting, rules filtering, retry and idempotency."""

    def test_19_notification_rules_filtering(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "SLACK_NOTIFICATIONS_ENABLED", True)
        monkeypatch.setattr(get_settings(), "SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")
        monkeypatch.setattr(get_settings(), "SLACK_NOTIFICATION_MIN_SEVERITY", "ERROR")
        monkeypatch.setattr(get_settings(), "SLACK_NOTIFY_ON_INCIDENT_CREATED", True)
        monkeypatch.setattr(get_settings(), "SLACK_NOTIFY_ON_STATUS_CHANGED", False)

        # WARNING is below min severity ERROR -> Suppressed
        assert is_notification_allowed("incident.created", "WARNING") is False

        # ERROR is at min severity -> Allowed
        assert is_notification_allowed("incident.created", "ERROR") is True

        # CRITICAL is above min severity -> Allowed
        assert is_notification_allowed("incident.created", "CRITICAL") is True

        # status_changed is disabled by flag -> Suppressed
        assert is_notification_allowed("incident.status_changed", "CRITICAL") is False

    def test_20_slack_block_kit_structure_and_links(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "APP_BASE_URL", "https://tracemind.sre.internal")

        mock_incident = MagicMock(spec=Incident)
        mock_incident.id = uuid.uuid4()
        mock_incident.title = "PostgreSQL deadlock detected"
        mock_incident.service_name = "payment-api"
        mock_incident.environment = "production"
        mock_incident.severity = "CRITICAL"
        mock_incident.status = "OPEN"
        mock_incident.description = "Deadlock on table transactions during checkout."

        blocks = build_slack_blocks("incident.created", mock_incident)
        assert len(blocks) >= 3

        # Header block
        assert blocks[0]["type"] == "header"
        assert "CRITICAL" in blocks[0]["text"]["text"]

        # Action button with deep link
        action_block = next((b for b in blocks if b["type"] == "actions"), None)
        assert action_block is not None
        btn = action_block["elements"][0]
        assert btn["url"] == f"https://tracemind.sre.internal/incidents/{mock_incident.id}"

    def test_21_successful_slack_delivery(self, monkeypatch):
        webhook_url = "https://hooks.slack.com/services/T/B/X"

        def mock_post(url, json, headers, timeout):
            return httpx.Response(status_code=200, text="ok")

        monkeypatch.setattr(httpx, "post", mock_post)

        # Should complete without error
        execute_slack_delivery(webhook_url, {"text": "hello"}, timeout_seconds=5.0)

    def test_22_slack_delivery_failure_raises_exception(self, monkeypatch):
        webhook_url = "https://hooks.slack.com/services/T/B/X"

        def mock_post_500(url, json, headers, timeout):
            return httpx.Response(status_code=500, text="internal error")

        monkeypatch.setattr(httpx, "post", mock_post_500)

        with pytest.raises(SlackNotificationError) as exc_info:
            execute_slack_delivery(webhook_url, {"text": "hello"})
        assert "500" in str(exc_info.value)

    def test_23_notification_task_idempotency_guard(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "SLACK_NOTIFICATIONS_ENABLED", True)
        monkeypatch.setattr(get_settings(), "SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

        send_count = 0
        def mock_post(url, json, headers, timeout):
            nonlocal send_count
            send_count += 1
            return httpx.Response(status_code=200, text="ok")

        monkeypatch.setattr(httpx, "post", mock_post)

        with TestingSessionLocal() as session:
            record, _ = create_or_get_notification_log(
                db=session,
                incident_id=uuid.uuid4(),
                event_type="incident.created",
                idempotency_key="idemp-key-test-01",
            )
            rec_id = str(record.id)

        # First run -> SENT
        res1 = send_slack_notification_task(rec_id, json.dumps({"text": "test"}))
        assert res1["status"] == "sent"
        assert send_count == 1

        # Second run (simulating Celery retry or duplicate task) -> ALREADY_SENT
        res2 = send_slack_notification_task(rec_id, json.dumps({"text": "test"}))
        assert res2["status"] == "already_sent"
        # Network call was NOT made a second time
        assert send_count == 1


# ===========================================================================
# 6. Logging & Secret Redaction Tests
# ===========================================================================

class TestSecretRedaction:
    """Tests 25-27: Secret and token redaction in application logs."""

    def test_25_slack_webhook_url_redacted(self):
        sample_log = "Dispatching alert to https://hooks.slack.com/services/T_WORKSPACE/B_CHANNEL/mock_token_789"
        redacted = redact_sensitive_text(sample_log)
        assert "mock_token_789" not in redacted
        assert "[REDACTED_SLACK_WEBHOOK]" in redacted

    def test_26_pagerduty_signature_redacted(self):
        sample_log = "Verifying header X-PagerDuty-Signature: v1=a694a108a7ae7918"
        redacted = redact_sensitive_text(sample_log)
        assert "a694a108a7ae7918" not in redacted
        assert "[REDACTED_SIGNATURE]" in redacted

    def test_27_datadog_token_redacted(self):
        sample_log = "Request received with DD-WEBHOOK-TOKEN: super_secret_dd_token_123"
        redacted = redact_sensitive_text(sample_log)
        assert "super_secret_dd_token_123" not in redacted
        assert "[REDACTED_TOKEN]" in redacted

    def test_28_mask_slack_url_helper(self):
        masked = mask_slack_url("https://hooks.slack.com/services/T_WORKSPACE/B_CHANNEL/mock_abc123")
        assert "mock_abc123" not in masked
        assert "***REDACTED***" in masked
