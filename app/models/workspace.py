"""
app/models/workspace.py — SQLAlchemy ORM models for Team Workspaces and RBAC Memberships.

Milestone 17: Team Workspaces & Role-Based Access Control.
"""

from datetime import datetime, timezone
from enum import Enum
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WorkspaceRole(str, Enum):
    """
    Standardized RBAC roles for workspace collaboration.
    - ADMIN: Full management over workspace settings, membership, and resources.
    - RESPONDER: Operational permissions (create/update incidents, run investigations).
    - VIEWER: Read-only access to authorized workspace resources.
    """
    ADMIN = "admin"
    RESPONDER = "responder"
    VIEWER = "viewer"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            val_clean = value.strip().lower()
            for member in cls:
                if member.value == val_clean:
                    return member
        return None


class Workspace(Base):
    """
    ORM model representing a team workspace.
    
    Workspaces act as multi-tenant isolation boundaries containing incidents,
    investigations, and team members.
    """
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
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

    # Relationships
    memberships = relationship(
        "WorkspaceMembership",
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="select",
    )

    incidents = relationship(
        "Incident",
        back_populates="workspace",
        lazy="select",
    )

    creator = relationship(
        "User",
        foreign_keys=[created_by],
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Workspace id={self.id!s} name={self.name!r} created_by={self.created_by}>"


class WorkspaceMembership(Base):
    """
    ORM model representing a user's membership and role within a workspace.
    """
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership_user"),
        CheckConstraint(
            "role IN ('admin', 'responder', 'viewer')",
            name="ck_workspace_membership_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=WorkspaceRole.VIEWER.value,
        index=True,
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

    # Relationships
    workspace = relationship("Workspace", back_populates="memberships", lazy="select")
    user = relationship("User", back_populates="workspace_memberships", lazy="select")

    def __repr__(self) -> str:
        return f"<WorkspaceMembership ws={self.workspace_id!s} user={self.user_id!s} role={self.role!r}>"
