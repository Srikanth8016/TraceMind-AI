"""
app/routers/investigations.py — Router for AI-assisted incident investigations.

Milestone 8: Asynchronous AI-assisted incident investigation engine.
"""

from typing import Annotated
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_optional_current_user
from app.database import get_db
from app.models.incident import Incident
from app.models.investigation import InvestigationJob, InvestigationStatus
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.schemas.investigation import (
    InvestigationCreateResponse,
    InvestigationJobResponse,
)
from app.services.rbac import can_run_investigation
from app.services.task_dispatcher import dispatch_incident_investigation
from app.tasks import investigate_incident_task
from app.utils import sanitize_error

router = APIRouter(tags=["investigations"])


def _check_incident_access_for_user(
    db: Session,
    incident: Incident,
    user: User | None,
    require_write: bool = False,
) -> None:
    if user is None:
        return
    if incident.workspace_id is not None:
        mem = db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == incident.workspace_id,
                WorkspaceMembership.user_id == user.id,
            )
        ).scalars().first()
        if mem is None and incident.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Incident with id={incident.id!s} not found.",
            )
        if require_write and mem is not None:
            if not can_run_investigation(mem.role):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Workspace viewers have read-only access and cannot trigger incident investigations.",
                )
    else:
        if incident.owner_id is not None and incident.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Incident with id={incident.id!s} not found.",
            )


@router.post(
    "/incidents/{incident_id}/investigate",
    response_model=InvestigationCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue AI investigation for an incident",
    description=(
        "Initiate an asynchronous AI-assisted investigation for an incident. "
        "Persists an InvestigationJob record and enqueues background analysis via Celery or BackgroundTasks in demo mode. "
        "Returns HTTP 202 with the investigation job ID."
    ),
)
@router.post(
    "/incidents/{incident_id}/investigations",
    response_model=InvestigationCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue AI investigation for an incident (REST collection alias)",
    include_in_schema=False,
)
def request_incident_investigation(
    incident_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> InvestigationCreateResponse:
    """
    Enqueue an asynchronous investigation job for an incident with workspace authorization.
    """
    # 1. Verify incident exists
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with id={incident_id!s} not found.",
        )

    # 2. Authorize user
    _check_incident_access_for_user(db, incident, current_user, require_write=True)

    # 3. Persist InvestigationJob in PostgreSQL (source of truth)
    job = InvestigationJob(
        id=uuid.uuid4(),
        incident_id=incident.id,
        status=InvestigationStatus.PENDING.value,
        attempt_count=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # 4. Enqueue task via Celery (production) or BackgroundTasks (demo mode)
    try:
        dispatch_incident_investigation(str(job.id), str(incident.id), background_tasks)
    except Exception as exc:
        job.status = InvestigationStatus.FAILED.value
        job.error_message = f"Failed to enqueue task to broker: {sanitize_error(str(exc))}"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue background investigation task. Broker is unavailable.",
        ) from exc

    return InvestigationCreateResponse(
        id=job.id,
        incident_id=incident.id,
        status=InvestigationStatus.PENDING,
    )


@router.get(
    "/investigations/{job_id}",
    response_model=InvestigationJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve investigation report and status",
    description=(
        "Retrieve the status and structured report of an investigation job by its UUID. "
        "Returns HTTP 404 if the job ID is unknown."
    ),
)
def get_investigation_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> InvestigationJobResponse:
    """
    Fetch an investigation job by its UUID with workspace isolation check.
    """
    job = db.get(InvestigationJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation job with id={job_id!s} not found.",
        )

    incident = db.get(Incident, job.incident_id)
    if incident is not None:
        _check_incident_access_for_user(db, incident, current_user, require_write=False)

    return job


@router.get(
    "/incidents/{incident_id}/investigations",
    response_model=list[InvestigationJobResponse],
    status_code=status.HTTP_200_OK,
    summary="List investigations for an incident",
    description="Retrieve all investigation jobs associated with a specific incident, ordered by creation time.",
)
def list_incident_investigations(
    incident_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> list[InvestigationJobResponse]:
    """
    List all investigation jobs for a given incident with workspace isolation check.
    """
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with id={incident_id!s} not found.",
        )

    _check_incident_access_for_user(db, incident, current_user, require_write=False)

    stmt = (
        select(InvestigationJob)
        .where(InvestigationJob.incident_id == incident_id)
        .order_by(InvestigationJob.created_at.desc())
    )
    jobs = db.execute(stmt).scalars().all()
    return list(jobs)
