"""create webhook_events and notification_logs tables

Revision ID: 0008_integrations_notifications
Revises: 0007_workspaces_rbac
Create Date: 2026-10-22 19:30:00

Milestone 19: External Alert Integrations & Notifications.
- Creates webhook_events table with unique constraint on (provider, provider_event_id)
  to ensure inbound idempotency and prevent duplicate event processing.
- Creates notification_logs table with unique constraint on idempotency_key
  to ensure outbound at-most-once notification delivery.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008_integrations_notifications"
down_revision: str | None = "0007_workspaces_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create webhook_events and notification_logs tables."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)

    # 1. Create webhook_events table
    op.create_table(
        "webhook_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False),
        sa.Column("event_id", uuid_type, nullable=True),
        sa.Column("incident_id", uuid_type, nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="PROCESSED"),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("payload_summary", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_webhook_provider_event"),
    )
    op.create_index("ix_webhook_events_provider", "webhook_events", ["provider"], unique=False)
    op.create_index("ix_webhook_events_provider_event_id", "webhook_events", ["provider_event_id"], unique=False)
    op.create_index("ix_webhook_events_event_id", "webhook_events", ["event_id"], unique=False)
    op.create_index("ix_webhook_events_incident_id", "webhook_events", ["incident_id"], unique=False)

    if is_postgres:
        op.create_foreign_key(
            "fk_webhook_events_event_id",
            "webhook_events",
            "events",
            ["event_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            "fk_webhook_events_incident_id",
            "webhook_events",
            "incidents",
            ["incident_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # 2. Create notification_logs table
    op.create_table(
        "notification_logs",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("incident_id", uuid_type, nullable=True),
        sa.Column("channel", sa.String(50), nullable=False, server_default="slack"),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_notification_idempotency_key"),
    )
    op.create_index("ix_notification_logs_incident_id", "notification_logs", ["incident_id"], unique=False)
    op.create_index("ix_notification_logs_idempotency_key", "notification_logs", ["idempotency_key"], unique=True)
    op.create_index("ix_notification_logs_status", "notification_logs", ["status"], unique=False)

    if is_postgres:
        op.create_foreign_key(
            "fk_notification_logs_incident_id",
            "notification_logs",
            "incidents",
            ["incident_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    """Drop notification_logs and webhook_events tables."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # Drop notification_logs
    if is_postgres:
        op.drop_constraint("fk_notification_logs_incident_id", "notification_logs", type_="foreignkey")
    op.drop_index("ix_notification_logs_status", table_name="notification_logs")
    op.drop_index("ix_notification_logs_idempotency_key", table_name="notification_logs")
    op.drop_index("ix_notification_logs_incident_id", table_name="notification_logs")
    op.drop_table("notification_logs")

    # Drop webhook_events
    if is_postgres:
        op.drop_constraint("fk_webhook_events_incident_id", "webhook_events", type_="foreignkey")
        op.drop_constraint("fk_webhook_events_event_id", "webhook_events", type_="foreignkey")
    op.drop_index("ix_webhook_events_incident_id", table_name="webhook_events")
    op.drop_index("ix_webhook_events_event_id", table_name="webhook_events")
    op.drop_index("ix_webhook_events_provider_event_id", table_name="webhook_events")
    op.drop_index("ix_webhook_events_provider", table_name="webhook_events")
    op.drop_table("webhook_events")
