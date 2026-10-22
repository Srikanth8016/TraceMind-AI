"""
app/models/user.py — SQLAlchemy ORM model for user accounts and authentication.

Milestone 14: Authentication & Authorization.
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    """
    ORM model representing an authenticated user account.

    Attributes
    ----------
    id : uuid.UUID
        Primary key UUID of the user.
    email : str
        Unique, normalized lowercase email address of the user.
    hashed_password : str
        Cryptographically hashed user password.
    is_active : bool
        Lifecycle flag indicating whether the account is currently enabled.
    created_at : datetime
        Timestamp when the user account was registered.
    updated_at : datetime
        Timestamp when the user account was last modified.
    incidents : list[Incident]
        Incidents owned/created by this user.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
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

    # 1-to-many relationship: a user owns multiple incidents
    incidents = relationship("Incident", back_populates="owner", lazy="select")

    # 1-to-many relationship: a user has memberships in multiple workspaces
    workspace_memberships = relationship(
        "WorkspaceMembership",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!s} email={self.email!r} is_active={self.is_active}>"
