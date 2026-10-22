"""
app/models/integration.py — SQLAlchemy ORM models for external alert integrations & notifications.

Milestone 19: External Alert Integrations & Notifications.

Models
------
1. WebhookEvent:
   Tracks inbound webhook delivery from external monitoring providers (Datadog, PagerDuty).
   Enforces idempotency via UniqueConstraint("provider", "provider_event_id") to prevent
   duplicate event creation on webhook retries.
2. NotificationLog:
   Audit and tracking record for outbound notifications (Slack).
   Enforces idempotency via unique idempotency_key to prevent duplicate Slack alerts
   when Celery tasks are retried.
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WebhookEvent(Base):
    """
    ORM model tracking an inbound webhook from an external provider (Datadog, PagerDuty).
    """

    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        # e.g., 'datadog', 'pagerduty'
    )

    provider_event_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="PROCESSED",  # 'PROCESSED', 'DUPLICATE', 'IGNORED'
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    payload_summary: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_webhook_provider_event"),
    )

    def __repr__(self) -> str:
        return f"<WebhookEvent id={self.id} provider={self.provider} provider_id={self.provider_event_id}>"


class NotificationLog(Base):
    """
    ORM model tracking an outbound notification delivery (e.g. Slack).
    Enforces at-most-once delivery via unique idempotency_key.
    """

    __tablename__ = "notification_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    channel: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="slack",
    )

    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        # e.g., 'incident.created', 'incident.severity_escalated', 'incident.status_changed',
        #       'investigation.completed', 'investigation.failed'
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",  # 'PENDING', 'SENT', 'FAILED', 'SKIPPED'
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<NotificationLog id={self.id} channel={self.channel} event_type={self.event_type} status={self.status}>"
