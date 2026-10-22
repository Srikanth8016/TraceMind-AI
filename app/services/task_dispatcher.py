"""
app/services/task_dispatcher.py — Unified background task dispatcher.

Supports:
1. Production & Local Dev Mode (DEMO_MODE=False):
   Dispatches tasks asynchronously to Celery via Redis broker (process_event_task.delay / investigate_incident_task.delay).
2. Zero-Budget Demo Mode (DEMO_MODE=True):
   Dispatches tasks via FastAPI BackgroundTasks (or in-process threaded execution),
   running on a single free Render Web Service container without requiring a paid separate Celery worker or Redis broker.
"""

import logging
import threading
from typing import Optional
from fastapi import BackgroundTasks

from app.config import get_settings
from app.tasks import investigate_incident_task, process_event_task, send_slack_notification_task

logger = logging.getLogger(__name__)


def _run_sync_event_task(job_id: str) -> None:
    try:
        process_event_task.apply(args=[job_id])
    except Exception as exc:
        logger.exception("Error executing event task in demo mode for job %s: %s", job_id, exc)


def _run_sync_investigation_task(job_id: str, incident_id: str) -> None:
    try:
        investigate_incident_task.apply(args=[job_id, incident_id])
    except Exception as exc:
        logger.exception(
            "Error executing investigation task in demo mode for job %s (incident %s): %s",
            job_id,
            incident_id,
            exc,
        )


def _run_sync_slack_task(notification_id: str, payload_json: str) -> None:
    try:
        send_slack_notification_task.apply(args=[notification_id, payload_json])
    except Exception as exc:
        logger.exception("Error executing Slack notification in demo mode for %s: %s", notification_id, exc)


def dispatch_event_processing(job_id: str, background_tasks: Optional[BackgroundTasks] = None) -> None:
    """
    Dispatch an event processing task.
    In DEMO_MODE, runs asynchronously in-process via FastAPI BackgroundTasks or background thread.
    In standard mode, dispatches to the Celery/Redis broker.
    """
    settings = get_settings()
    if settings.DEMO_MODE:
        logger.info("DEMO_MODE active: Scheduling event job %s in-process via background task.", job_id)
        if background_tasks is not None:
            background_tasks.add_task(_run_sync_event_task, job_id)
        else:
            threading.Thread(target=_run_sync_event_task, args=(job_id,), daemon=True).start()
    else:
        process_event_task.delay(job_id)


def dispatch_incident_investigation(
    job_id: str, incident_id: str, background_tasks: Optional[BackgroundTasks] = None
) -> None:
    """
    Dispatch an AI incident investigation task.
    In DEMO_MODE, runs asynchronously in-process via FastAPI BackgroundTasks or background thread.
    In standard mode, dispatches to the Celery/Redis broker.
    """
    settings = get_settings()
    if settings.DEMO_MODE:
        logger.info(
            "DEMO_MODE active: Scheduling investigation job %s for incident %s in-process via background task.",
            job_id,
            incident_id,
        )
        if background_tasks is not None:
            background_tasks.add_task(_run_sync_investigation_task, job_id, incident_id)
        else:
            threading.Thread(target=_run_sync_investigation_task, args=(job_id, incident_id), daemon=True).start()
    else:
        investigate_incident_task.delay(job_id, incident_id)


def dispatch_slack_notification(
    notification_id: str,
    payload_json: str,
    background_tasks: Optional[BackgroundTasks] = None,
) -> None:
    """
    Dispatch a Slack incident notification task.
    In DEMO_MODE, runs asynchronously in-process via FastAPI BackgroundTasks or background thread.
    In standard mode, dispatches to the Celery/Redis broker.
    """
    settings = get_settings()
    if settings.DEMO_MODE:
        logger.info(
            "DEMO_MODE active: Scheduling Slack notification %s in-process via background task.",
            notification_id,
        )
        if background_tasks is not None:
            background_tasks.add_task(_run_sync_slack_task, notification_id, payload_json)
        else:
            threading.Thread(target=_run_sync_slack_task, args=(notification_id, payload_json), daemon=True).start()
    else:
        send_slack_notification_task.delay(notification_id, payload_json)

