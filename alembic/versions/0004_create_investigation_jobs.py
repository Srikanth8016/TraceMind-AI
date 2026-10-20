"""create investigation_jobs table

Revision ID: 0004_create_investigation_jobs
Revises: 0003_create_incidents
Create Date: 2026-10-20 19:20:00

Milestone 8: Asynchronous AI-assisted incident investigation engine.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_create_investigation_jobs"
down_revision: str | None = "0003_create_incidents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the investigation_jobs table with indexes and foreign keys."""
    op.create_table(
        "investigation_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "incident_id",
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
            "report",
            sa.JSON(),
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
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_investigation_jobs_incident_id",
        "investigation_jobs",
        ["incident_id"],
    )
    op.create_index(
        "ix_investigation_jobs_status",
        "investigation_jobs",
        ["status"],
    )


def downgrade() -> None:
    """Drop the investigation_jobs table and its indexes."""
    op.drop_index("ix_investigation_jobs_status", table_name="investigation_jobs")
    op.drop_index("ix_investigation_jobs_incident_id", table_name="investigation_jobs")
    op.drop_table("investigation_jobs")
