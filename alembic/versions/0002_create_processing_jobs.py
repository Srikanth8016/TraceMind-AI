"""create processing_jobs table

Revision ID: 0002_create_processing_jobs
Revises: 0001_create_events
Create Date: 2026-10-20 17:05:00

Milestone 6: Asynchronous processing jobs tracking table.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_create_processing_jobs"
down_revision: str | None = "0001_create_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the processing_jobs table with indexes and foreign keys."""
    op.create_table(
        "processing_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(20),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
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
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_processing_jobs_event_id",
        "processing_jobs",
        ["event_id"],
    )
    op.create_index(
        "ix_processing_jobs_status",
        "processing_jobs",
        ["status"],
    )


def downgrade() -> None:
    """Drop the processing_jobs table and its indexes."""
    op.drop_index("ix_processing_jobs_status", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_event_id", table_name="processing_jobs")
    op.drop_table("processing_jobs")
