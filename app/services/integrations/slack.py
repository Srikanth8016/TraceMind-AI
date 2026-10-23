"""
app/services/integrations/slack.py — Outbound Slack incident notification service.

Milestone 19: External Alert Integrations & Notifications.

Features:
- Slack Incoming Webhook delivery formatted with Block Kit.
- Granular notification rule filtering (enabled toggle, event types, minimum severity).
- Idempotent at-most-once delivery via NotificationLog idempotency keys.
- Full context formatting: service, environment, severity, status, and application deep links.
- Fault isolation: external Slack failures never break core incident correlation or updates.
- Redaction of webhook tokens and secrets in all logs.
"""

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Optional
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.incident import Incident
from app.models.integration import NotificationLog
from app.services.integrations.exceptions import SlackNotificationError

logger = logging.getLogger(__name__)

SEVERITY_ORDER = {
    "INFO": 1,
    "WARNING": 2,
    "ERROR": 3,
    "CRITICAL": 4,
}

SLACK_URL_MASK_REGEX = re.compile(r"(https://hooks\.slack\.com/services/)([^/]+/[^/]+/[^/\s]+)")


def mask_slack_url(url: Optional[str]) -> str:
    """Mask sensitive tokens in Slack webhook URL for safe logging."""
    if not url:
        return "<none>"
    return SLACK_URL_MASK_REGEX.sub(r"\1***REDACTED***", url)


def is_notification_allowed(event_type: str, severity: str) -> bool:
    """
    Evaluate whether a notification should be dispatched based on configuration rules.
    """
    settings = get_settings()

    if not settings.SLACK_NOTIFICATIONS_ENABLED:
        return False

    if not settings.SLACK_WEBHOOK_URL:
        return False

    # Check minimum severity threshold
    min_sev = (settings.SLACK_NOTIFICATION_MIN_SEVERITY or "ERROR").upper()
    req_rank = SEVERITY_ORDER.get(min_sev, 3)
    inc_rank = SEVERITY_ORDER.get(severity.upper(), 3)
    if inc_rank < req_rank:
        logger.debug(
            "Slack notification suppressed: severity %s below minimum %s",
            severity,
            min_sev,
        )
        return False

    # Check event type switches
    if event_type in ("incident.created", "incident.severity_escalated"):
        return settings.SLACK_NOTIFY_ON_INCIDENT_CREATED
    elif event_type == "incident.status_changed":
        return settings.SLACK_NOTIFY_ON_STATUS_CHANGED
    elif event_type in ("investigation.completed", "investigation.failed"):
        return settings.SLACK_NOTIFY_ON_INVESTIGATION_COMPLETED

    return True


def build_slack_blocks(
    event_type: str,
    incident: Incident,
    extra_context: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    Construct rich Slack Block Kit layout for an incident event.
    """
    settings = get_settings()
    app_base_url = settings.APP_BASE_URL.rstrip("/") if settings.APP_BASE_URL else None
    incident_link = f"{app_base_url}/incidents/{incident.id}" if app_base_url else None

    # Header title mapping
    if event_type == "incident.created":
        header_text = f"🚨 [{incident.severity}] New Incident: {incident.title[:80]}"
    elif event_type == "incident.severity_escalated":
        header_text = f"⚠️ Incident Escalated to [{incident.severity}]: {incident.title[:80]}"
    elif event_type == "incident.status_changed":
        header_text = f"ℹ️ Incident Status: {incident.status} — {incident.title[:80]}"
    elif event_type == "investigation.completed":
        header_text = f"🤖 AI Investigation Ready: {incident.title[:80]}"
    elif event_type == "investigation.failed":
        header_text = f"❌ AI Investigation Failed: {incident.title[:80]}"
    else:
        header_text = f"📢 Incident Alert: {incident.title[:80]}"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header_text[:150],
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Service:*\n`{incident.service_name}`",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Environment:*\n`{incident.environment}`",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Severity:*\n*{incident.severity}*",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Status:*\n`{incident.status}`",
                },
            ],
        },
    ]

    # Description section
    if incident.description:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Details:*\n{incident.description[:300]}",
            },
        })

    # Extra context (e.g. Investigation findings)
    if extra_context and "summary" in extra_context:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Investigation Summary:*\n{str(extra_context['summary'])[:300]}",
            },
        })

    # Interactive action button if app URL is configured
    if incident_link:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "View in TraceMind",
                        "emoji": True,
                    },
                    "url": incident_link,
                    "style": "primary",
                }
            ],
        })

    return blocks


def create_or_get_notification_log(
    db: Session,
    incident_id: uuid.UUID,
    event_type: str,
    idempotency_key: str,
) -> tuple[NotificationLog, bool]:
    """
    Retrieve existing NotificationLog or create a new PENDING record.
    Returns (record, is_new).
    """
    existing = db.execute(
        select(NotificationLog).where(
            NotificationLog.idempotency_key == idempotency_key
        )
    ).scalars().first()

    if existing:
        return existing, False

    record = NotificationLog(
        id=uuid.uuid4(),
        incident_id=incident_id,
        channel="slack",
        event_type=event_type,
        status="PENDING",
        idempotency_key=idempotency_key,
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, True


def execute_slack_delivery(
    webhook_url: str,
    payload: dict[str, Any],
    timeout_seconds: float = 5.0,
) -> None:
    """
    Perform external HTTP POST request to Slack incoming webhook.
    Enforces SSRF prevention by verifying destination begins with 'https://hooks.slack.com/'.
    Raises SlackNotificationError on timeout, 4xx, or 5xx.
    """
    if not webhook_url or not webhook_url.startswith("https://hooks.slack.com/"):
        raise SlackNotificationError(
            "SSRF protection violation: Slack webhook URL must start with 'https://hooks.slack.com/'"
        )

    headers = {"Content-Type": "application/json"}
    try:
        response = httpx.post(
            webhook_url,
            json=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
        if response.status_code != 200 or response.text.strip().lower() != "ok":
            raise SlackNotificationError(
                f"Slack webhook rejected payload: HTTP {response.status_code} — {response.text[:200]}"
            )
    except httpx.TimeoutException as exc:
        raise SlackNotificationError(f"Slack webhook request timed out after {timeout_seconds}s") from exc
    except httpx.RequestError as exc:
        raise SlackNotificationError(f"Network error communicating with Slack: {exc}") from exc
