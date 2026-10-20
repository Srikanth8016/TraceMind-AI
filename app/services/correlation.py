"""
app/services/correlation.py — Incident correlation and grouping engine.

Milestone 7: Deterministic incident grouping and event correlation.

Design Principles
-----------------
1. **Severity Qualification**: Only ERROR and CRITICAL events are correlated
   into incidents. INFO, DEBUG, and WARNING logs are operational traces and do
   not create or correlate into incidents.
2. **Bounded Correlation Time Window**:
   Configured via ``INCIDENT_CORRELATION_WINDOW_SECONDS`` (default: 3600s / 1 hour).
   If an error recurs within 1 hour of the incident's `last_seen_at`, it attaches
   to the existing incident. If the gap exceeds the window, it starts a fresh incident.
3. **Lifecycle Respect**:
   Only OPEN and ACKNOWLEDGED incidents absorb incoming events.
   RESOLVED incidents are treated as historical; recurring errors create a new OPEN incident.
4. **Severity Escalation**:
   If an incident was created by an ERROR event and subsequently observes a CRITICAL event,
   its severity escalates to CRITICAL.
5. **Idempotency Guard**:
   If an event already has an `incident_id` assigned, it is not double-counted even if the
   Celery task is re-delivered or re-executed.
6. **Concurrency & Locking**:
   In PostgreSQL, `with_for_update()` locks the candidate incident row to serialize
   concurrent worker updates and prevent lost increments.
"""

from datetime import datetime, timedelta, timezone
import logging
import os
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.incident import Incident, IncidentStatus
from app.services.fingerprint import extract_incident_title, generate_fingerprint

logger = logging.getLogger(__name__)

# Configurable correlation time window in seconds (default: 1 hour)
DEFAULT_WINDOW_SECONDS = 3600


def get_correlation_window_seconds() -> int:
    """Retrieve the correlation window from the environment, defaulting to 3600s."""
    raw = os.getenv("INCIDENT_CORRELATION_WINDOW_SECONDS")
    if raw:
        try:
            val = int(raw.strip())
            if val > 0:
                return val
        except ValueError:
            pass
    return DEFAULT_WINDOW_SECONDS


def correlate_event_to_incident(session: Session, event: Event) -> Incident | None:
    """
    Correlate an ingested event to an active incident, or create a new incident.

    Parameters
    ----------
    session : Session
        Active database session within a transaction.
    event : Event
        Persisted Event model instance.

    Returns
    -------
    Incident | None
        The correlated Incident, or None if the event is not eligible for grouping.
    """
    # -----------------------------------------------------------------------
    # 1. Eligibility Check
    # -----------------------------------------------------------------------
    # Only ERROR and CRITICAL events participate in incident correlation
    if event.level not in ("ERROR", "CRITICAL"):
        return None

    # -----------------------------------------------------------------------
    # 2. Idempotency Check
    # -----------------------------------------------------------------------
    # If the event was already correlated to an incident, do not increment again
    if event.incident_id is not None:
        logger.info(
            "Event %s already associated with incident %s. Skipping duplicate correlation.",
            event.id,
            event.incident_id,
        )
        return session.get(Incident, event.incident_id)

    # -----------------------------------------------------------------------
    # 3. Compute Deterministic Fingerprint
    # -----------------------------------------------------------------------
    fingerprint = generate_fingerprint(
        service_name=event.service_name,
        environment=event.environment,
        message=event.message,
    )

    # -----------------------------------------------------------------------
    # 4. Search for Candidate Incident within Time Window
    # -----------------------------------------------------------------------
    window_seconds = get_correlation_window_seconds()
    window_delta = timedelta(seconds=window_seconds)

    # Time-window cutoff: events can correlate if incident was active recently
    event_ts = event.timestamp
    if event_ts.tzinfo is None:
        event_ts = event_ts.replace(tzinfo=timezone.utc)

    window_cutoff = event_ts - window_delta

    # Query active candidate incident (OPEN or ACKNOWLEDGED) with row lock
    query = (
        select(Incident)
        .where(
            Incident.service_name == event.service_name,
            Incident.environment == event.environment,
            Incident.fingerprint == fingerprint,
            Incident.status.in_([
                IncidentStatus.OPEN.value,
                IncidentStatus.ACKNOWLEDGED.value,
            ]),
            Incident.last_seen_at >= window_cutoff,
        )
        .order_by(Incident.last_seen_at.desc())
        .with_for_update()
    )

    candidate = session.execute(query).scalars().first()

    # -----------------------------------------------------------------------
    # 5. Associate with Existing Incident or Create New Incident
    # -----------------------------------------------------------------------
    if candidate is not None:
        # Existing incident found within the correlation window
        event.incident_id = candidate.id
        candidate.event_count += 1

        # Advance last_seen_at if this event is newer
        candidate_last_seen = candidate.last_seen_at
        if candidate_last_seen.tzinfo is None:
            candidate_last_seen = candidate_last_seen.replace(tzinfo=timezone.utc)

        if event_ts > candidate_last_seen:
            candidate.last_seen_at = event_ts

        # Escalate severity to CRITICAL if a CRITICAL event occurs
        if event.level == "CRITICAL" and candidate.severity != "CRITICAL":
            candidate.severity = "CRITICAL"

        candidate.updated_at = datetime.now(timezone.utc)
        logger.info(
            "Correlated event %s to existing incident %s (count=%d)",
            event.id,
            candidate.id,
            candidate.event_count,
        )
        return candidate

    # No existing incident within the correlation window: create a new incident
    title = extract_incident_title(event.message)
    new_incident = Incident(
        id=uuid.uuid4(),
        service_name=event.service_name,
        environment=event.environment,
        fingerprint=fingerprint,
        title=title,
        severity=event.level,
        status=IncidentStatus.OPEN.value,
        first_seen_at=event.timestamp,
        last_seen_at=event.timestamp,
        event_count=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(new_incident)
    session.flush()  # Ensures new_incident.id is materialized

    event.incident_id = new_incident.id
    logger.info(
        "Created new incident %s for event %s (service=%s, fingerprint=%s)",
        new_incident.id,
        event.id,
        event.service_name,
        fingerprint[:8],
    )
    return new_incident
