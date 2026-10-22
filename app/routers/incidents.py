"""
app/routers/incidents.py — Router for querying grouped incidents and associated events.

Milestone 7: Deterministic incident grouping and event correlation.
"""

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import get_current_active_user
from app.models.incident import IncidentStatus
from app.models.user import User
from app.schemas.incident import (
    IncidentCreate,
    IncidentEventListResponse,
    IncidentListResponse,
    IncidentResponse,
    IncidentStatusUpdate,
    IncidentUpdate,
)
from app.services.incident_service import (
    IncidentConflictError,
    IncidentDatabaseError,
    IncidentNotFoundError,
    IncidentService,
    get_incident_service,
)
from app.services.rbac import WorkspaceAccessDeniedError, WorkspaceNotFoundError

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new incident",
    description="Create and persist an incident record through the service layer scoped to the authenticated user.",
)
def create_incident(
    incident_in: IncidentCreate,
    incident_service: IncidentService = Depends(get_incident_service),
    current_user: User = Depends(get_current_active_user),
) -> IncidentResponse:
    """
    Create a new incident via IncidentService owned by the current active user.
    """
    try:
        return incident_service.create_incident(incident_in, owner_id=current_user.id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except WorkspaceAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )


@router.patch(
    "/{incident_id}/status",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update incident lifecycle status",
    description=(
        "Atomically update an incident's lifecycle status (OPEN, INVESTIGATING, RESOLVED, CLOSED). "
        "Enforces workflow transition rules: OPEN -> INVESTIGATING -> RESOLVED -> CLOSED. "
        "Reopening allowed from RESOLVED -> OPEN or CLOSED -> OPEN. "
        "Direct transitions from CLOSED or RESOLVED directly to INVESTIGATING return HTTP 400."
    ),
)
def update_incident_status(
    incident_id: uuid.UUID,
    status_in: IncidentStatusUpdate,
    incident_service: IncidentService = Depends(get_incident_service),
    current_user: User = Depends(get_current_active_user),
) -> IncidentResponse:
    """
    Update incident lifecycle status within an atomic transaction for owner.
    """
    try:
        return incident_service.update_incident_status(incident_id, status_in.status, owner_id=current_user.id)
    except WorkspaceAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )


@router.put(
    "/{incident_id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an existing incident",
    description=(
        "Update supported fields (title, description, severity, status) of an existing incident. "
        "Status modifications strictly adhere to lifecycle workflow transition rules."
    ),
)
def update_incident(
    incident_id: uuid.UUID,
    incident_in: IncidentUpdate,
    incident_service: IncidentService = Depends(get_incident_service),
    current_user: User = Depends(get_current_active_user),
) -> IncidentResponse:
    """
    Update incident fields via IncidentService for owner.
    """
    try:
        return incident_service.update_incident(incident_id, incident_in, owner_id=current_user.id)
    except WorkspaceAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )


@router.patch(
    "/{incident_id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Partial update of an existing incident",
    description=(
        "Partial update of supported fields of an existing incident. "
        "Status modifications strictly adhere to lifecycle workflow transition rules."
    ),
)
def patch_incident(
    incident_id: uuid.UUID,
    incident_in: IncidentUpdate,
    incident_service: IncidentService = Depends(get_incident_service),
    current_user: User = Depends(get_current_active_user),
) -> IncidentResponse:
    """
    Partially update incident fields via IncidentService for owner.
    """
    try:
        return incident_service.update_incident(incident_id, incident_in, owner_id=current_user.id)
    except WorkspaceAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )


