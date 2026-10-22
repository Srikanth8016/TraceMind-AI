"""create workspaces and workspace_memberships tables, add workspace_id to incidents

Revision ID: 0007_workspaces_rbac
Revises: 0006_create_users_and_owner
Create Date: 2026-10-22 18:30:00

Milestone 17: Team Workspaces & Role-Based Access Control.
- Creates workspaces table with name, created_by foreign key, and timestamps.
- Creates workspace_memberships table with workspace_id, user_id, role, uniqueness constraint, and role check constraint.
- Adds nullable workspace_id foreign key column to incidents table with index for multi-tenant isolation.
- Preserves existing legacy and single-user incidents safely without data loss.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007_workspaces_rbac"
down_revision: str | None = "0006_create_users_and_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create workspaces, workspace_memberships, and alter incidents."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)

    # 1. Create workspaces table
    op.create_table(
        "workspaces",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_by", uuid_type, nullable=False),
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
    op.create_index("ix_workspaces_name", "workspaces", ["name"], unique=False)
    op.create_index("ix_workspaces_created_by", "workspaces", ["created_by"], unique=False)

    if is_postgres:
        op.create_foreign_key(
            "fk_workspaces_created_by_users",
            "workspaces",
            "users",
            ["created_by"],
            ["id"],
            ondelete="RESTRICT",
        )

    # 2. Create workspace_memberships table
    op.create_table(
        "workspace_memberships",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("workspace_id", uuid_type, nullable=False),
        sa.Column("user_id", uuid_type, nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
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
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership_user"),
        sa.CheckConstraint(
            "role IN ('admin', 'responder', 'viewer')",
            name="ck_workspace_membership_role",
        ),
    )
    op.create_index("ix_workspace_memberships_workspace_id", "workspace_memberships", ["workspace_id"], unique=False)
    op.create_index("ix_workspace_memberships_user_id", "workspace_memberships", ["user_id"], unique=False)
    op.create_index("ix_workspace_memberships_role", "workspace_memberships", ["role"], unique=False)

    if is_postgres:
        op.create_foreign_key(
            "fk_workspace_memberships_workspace_id",
            "workspace_memberships",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_workspace_memberships_user_id",
            "workspace_memberships",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # 3. Add workspace_id column to incidents table (nullable for legacy/personal incidents)
    op.add_column("incidents", sa.Column("workspace_id", uuid_type, nullable=True))
    op.create_index("ix_incidents_workspace_id", "incidents", ["workspace_id"], unique=False)

    if is_postgres:
        op.create_foreign_key(
            "fk_incidents_workspace_id_workspaces",
            "incidents",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Drop workspace_id from incidents, and drop workspace tables."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Revert incidents table
    if is_postgres:
        op.drop_constraint("fk_incidents_workspace_id_workspaces", "incidents", type_="foreignkey")
    op.drop_index("ix_incidents_workspace_id", table_name="incidents")
    op.drop_column("incidents", "workspace_id")

    # 2. Revert workspace_memberships table
    if is_postgres:
        op.drop_constraint("fk_workspace_memberships_user_id", "workspace_memberships", type_="foreignkey")
        op.drop_constraint("fk_workspace_memberships_workspace_id", "workspace_memberships", type_="foreignkey")
    op.drop_index("ix_workspace_memberships_role", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_user_id", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_workspace_id", table_name="workspace_memberships")
    op.drop_table("workspace_memberships")

    # 3. Revert workspaces table
    if is_postgres:
        op.drop_constraint("fk_workspaces_created_by_users", "workspaces", type_="foreignkey")
    op.drop_index("ix_workspaces_created_by", table_name="workspaces")
    op.drop_index("ix_workspaces_name", table_name="workspaces")
    op.drop_table("workspaces")
