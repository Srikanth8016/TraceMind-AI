"""
app/services/integrations/pipeline.py — Shared inbound alert processing and deduplication pipeline.

Milestone 19: External Alert Integrations & Notifications.

Flow:
1. Validates deduplication key against WebhookEvent table.
2. If duplicate is detected, returns status='duplicate_skipped' without duplicate database writes.
3. If new, persists Event and associated ProcessingJob.
4. Records WebhookEvent audit record.
5. Commits transaction to PostgreSQL / database.
6. Dispatches Celery / background event processing task.
"""

from datetime import datetime, timezone
import logging
from typing import Optional
import uuid

from fastapi import BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.integration import WebhookEvent
from app.models.job import JobStatus, ProcessingJob
from app.schemas.event import EventCreate
from app.services.task_dispatcher import dispatch_event_processing
from app.utils import sanitize_error

logger = logging.getLogger(__name__)


class InboundAlertResult(BaseModel):
    """Result of inbound alert webhook processing."""
    status: str  # "accepted" or "duplicate_skipped"
    event_id: Optional[uuid.UUID] = None
    job_id: Optional[uuid.UUID] = None
    is_duplicate: bool = False
    message: str = "Alert accepted for processing"


def process_inbound_alert(
    db: Session,
    background_tasks: BackgroundTasks,
    provider: str,
    event_create: EventCreate,
    provider_event_id: str,
    workspace_id: Optional[uuid.UUID] = None,
) -> InboundAlertResult:
    """
    Ingest, deduplicate, and enqueue an alert from an external monitoring provider.
    """
    event_create.validate_timezone()

    # 1. Deduplication Check
    existing_webhook = db.execute(
        select(WebhookEvent).where(
            WebhookEvent.provider == provider,
            WebhookEvent.provider_event_id == provider_event_id,
        )
    ).scalars().first()

    if existing_webhook:
        logger.info(
            "Duplicate webhook ignored for provider=%s provider_event_id=%s (original event_id=%s)",
            provider,
            provider_event_id,
            existing_webhook.event_id,
        )
        return InboundAlertResult(
            status="duplicate_skipped",
            event_id=existing_webhook.event_id,
            job_id=None,
            is_duplicate=True,
            message=f"Duplicate alert delivery ignored for {provider} event {provider_event_id}.",
        )

    # 2. Persist new Event
    event = Event(
        id=uuid.uuid4(),
        service_name=event_create.service_name,
        environment=event_create.environment,
        level=event_create.level.value,
        message=event_create.message,
        timestamp=event_create.timestamp,
    )
    db.add(event)
    db.flush()

    # 3. Create ProcessingJob
    job = ProcessingJob(
        id=uuid.uuid4(),
        event_id=event.id,
        status=JobStatus.PENDING.value,
        attempt_count=0,
    )
    db.add(job)
    db.flush()

    # 4. Record WebhookEvent audit record
    webhook_record = WebhookEvent(
        id=uuid.uuid4(),
        provider=provider,
        provider_event_id=provider_event_id,
        event_id=event.id,
        status="PROCESSED",
        received_at=datetime.now(timezone.utc),
        payload_summary=event.message[:250],
    )
    db.add(webhook_record)

    # 5. Commit transaction
    db.commit()
    db.refresh(event)
    db.refresh(job)

    # 6. Dispatch to background worker
    try:
        dispatch_event_processing(str(job.id), background_tasks)
    except Exception as exc:
        job.status = JobStatus.FAILED.value
        job.error_message = f"Failed to enqueue processing task: {sanitize_error(str(exc))}"
        db.commit()
        logger.exception("Failed to dispatch task for event %s: %s", event.id, exc)

    logger.info(
        "Successfully ingested %s webhook: event_id=%s, job_id=%s (provider_event_id=%s)",
        provider,
        event.id,
        job.id,
        provider_event_id,
    )

    return InboundAlertResult(
        status="accepted",
        event_id=event.id,
        job_id=job.id,
        is_duplicate=False,
        message="Alert successfully ingested and enqueued for correlation.",
    )
