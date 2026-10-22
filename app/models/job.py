"""
app/models/job.py — SQLAlchemy ORM model for asynchronous processing jobs.

Milestone 6: Background event processing with Celery and Redis.

Design Decisions
----------------
- ``id``: UUID primary key.
- ``event_id``: Foreign key referencing ``events.id``.
- ``status``: Lifecycle state (PENDING, PROCESSING, COMPLETED, FAILED).
- ``attempt_count``: Integer tracking task retry attempts.
- ``error_message``: Sanitized, human-readable error description if failed.
- ``created_at`` / ``updated_at``: Timestamps tracking the job lifecycle.
"""

from datetime import datetime, timezone
from enum import Enum
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobStatus(str, Enum):
    """Lifecycle states of a background event processing job."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProcessingJob(Base):
    """
    ORM model tracking the state of an asynchronous processing job.

    PostgreSQL is the source of truth for all job states.
    """
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=JobStatus.PENDING.value,
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

    # Relationship to the originating event
    event = relationship("Event", backref="processing_jobs")

    def __repr__(self) -> str:
        return (
            f"<ProcessingJob id={self.id!s} event_id={self.event_id!s} "
            f"status={self.status!r} attempts={self.attempt_count}>"
        )
