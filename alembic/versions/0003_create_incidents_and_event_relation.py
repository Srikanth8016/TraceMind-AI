"""create incidents table and event relationship

Revision ID: 0003_create_incidents
Revises: 0002_create_processing_jobs
Create Date: 2026-10-20 17:50:00

Milestone 7: Deterministic incident grouping and event correlation.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_create_incidents"
down_revision: str | None = "0002_create_processing_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the incidents table and add incident_id foreign key to events."""
    # 1. Create incidents table
    op.create_table(
        "incidents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("service_name", sa.String(100), nullable=False),
        sa.Column("environment", sa.String(50), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(20), server_default="ERROR", nullable=False),
        sa.Column("status", sa.String(20), server_default="OPEN", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. Indexes for incidents
    op.create_index("ix_incidents_fingerprint", "incidents", ["fingerprint"])
    op.create_index("ix_incidents_service_name", "incidents", ["service_name"])
    op.create_index("ix_incidents_environment", "incidents", ["environment"])
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_severity", "incidents", ["severity"])
    op.create_index("ix_incidents_last_seen_at", "incidents", ["last_seen_at"])
    op.create_index(
        "ix_incidents_correlation_lookup",
        "incidents",
        ["service_name", "environment", "fingerprint", "status"],
    )

    # 3. Add incident_id foreign key column to events table
    op.add_column(
        "events",
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_events_incident_id_incidents",
        "events",
        "incidents",
        ["incident_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_events_incident_id", "events", ["incident_id"])


def downgrade() -> None:
    """Drop foreign key, column from events, and the incidents table."""
    op.drop_index("ix_events_incident_id", table_name="events")
    op.drop_constraint("fk_events_incident_id_incidents", "events", type_="foreignkey")
    op.drop_column("events", "incident_id")

    op.drop_index("ix_incidents_correlation_lookup", table_name="incidents")
    op.drop_index("ix_incidents_last_seen_at", table_name="incidents")
    op.drop_index("ix_incidents_severity", table_name="incidents")
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_index("ix_incidents_environment", table_name="incidents")
    op.drop_index("ix_incidents_service_name", table_name="incidents")
    op.drop_index("ix_incidents_fingerprint", table_name="incidents")
    op.drop_table("incidents")
