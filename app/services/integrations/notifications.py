"""
app/services/integrations/notifications.py — Notification orchestration and after-commit dispatch.

Milestone 19: External Alert Integrations & Notifications.

Guarantees:
1. Rules Filtering: Evaluates severity threshold and event type enablement before dispatch.
2. Idempotency: Uses NotificationLog table with unique idempotency_key to prevent duplicate sends.
3. Transaction Safety: Notification HTTP calls are NEVER executed inside active database transactions.
4. Fault Isolation: Slack API downtime never impacts core incident lifecycle transitions.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Optional
import uuid

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.integration import NotificationLog
from app.services.integrations.slack import (
    build_slack_blocks,
    create_or_get_notification_log,
    is_notification_allowed,
)
from app.services.task_dispatcher import dispatch_slack_notification

logger = logging.getLogger(__name__)


def dispatch_incident_notification(
    db: Session,
    incident: Incident,
    event_type: str,
    background_tasks: Optional[BackgroundTasks] = None,
    extra_context: Optional[dict[str, Any]] = None,
) -> Optional[NotificationLog]:
    """
    Evaluate, log, and asynchronously dispatch an outbound Slack notification.

    Parameters
    ----------
    db : Session
        Active database session.
    incident : Incident
        Incident instance for which notification is triggered.
    event_type : str
        Lifecycle event type (e.g. 'incident.created', 'incident.status_changed',
        'incident.severity_escalated', 'investigation.completed', 'investigation.failed').
    background_tasks : Optional[BackgroundTasks]
        FastAPI BackgroundTasks instance (if inside HTTP request).
    extra_context : Optional[dict[str, Any]]
        Optional additional context (e.g. investigation report summary, job_id).

    Returns
    -------
    Optional[NotificationLog]
        The created or existing NotificationLog, or None if suppressed by rules.
    """
    # 1. Evaluate notification rules (enabled flag, min severity, event type)
    if not is_notification_allowed(event_type, incident.severity):
        logger.debug(
            "Notification suppressed by rules for incident %s (event_type=%s, severity=%s)",
            incident.id,
            event_type,
            incident.severity,
        )
        return None

    # 2. Build deterministic idempotency key
    extra = extra_context or {}
    if event_type == "incident.created":
        idempotency_key = f"incident_created:{incident.id}"
    elif event_type == "incident.severity_escalated":
        idempotency_key = f"incident_severity:{incident.id}:{incident.severity}"
    elif event_type == "incident.status_changed":
        idempotency_key = f"incident_status:{incident.id}:{incident.status}"
    elif event_type in ("investigation.completed", "investigation.failed"):
        job_id = extra.get("job_id", incident.id)
        idempotency_key = f"{event_type.replace('.', '_')}:{job_id}"
    else:
        idempotency_key = f"{event_type}:{incident.id}:{uuid.uuid4()}"

    # 3. Create or retrieve audit log record
    record, is_new = create_or_get_notification_log(
        db=db,
        incident_id=incident.id,
        event_type=event_type,
        idempotency_key=idempotency_key,
    )

    # 4. If already sent, do not re-dispatch
    if not is_new and record.status == "SENT":
        logger.info(
            "Notification %s already marked SENT for idempotency_key %s. Skipping re-dispatch.",
            record.id,
            idempotency_key,
        )
        return record

    # 5. Build Block Kit payload
    blocks = build_slack_blocks(
        event_type=event_type,
        incident=incident,
        extra_context=extra_context,
    )
    payload_dict = {
        "text": f"[{incident.severity}] {incident.title}",
        "blocks": blocks,
    }
    payload_json = json.dumps(payload_dict)

    # 6. Dispatch background task (after commit, decoupled from DB transaction)
    try:
        dispatch_slack_notification(
            notification_id=str(record.id),
            payload_json=payload_json,
            background_tasks=background_tasks,
        )
        logger.info(
            "Dispatched Slack notification task %s (incident=%s, event_type=%s, key=%s)",
            record.id,
            incident.id,
            event_type,
            idempotency_key,
        )
    except Exception as exc:
        record.status = "FAILED"
        record.error_message = f"Failed to enqueue Slack dispatch task: {exc}"
        db.commit()
        logger.exception("Failed to dispatch Slack notification for %s: %s", incident.id, exc)

    return record
