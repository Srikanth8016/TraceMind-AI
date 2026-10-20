"""
app/schemas/job.py — Pydantic schemas for processing jobs.

Milestone 6: Background event processing schemas.
"""

from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.job import JobStatus
from app.schemas.event import EventResponse


class JobResponse(BaseModel):
    """
    Representation of a processing job record.

    Includes state, attempts, sanitized errors, and timestamps.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Server-generated UUID primary key of the job.")
    event_id: uuid.UUID = Field(..., description="UUID of the associated event.")
    status: JobStatus = Field(..., description="Lifecycle status: PENDING, PROCESSING, COMPLETED, FAILED.")
    attempt_count: int = Field(..., description="Number of execution attempts.")
    error_message: str | None = Field(default=None, description="Sanitized failure description if any.")
    created_at: datetime = Field(..., description="Timestamp when the job was created.")
    updated_at: datetime = Field(..., description="Timestamp when the job status was last updated.")


class EventIngestResponse(BaseModel):
    """
    HTTP 202 Accepted response returned by POST /api/v1/events.

    Includes the persisted event attributes, event ID, job ID, and initial job status.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="UUID primary key of the persisted event.")
    event_id: uuid.UUID = Field(..., description="Alias identifier for the event.")
    service_name: str
    environment: str
    level: str
    message: str
    timestamp: datetime
    created_at: datetime

    job_id: uuid.UUID = Field(..., description="UUID primary key of the processing job.")
    status: JobStatus = Field(default=JobStatus.PENDING, description="Initial job status.")
    job_status: JobStatus = Field(default=JobStatus.PENDING, description="Initial job status.")


class EventAcceptedWithJob(BaseModel):
    """
    Detailed HTTP 202 Accepted response body nesting event and job objects.
    """
    message: str = Field(
        default="Event accepted and queued for processing.",
        description="Human-readable confirmation message.",
    )
    event: EventResponse = Field(..., description="The persisted event.")
    job: JobResponse = Field(..., description="The queued background processing job.")

