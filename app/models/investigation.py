"""
app/models/investigation.py — SQLAlchemy ORM model for AI-assisted incident investigations.

Milestone 8: Asynchronous AI-assisted incident investigation engine.

Design Decisions
----------------
1. **Job Tracking**:
   Each investigation is tracked as a distinct asynchronous job associated with an incident.
2. **PostgreSQL as Source of Truth**:
   The job state (PENDING, PROCESSING, COMPLETED, FAILED), attempt counter, sanitized
   error messages, and final structured investigation report are persisted in PostgreSQL.
3. **Report Storage**:
   The structured report is persisted using SQLAlchemy's dialect-agnostic JSON column,
   which maps to native JSONB in PostgreSQL and JSON/TEXT in SQLite (tests).
4. **Idempotency**:
   Repeating execution checks job status; completed jobs are not re-executed or duplicated.
"""

from datetime import datetime, timezone
from enum import Enum
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class InvestigationStatus(str, Enum):
    """Lifecycle states of an investigation job."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class InvestigationJob(Base):
    """
    ORM model tracking an AI investigation for a specific incident.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the investigation job.
    incident_id : uuid.UUID
        Foreign key referencing ``incidents.id``.
    status : str
        Lifecycle status: PENDING, PROCESSING, COMPLETED, FAILED.
    attempt_count : int
        Number of execution attempts.
    error_message : str | None
        Sanitized error description if the job failed.
    report : dict | None
        Structured investigation report (hypotheses, evidence citations, actions).
    created_at : datetime
        Timestamp when the investigation request was enqueued.
    updated_at : datetime
        Timestamp when the job status was last modified.
    completed_at : datetime | None
        Timestamp when the investigation completed successfully.
    """
    __tablename__ = "investigation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=InvestigationStatus.PENDING.value,
        index=True,
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    report: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationship to the parent Incident
    incident = relationship("Incident", back_populates="investigation_jobs")

    def __repr__(self) -> str:
        return (
            f"<InvestigationJob id={self.id!s} incident_id={self.incident_id!s} "
            f"status={self.status!r} attempts={self.attempt_count}>"
        )
