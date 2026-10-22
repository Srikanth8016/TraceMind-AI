"""
app/schemas/incident.py — Pydantic schemas for incident management.

Milestone 7: Deterministic incident grouping and event correlation.
"""

from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.incident import IncidentStatus
from app.schemas.event import EventResponse


class IncidentCreate(BaseModel):
    """
    Schema for creating a new Incident via POST /api/v1/incidents.
    """
    title: str = Field(..., min_length=1, max_length=255, description="Normalized title or summary of the error incident.")
    description: str | None = Field(default=None, max_length=2000, description="Optional detailed description.")
    service_name: str = Field(default="default-service", min_length=1, max_length=100, description="Source microservice name.")
    environment: str = Field(default="production", min_length=1, max_length=50, description="Deployment environment.")
    severity: str = Field(default="ERROR", pattern="(?i)^(ERROR|CRITICAL|HIGH|MEDIUM|LOW|WARNING|INFO)$", description="Severity level: ERROR, CRITICAL, HIGH, etc.")
    status: IncidentStatus = Field(default=IncidentStatus.OPEN, description="Initial lifecycle status: OPEN, INVESTIGATING, RESOLVED, CLOSED.")


class IncidentStatusUpdate(BaseModel):
    """
    Schema for updating the lifecycle status of an existing Incident.
    """
    status: IncidentStatus = Field(..., description="Target lifecycle status: OPEN, INVESTIGATING, RESOLVED, or CLOSED.")


class IncidentUpdate(BaseModel):
    """
    Schema for updating an existing incident via PUT / PATCH.
    """
    title: str | None = Field(default=None, min_length=1, max_length=255, description="Updated incident title.")
    description: str | None = Field(default=None, max_length=2000, description="Updated incident description.")
    severity: str | None = Field(default=None, pattern="(?i)^(ERROR|CRITICAL|HIGH|MEDIUM|LOW|WARNING|INFO)$", description="Updated severity.")
    status: IncidentStatus | None = Field(default=None, description="Updated lifecycle status: OPEN, INVESTIGATING, RESOLVED, CLOSED.")


class IncidentResponse(BaseModel):
    """
    Representation of an Incident record.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Server-generated UUID primary key of the incident.")
    service_name: str = Field(..., description="Source microservice where the incident originated.")
    environment: str = Field(..., description="Deployment environment (e.g. production, staging).")
    fingerprint: str = Field(..., description="Deterministic 64-character SHA-256 grouping fingerprint.")
    title: str = Field(..., description="Normalized title or summary of the error incident.")
    severity: str = Field(..., description="Severity level: ERROR or CRITICAL.")
    status: IncidentStatus = Field(..., description="Lifecycle status: OPEN, INVESTIGATING, RESOLVED, CLOSED.")
    first_seen_at: datetime = Field(..., description="Timestamp of the earliest correlated event.")
    last_seen_at: datetime = Field(..., description="Timestamp of the most recent correlated event.")
    event_count: int = Field(..., description="Total number of events grouped into this incident.")
    owner_id: uuid.UUID | None = Field(default=None, description="UUID of the incident owner/creator.")
    created_at: datetime = Field(..., description="Timestamp when the incident was first created.")
    updated_at: datetime = Field(..., description="Timestamp when the incident was last modified.")


class IncidentListResponse(BaseModel):
    """
    Paginated list response for GET /api/v1/incidents.
    """
    items: list[IncidentResponse] = Field(..., description="List of incidents on current page.")
    limit: int = Field(..., description="Maximum rows returned per page.")
    offset: int = Field(..., description="Starting row offset.")
    total: int = Field(..., description="Total matching incidents matching filters before pagination.")


class IncidentEventListResponse(BaseModel):
    """
    Paginated list response for GET /api/v1/incidents/{incident_id}/events.
    """
    items: list[EventResponse] = Field(..., description="List of events linked to this incident.")
    limit: int = Field(..., description="Maximum rows returned per page.")
    offset: int = Field(..., description="Starting row offset.")
    total: int = Field(..., description="Total events linked to this incident.")
