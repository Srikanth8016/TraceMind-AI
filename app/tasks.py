"""
app/tasks.py — Celery worker tasks for asynchronous event processing.

Milestone 6: Background event processing with Celery and Redis.

Design Decisions
----------------
1. **Database Session**: Worker tasks run outside FastAPI request lifecycle,
   so we instantiate a direct ``SessionLocal()`` with guaranteed teardown.
2. **Idempotency**: If the job is already marked COMPLETED, the task exits
   early without repeating processing or side effects.
3. **Bounded Retries with Exponential Backoff**: Transient errors trigger
   exponential backoff up to ``max_retries=3``.
4. **Permanent Failure Fast-Path**: Missing events or irrecoverable errors
   transition the job directly to FAILED without wasted retries.
5. **Sanitized Error Reporting**: Connection strings and credentials are
   redacted from stored error messages.
"""

from datetime import datetime, timezone
import re
import uuid

from celery.utils.log import get_task_logger

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.event import Event
from app.models.incident import Incident
from app.models.integration import NotificationLog
from app.models.investigation import InvestigationJob, InvestigationStatus
from app.models.job import JobStatus, ProcessingJob
from app.services.correlation import correlate_event_to_incident
from app.services.investigation import run_incident_investigation
from app.services.llm import get_llm_provider
from app.utils import sanitize_error

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def process_event_task(self, job_id: str) -> dict:
    """
    Background worker task: loads an event from PostgreSQL, normalizes content,
    and updates job status.

    Parameters
    ----------
    job_id : str
        String UUID of the ProcessingJob record.
    """
    session = SessionLocal()
    try:
        parsed_job_id = uuid.UUID(job_id)
        job = session.get(ProcessingJob, parsed_job_id)

        if not job:
            logger.warning("Job %s not found in database. Aborting without retry.", job_id)
            return {"status": "failed", "reason": "job_not_found"}

        # -------------------------------------------------------------------
        # 1. Idempotency guard
        # -------------------------------------------------------------------
        if job.status == JobStatus.COMPLETED.value:
            logger.info("Job %s already marked COMPLETED. Skipping duplicate execution.", job_id)
            return {"status": "already_completed", "job_id": job_id}

        # -------------------------------------------------------------------
        # 2. Transition to PROCESSING
        # -------------------------------------------------------------------
        job.attempt_count += 1
        job.status = JobStatus.PROCESSING.value
        job.error_message = None
        job.updated_at = datetime.now(timezone.utc)
        session.commit()

        # -------------------------------------------------------------------
        # 3. Load associated Event
        # -------------------------------------------------------------------
        event = session.get(Event, job.event_id)
        if not event:
            # Permanent failure: event was deleted or never persisted
            logger.error("Event %s for job %s not found. Marking FAILED.", job.event_id, job_id)
            job.status = JobStatus.FAILED.value
            job.error_message = "Associated event not found in database."
            job.updated_at = datetime.now(timezone.utc)
            session.commit()
            return {"status": "failed", "reason": "event_not_found"}

        # -------------------------------------------------------------------
        # 4. Incident Correlation (Milestone 7)
        # -------------------------------------------------------------------
        incident = correlate_event_to_incident(session, event)
        incident_id_str = str(incident.id) if incident else None

        # -------------------------------------------------------------------
        # 5. Mark COMPLETED
        # -------------------------------------------------------------------
        job.status = JobStatus.COMPLETED.value
        job.error_message = None
        job.updated_at = datetime.now(timezone.utc)
        session.commit()

        return {
            "status": "completed",
            "job_id": str(job.id),
            "event_id": str(event.id),
            "incident_id": incident_id_str,
            "attempt_count": job.attempt_count,
        }

    except Exception as exc:
        logger.exception("Error processing job %s: %s", job_id, exc)
        session.rollback()

        # Reload job in a fresh state to persist retry/failed status
        try:
            job = session.get(ProcessingJob, uuid.UUID(job_id))
            if job:
                sanitized_msg = sanitize_error(str(exc))
                if self.request.retries < self.max_retries:
                    # Bounded exponential backoff: 2, 4, 8... capped at 60s
                    countdown = min(2 ** (self.request.retries + 1), 60)
                    job.status = JobStatus.PENDING.value
                    job.error_message = (
                        f"Transient failure (attempt {job.attempt_count}): {sanitized_msg}"
                    )
                    job.updated_at = datetime.now(timezone.utc)
                    session.commit()

                    raise self.retry(exc=exc, countdown=countdown)
                else:
                    # Retry limit reached: mark FAILED
                    job.status = JobStatus.FAILED.value
                    job.error_message = (
                        f"Max retries exceeded ({self.max_retries} attempts): {sanitized_msg}"
                    )
                    job.updated_at = datetime.now(timezone.utc)
                    session.commit()
        except Exception as update_exc:
            logger.error("Failed to update job status on error: %s", update_exc)

        raise exc

    finally:
        session.close()


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def investigate_incident_task(self, job_id: str, incident_id: str) -> dict:
    """
    Background worker task: collects incident evidence, queries the LLM provider,
    validates structured output and citations, and persists the investigation report.
    """
    session = SessionLocal()
    try:
        parsed_job_id = uuid.UUID(job_id)
        job = session.get(InvestigationJob, parsed_job_id)
        if not job:
            logger.warning("InvestigationJob %s not found in database. Aborting.", job_id)
            return {"status": "failed", "reason": "job_not_found"}

        # Idempotency guard: do not re-execute already completed investigations
        if job.status == InvestigationStatus.COMPLETED.value:
            logger.info("InvestigationJob %s already COMPLETED. Skipping duplicate execution.", job_id)
            return {"status": "already_completed", "job_id": job_id}

        # Transition status to PROCESSING
        job.attempt_count += 1
        job.status = InvestigationStatus.PROCESSING.value
        job.error_message = None
        job.updated_at = datetime.now(timezone.utc)
        session.commit()

        # Load target incident
        parsed_incident_id = uuid.UUID(incident_id)
        incident = session.get(Incident, parsed_incident_id)
        if not incident:
            logger.error("Incident %s for InvestigationJob %s not found. Marking FAILED.", incident_id, job_id)
            job.status = InvestigationStatus.FAILED.value
            job.error_message = f"Associated incident {incident_id} not found."
            job.updated_at = datetime.now(timezone.utc)
            session.commit()
            return {"status": "failed", "reason": "incident_not_found"}

        # Run investigation through LLM abstraction
        provider = get_llm_provider()
        report = run_incident_investigation(session, incident, provider)

        # Persist structured report
        job.report = report.model_dump()
        job.status = InvestigationStatus.COMPLETED.value
        job.error_message = None
        job.completed_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        session.commit()

        try:
            from app.services.integrations.notifications import dispatch_incident_notification
            dispatch_incident_notification(
                session,
                incident,
                "investigation.completed",
                extra_context={
                    "job_id": str(job.id),
                    "summary": f"{len(report.hypotheses)} root-cause hypotheses evaluated.",
                },
            )
        except Exception as notify_exc:
            logger.warning("Failed to dispatch investigation completed notification: %s", notify_exc)

        logger.info(
            "InvestigationJob %s completed successfully for incident %s (hypotheses=%d)",
            job.id,
            incident.id,
            len(report.hypotheses),
        )
        return {
            "status": "completed",
            "job_id": str(job.id),
            "incident_id": str(incident.id),
            "hypotheses_count": len(report.hypotheses),
        }

    except Exception as exc:
        logger.exception("Error executing investigation job %s: %s", job_id, exc)
        session.rollback()

        try:
            job = session.get(InvestigationJob, uuid.UUID(job_id))
            if job:
                sanitized_msg = sanitize_error(str(exc))
                if self.request.retries < self.max_retries:
                    countdown = min(2 ** (self.request.retries + 1), 60)
                    job.status = InvestigationStatus.PENDING.value
                    job.error_message = f"Transient failure (attempt {job.attempt_count}): {sanitized_msg}"
                    job.updated_at = datetime.now(timezone.utc)
                    session.commit()
                    raise self.retry(exc=exc, countdown=countdown)
                else:
                    job.status = InvestigationStatus.FAILED.value
                    job.error_message = f"Max retries exceeded ({self.max_retries} attempts): {sanitized_msg}"
                    job.updated_at = datetime.now(timezone.utc)
                    session.commit()

                    try:
                        target_inc = session.get(Incident, uuid.UUID(incident_id))
                        if target_inc:
                            from app.services.integrations.notifications import dispatch_incident_notification
                            dispatch_incident_notification(
                                session,
                                target_inc,
                                "investigation.failed",
                                extra_context={
                                    "job_id": str(job.id),
                                    "summary": job.error_message,
                                },
                            )
                    except Exception as notify_exc:
                        logger.warning("Failed to dispatch investigation failure notification: %s", notify_exc)
        except Exception as update_exc:
            logger.error("Failed to update investigation job status on error: %s", update_exc)

        raise exc

    finally:
        session.close()


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def send_slack_notification_task(
    self,
    notification_log_id: str,
    payload_json: str,
) -> dict:
    """
    Background worker task: delivers outbound notification to Slack incoming webhook.
    Enforces at-most-once delivery via NotificationLog idempotency check.
    """
    import json
    from app.config import get_settings
    from app.services.integrations.slack import execute_slack_delivery, mask_slack_url

    session = SessionLocal()
    settings = get_settings()
    try:
        parsed_id = uuid.UUID(notification_log_id)
        record = session.get(NotificationLog, parsed_id)
        if not record:
            logger.warning("NotificationLog %s not found. Skipping.", notification_log_id)
            return {"status": "failed", "reason": "not_found"}

        # Idempotency guard: if already sent, exit early
        if record.status == "SENT":
            logger.info("Notification %s already marked SENT. Skipping duplicate execution.", notification_log_id)
            return {"status": "already_sent"}

        if not settings.SLACK_NOTIFICATIONS_ENABLED or not settings.SLACK_WEBHOOK_URL:
            record.status = "SKIPPED"
            record.error_message = "Slack notifications disabled or webhook URL not configured."
            session.commit()
            return {"status": "skipped"}

        payload = json.loads(payload_json)
        masked_url = mask_slack_url(settings.SLACK_WEBHOOK_URL)
        logger.info("Delivering Slack notification %s to %s", notification_log_id, masked_url)

        execute_slack_delivery(
            webhook_url=settings.SLACK_WEBHOOK_URL,
            payload=payload,
            timeout_seconds=settings.REQUEST_TIMEOUT_SECONDS,
        )

        record.status = "SENT"
        record.sent_at = datetime.now(timezone.utc)
        record.error_message = None
        session.commit()
        return {"status": "sent", "notification_id": notification_log_id}

    except Exception as exc:
        logger.exception("Failed to deliver Slack notification %s: %s", notification_log_id, exc)
        session.rollback()

        try:
            record = session.get(NotificationLog, uuid.UUID(notification_log_id))
            if record:
                sanitized_msg = sanitize_error(str(exc))
                if self.request.retries < self.max_retries:
                    countdown = min(2 ** (self.request.retries + 1), 60)
                    record.status = "PENDING"
                    record.error_message = f"Transient failure (attempt {self.request.retries + 1}): {sanitized_msg}"
                    session.commit()
                    raise self.retry(exc=exc, countdown=countdown)
                else:
                    record.status = "FAILED"
                    record.error_message = f"Max retries exceeded: {sanitized_msg}"
                    session.commit()
        except Exception as update_exc:
            logger.error("Failed to update notification log status: %s", update_exc)

        raise exc

    finally:
        session.close()