@router.delete(
    "/{incident_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an incident",
    description=(
        "Delete an existing incident owned by current user. Associated events remain in the database "
        "with their incident_id set to NULL."
    ),
)
def delete_incident(
    incident_id: uuid.UUID,
    incident_service: IncidentService = Depends(get_incident_service),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete an incident via IncidentService for owner or workspace admin. Returns HTTP 204 No Content.
    """
    try:
        incident_service.delete_incident(incident_id, owner_id=current_user.id)
        return None
    except WorkspaceAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )


@router.get(
    "",
    response_model=IncidentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List, search, filter, sort, and paginate incidents",
    description=(
        "Retrieve a paginated list of correlated error incidents belonging to current authenticated user. "
        "Supports search by title, filtering by service_name, environment, severity, and status. "
        "Supports sorting by created_at, last_seen_at, severity, id, or title with asc/desc direction. "
        "Deterministic ordering guaranteed via stable tie-breaker."
    ),
)
def list_incidents(
    search: Annotated[
        str | None,
        Query(max_length=100, description="Search term matching incident title (case-insensitive substring)."),
    ] = None,
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
        Query(
            pattern="(?i)^(low|medium|high|critical|error|warning|info)$",
            description="Filter by severity level (case-insensitive: low, medium, high, critical, error).",
        ),
    ] = None,
    status_filter: Annotated[
        IncidentStatus | None,
        Query(alias="status", description="Filter by status (OPEN, ACKNOWLEDGED, RESOLVED)."),
    ] = None,
    sort_by: Annotated[
        str,
        Query(
            pattern="^(created_at|last_seen_at|first_seen_at|severity|id|title|service_name|event_count)$",
            description="Field to sort by: created_at, last_seen_at, severity, id, title, service_name.",
        ),
    ] = "created_at",
    order: Annotated[
        str,
        Query(
            pattern="(?i)^(asc|desc)$",
            description="Sort direction: asc or desc.",
        ),
    ] = "desc",
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Maximum number of incidents per page (1–100)."),
    ] = 20,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based index of the first incident to return."),
    ] = 0,
    skip: Annotated[
        int | None,
        Query(ge=0, description="Alternative alias for offset (0-based start index)."),
    ] = None,
    workspace_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter incidents belonging to a specific workspace UUID."),
    ] = None,
    incident_service: IncidentService = Depends(get_incident_service),
    current_user: User = Depends(get_current_active_user),
) -> IncidentListResponse:
    """
    List incidents owned by current user or team workspaces with optional search, filtering, sorting, and pagination.
    Supports both `offset` and `skip` query parameters.
    """
    effective_offset = skip if skip is not None else offset
    try:
        items, total = incident_service.list_incidents(
            search=search,
            service_name=service_name,
            environment=environment,
            severity=severity,
            status_filter=status_filter,
            sort_by=sort_by,
            order=order,
            limit=limit,
            offset=effective_offset,
            owner_id=current_user.id,
            workspace_id=workspace_id,
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    return IncidentListResponse(
        items=list(items),
        limit=limit,
        offset=effective_offset,
        total=total,
    )


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve incident details",
    description=(
        "Retrieve the full details of an incident by its UUID primary key scoped to the owner. "
        "Returns HTTP 404 if the incident does not exist or belongs to another user."
    ),
)
def get_incident(
    incident_id: uuid.UUID,
    incident_service: IncidentService = Depends(get_incident_service),
    current_user: User = Depends(get_current_active_user),
) -> IncidentResponse:
    """
    Fetch an incident by UUID via IncidentService for owner.
    """
    incident = incident_service.get_incident_by_id(incident_id, owner_id=current_user.id)
    if incident is None:
        raise IncidentNotFoundError(incident_id)
    return incident


@router.get(
    "/{incident_id}/events",
    response_model=IncidentEventListResponse,
    status_code=status.HTTP_200_OK,
    summary="List events belonging to an incident",
    description=(
        "Retrieve a paginated list of individual error events correlated to this incident. "
        "Returns HTTP 404 if the parent incident does not exist or belongs to another user. "
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
    incident_service: IncidentService = Depends(get_incident_service),
    current_user: User = Depends(get_current_active_user),
) -> IncidentEventListResponse:
    """
    List events correlated to an incident via IncidentService for owner.
    """
    result = incident_service.list_incident_events(
        incident_id=incident_id,
        limit=limit,
        offset=offset,
        owner_id=current_user.id,
    )
    if result is None:
        raise IncidentNotFoundError(incident_id)

    events, total = result
    return IncidentEventListResponse(
        items=list(events),
        limit=limit,
        offset=offset,
        total=total,
    )
