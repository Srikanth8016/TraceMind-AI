"""
Router for the event ingestion API.

A FastAPI ``APIRouter`` works exactly like the main ``FastAPI`` application
object for defining routes, but it is a *sub-router* that gets mounted onto
the application in ``main.py``.  This keeps each resource (events, incidents,
traces…) in its own file instead of growing main.py into an unmaintainable
monolith.

Milestone 3 changes
-------------------
* POST /api/v1/events now persists to PostgreSQL and returns the full record.
* GET  /api/v1/events/{event_id} retrieves a single event by UUID.
* Both endpoints receive a ``Session`` via FastAPI's ``Depends(get_db)``
  dependency — the session is opened before the handler and closed after,
  regardless of success or error.
"""

from typing import Annotated
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.event import Event
from app.models.job import JobStatus, ProcessingJob
from app.schemas.event import (
    EventCreate,
    EventListQuery,
    EventListResponse,
    EventResponse,
)
from app.schemas.job import EventIngestResponse
from app.services.task_dispatcher import dispatch_event_processing
from app.tasks import process_event_task
from app.utils import sanitize_error

# ---------------------------------------------------------------------------
# Router instance
# ---------------------------------------------------------------------------
# `prefix` is prepended to every route defined below, so we write "/events"
# here and get "/api/v1/events" when the router is mounted with the v1 prefix
# in main.py.
#
# `tags` group all routes under a single heading in the Swagger UI — a small
# but important detail for developer experience.

router = APIRouter(prefix="/events", tags=["events"])


# ---------------------------------------------------------------------------
# POST /api/v1/events — ingest and persist a new event
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# POST /api/v1/events — ingest, persist, and enqueue event for processing (Milestone 6)
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=EventIngestResponse,
    status_code=202,
    summary="Ingest and enqueue a new event",
    description=(
        "Accept a structured event from any instrumented service. "
        "Persists the event and an associated processing job in PostgreSQL, "
        "then enqueues a background task via Celery/Redis or in-process background worker. "
        "Returns HTTP 202 Accepted with the event ID, job ID, and initial status."
    ),
)
def create_event(
    payload: EventCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> EventIngestResponse:
    """
    Ingest a validated event, persist it to PostgreSQL, and enqueue for processing.

    Flow
    ----
    1. Validate payload schema and timezone.
    2. Persist Event record.
    3. Persist ProcessingJob record with status PENDING.
    4. Commit transaction to ensure data is safely stored in PostgreSQL.
    5. Dispatch task via Celery/Redis or BackgroundTasks in demo mode.
    6. If enqueueing to Redis fails in standard mode, mark job FAILED and return 503.
    7. Return HTTP 202 with Event and Job identifiers.
    """
    try:
        payload.validate_timezone()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    event = Event(
        id=uuid.uuid4(),             # generate in Python → works in SQLite tests too
        service_name=payload.service_name,
        environment=payload.environment,
        level=payload.level.value,   # convert SeverityLevel enum → plain str
        message=payload.message,
        timestamp=payload.timestamp,
    )

    db.add(event)
    db.flush()

    # Create associated processing job tracking record
    job = ProcessingJob(
        id=uuid.uuid4(),
        event_id=event.id,
        status=JobStatus.PENDING.value,
        attempt_count=0,
    )
    db.add(job)
    db.commit()
    db.refresh(event)
    db.refresh(job)

    # Dispatch to background task runner (Celery in production, BackgroundTasks in demo mode)
    try:
        dispatch_event_processing(str(job.id), background_tasks)
    except Exception as enqueue_exc:
        # Consistency recovery: mark job FAILED so it does not falsely appear queued
        job.status = JobStatus.FAILED.value
        job.error_message = f"Failed to enqueue background processing task: {sanitize_error(str(enqueue_exc))}"
        db.commit()
        raise HTTPException(
            status_code=503,
            detail="Event was saved, but task enqueueing to Redis failed. Job is marked FAILED.",
        ) from enqueue_exc

    return EventIngestResponse(
        id=event.id,
        event_id=event.id,
        service_name=event.service_name,
        environment=event.environment,
        level=event.level,
        message=event.message,
        timestamp=event.timestamp,
        created_at=event.created_at,
        job_id=job.id,
        status=JobStatus.PENDING,
        job_status=JobStatus.PENDING,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/events — list and filter persisted events (Milestone 4)
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=EventListResponse,
    status_code=200,
    summary="List persisted events",
    description=(
        "Retrieve a paginated list of persisted events with optional filtering "
        "by service_name, environment, and severity level. "
        "Results are deterministically ordered by timestamp descending, then id descending."
    ),
)
def list_events(
    query: Annotated[EventListQuery, Query()],
    db: Session = Depends(get_db),
) -> EventListResponse:
    """
    List events from PostgreSQL with server-side filtering, count, and pagination.

    Flow
    ----
    1. FastAPI / Pydantic validates query parameters against ``EventListQuery``.
       Any invalid parameter (unknown level, negative offset, limit > 100, etc.)
       automatically produces HTTP 422 before this function executes.
    2. Build filter conditions using SQLAlchemy binary expressions:
       - service_name == query.service_name (exact match)
       - environment == query.environment (exact match)
       - level == query.level.value (exact match)
    3. Compute total count of matching rows BEFORE applying limit/offset using
       ``SELECT count(events.id) ... WHERE ...``.
    4. Fetch the paginated slice using ``ORDER BY timestamp DESC, id DESC``,
       ``LIMIT``, and ``OFFSET``.
    5. Return ``EventListResponse`` containing items, limit, offset, and total.
    """
    conditions = []
    if query.service_name is not None:
        conditions.append(Event.service_name == query.service_name)
    if query.environment is not None:
        conditions.append(Event.environment == query.environment)
    if query.level is not None:
        conditions.append(Event.level == query.level.value)

    # 1. Total matching count before pagination
    count_stmt = select(func.count(Event.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = db.scalar(count_stmt) or 0

    # 2. Paginated rows with deterministic tie-breaking order (timestamp DESC, id DESC)
    items_stmt = select(Event)
    if conditions:
        items_stmt = items_stmt.where(*conditions)
    items_stmt = (
        items_stmt
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(query.limit)
        .offset(query.offset)
    )
    events = list(db.scalars(items_stmt).all())

    return EventListResponse(
        items=events,
        limit=query.limit,
        offset=query.offset,
        total=total,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/events/{event_id} — retrieve a single event by UUID
# ---------------------------------------------------------------------------

@router.get(
    "/{event_id}",
    response_model=EventResponse,
    status_code=200,
    summary="Retrieve an event by ID",
    description=(
        "Look up a persisted event by its UUID primary key. "
        "Returns HTTP 404 if no event with that ID exists."
    ),
)
def get_event(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> EventResponse:
    """
    Return a single event identified by ``event_id``.

    FastAPI automatically parses and validates the UUID path parameter.
    A malformed UUID string (e.g. "not-a-uuid") produces HTTP 422 before
    this handler is called.

    We use ``db.get()`` (SQLAlchemy 2.x identity-map lookup + SELECT) rather
    than ``db.query(...).filter(...).first()`` because it is cleaner and
    benefits from the session-level identity map cache on repeated lookups.
    """
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(
            status_code=404,
            detail=f"Event with id={event_id!s} not found.",
        )
    return event
