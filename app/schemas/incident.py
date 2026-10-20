"""
app/schemas/incident.py — Pydantic schemas for incident management.

Milestone 7: Deterministic incident grouping and event correlation.
"""

from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.incident import IncidentStatus
from app.schemas.event import EventResponse


class IncidentResponse(BaseModel):
    """
    Representation of an Incident record.

    Includes identity, grouping fingerprint, lifecycle status, event counts,
    and occurrence timestamps.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Server-generated UUID primary key of the incident.")
    service_name: str = Field(..., description="Source microservice where the incident originated.")
    environment: str = Field(..., description="Deployment environment (e.g. production, staging).")
    fingerprint: str = Field(..., description="Deterministic 64-character SHA-256 grouping fingerprint.")
    title: str = Field(..., description="Normalized title or summary of the error incident.")
    severity: str = Field(..., description="Severity level: ERROR or CRITICAL.")
    status: IncidentStatus = Field(..., description="Lifecycle status: OPEN, ACKNOWLEDGED, RESOLVED.")
    first_seen_at: datetime = Field(..., description="Timestamp of the earliest correlated event.")
    last_seen_at: datetime = Field(..., description="Timestamp of the most recent correlated event.")
    event_count: int = Field(..., description="Total number of events grouped into this incident.")
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
