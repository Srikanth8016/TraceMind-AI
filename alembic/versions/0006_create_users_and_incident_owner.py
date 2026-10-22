"""create users table and incident owner_id foreign key

Revision ID: 0006_create_users_and_owner
Revises: 0005_create_knowledge_and_chunks
Create Date: 2026-10-22 10:40:00

Milestone 14: Authentication & Authorization.
- Creates users table with unique normalized email, hashed_password, is_active, and timestamps.
- Adds nullable owner_id foreign key column to incidents table with index for ownership lookups.
- Preserves existing legacy incidents safely without data loss.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006_create_users_and_owner"
down_revision: str | None = "0005_create_knowledge_and_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create users table and add owner_id to incidents table."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)

    # 1. Create users table
    op.create_table(
        "users",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # 2. Add owner_id to incidents table (nullable for backward compatibility)
    op.add_column("incidents", sa.Column("owner_id", uuid_type, nullable=True))
    op.create_index("ix_incidents_owner_id", "incidents", ["owner_id"], unique=False)

    if is_postgres:
        op.create_foreign_key(
            "fk_incidents_owner_id_users",
            "incidents",
            "users",
            ["owner_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Drop owner_id from incidents and drop users table."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.drop_constraint("fk_incidents_owner_id_users", "incidents", type_="foreignkey")

    op.drop_index("ix_incidents_owner_id", table_name="incidents")
    op.drop_column("incidents", "owner_id")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
