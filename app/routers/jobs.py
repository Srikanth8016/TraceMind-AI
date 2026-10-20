"""
app/routers/jobs.py — Router for querying asynchronous processing jobs.

Milestone 6: Background processing status tracking.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.job import ProcessingJob
from app.schemas.job import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    status_code=200,
    summary="Retrieve processing job status",
    description=(
        "Look up a background processing job by its UUID primary key. "
        "Returns the current lifecycle status (PENDING, PROCESSING, COMPLETED, FAILED), "
        "attempt count, and any sanitized error message. Returns HTTP 404 if not found."
    ),
)
def get_job_status(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> JobResponse:
    """
    Return the current status and metadata of a processing job.
    """
    job = db.get(ProcessingJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with id={job_id!s} not found.",
        )
    return job
