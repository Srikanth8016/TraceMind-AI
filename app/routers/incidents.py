"""
app/routers/incidents.py — Router for querying grouped incidents and associated events.

Milestone 7: Deterministic incident grouping and event correlation.
"""

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.event import Event
from app.models.incident import Incident, IncidentStatus
from app.schemas.incident import (
    IncidentEventListResponse,
    IncidentListResponse,
    IncidentResponse,
)

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get(
    "",
    response_model=IncidentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List, filter, and paginate incidents",
    description=(
        "Retrieve a paginated list of correlated error incidents. "
        "Supports filtering by service_name, environment, severity, and status. "
        "Deterministic ordering by last_seen_at DESC, id DESC."
    ),
)
def list_incidents(
    service_name: Annotated[
        str | None,
        Query(max_length=100, description="Exact match on service name."),
    ] = None,
    environment: Annotated[
        str | None,
        Query(max_length=50, description="Exact match on deployment environment."),
    ] = None,
    severity: Annotated[
        str | None,
        Query(pattern="^(ERROR|CRITICAL)$", description="Filter by severity (ERROR or CRITICAL)."),
    ] = None,
    status_filter: Annotated[
        IncidentStatus | None,
        Query(alias="status", description="Filter by status (OPEN, ACKNOWLEDGED, RESOLVED)."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Maximum number of incidents per page (1–100)."),
    ] = 20,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based index of the first incident to return."),
    ] = 0,
    db: Session = Depends(get_db),
) -> IncidentListResponse:
    """
    List incidents with optional filtering and pagination.
    """
    stmt = select(Incident)

    if service_name is not None:
        stmt = stmt.where(Incident.service_name == service_name)
    if environment is not None:
        stmt = stmt.where(Incident.environment == environment)
    if severity is not None:
        stmt = stmt.where(Incident.severity == severity)
    if status_filter is not None:
        stmt = stmt.where(Incident.status == status_filter.value)

    # Calculate total matching count before applying pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    # Deterministic tie-breaker: last_seen_at DESC, id DESC
    stmt = stmt.order_by(Incident.last_seen_at.desc(), Incident.id.desc())
    stmt = stmt.limit(limit).offset(offset)

    items = db.execute(stmt).scalars().all()

    return IncidentListResponse(
        items=list(items),
        limit=limit,
        offset=offset,
        total=total,
    )


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve incident details",
    description=(
        "Retrieve the full details of an incident by its UUID primary key. "
        "Returns HTTP 404 if the incident does not exist."
    ),
)
def get_incident(
    incident_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> IncidentResponse:
    """
    Fetch an incident by UUID.
    """
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with id={incident_id!s} not found.",
        )
    return incident


@router.get(
    "/{incident_id}/events",
    response_model=IncidentEventListResponse,
    status_code=status.HTTP_200_OK,
    summary="List events belonging to an incident",
    description=(
        "Retrieve a paginated list of individual error events correlated to this incident. "
        "Returns HTTP 404 if the parent incident does not exist. "
        "Deterministic ordering by timestamp DESC, id DESC."
    ),
)
def list_incident_events(
    incident_id: uuid.UUID,
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Maximum number of events per page (1–100)."),
    ] = 20,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based index of the first event to return."),
    ] = 0,
    db: Session = Depends(get_db),
) -> IncidentEventListResponse:
    """
    List events correlated to an incident.
    """
    # 1. Verify parent incident exists
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with id={incident_id!s} not found.",
        )

    # 2. Query events belonging to this incident
    stmt = select(Event).where(Event.incident_id == incident_id)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    # Deterministic ordering: timestamp DESC, id DESC
    stmt = stmt.order_by(Event.timestamp.desc(), Event.id.desc())
    stmt = stmt.limit(limit).offset(offset)

    events = db.execute(stmt).scalars().all()

    return IncidentEventListResponse(
        items=list(events),
        limit=limit,
        offset=offset,
        total=total,
    )
