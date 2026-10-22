"""
app/schemas/workspace.py — Pydantic validation schemas for Workspaces and RBAC Memberships.

Milestone 17: Team Workspaces & Role-Based Access Control.
"""

from datetime import datetime
import re
from typing import Annotated
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.workspace import WorkspaceRole

EMAIL_REGEX = re.compile(r"^[\w\.\+\-]+@[\w\-]+\.[a-zA-Z]{2,}$")


class WorkspaceCreate(BaseModel):
    """Payload to create a new team workspace."""
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=100,
            description="Human-readable name of the workspace (1–100 chars).",
            examples=["Infrastructure SRE Team", "Payments Platform"],
        ),
    ]

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Workspace name cannot be whitespace only.")
        return cleaned


class WorkspaceUpdate(BaseModel):
    """Payload to update workspace attributes."""
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=100,
            description="Updated human-readable name of the workspace.",
        ),
    ]

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Workspace name cannot be whitespace only.")
        return cleaned


class WorkspaceResponse(BaseModel):
    """Public representation of a workspace."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    member_count: int | None = None
    current_user_role: str | None = None


class WorkspaceListResponse(BaseModel):
    """List of workspaces the authenticated user belongs to."""
    model_config = ConfigDict(from_attributes=True)

    items: list[WorkspaceResponse]
    total: int


class WorkspaceMemberAdd(BaseModel):
    """Payload to add a user to a workspace."""
    email: str | None = Field(
        default=None,
        description="Email of user to add (must be registered account).",
    )
    user_id: uuid.UUID | None = Field(
        default=None,
        description="UUID of user to add (optional alternative to email).",
    )
    role: WorkspaceRole = Field(
        default=WorkspaceRole.VIEWER,
        description="Role assigned to user ('admin', 'responder', 'viewer').",
    )

    @field_validator("email", mode="before")
    @classmethod
    def validate_and_normalize_email(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("Email must be a string.")
        cleaned = v.strip().lower()
        if not cleaned:
            return None
        if not EMAIL_REGEX.match(cleaned):
            raise ValueError("Invalid email format.")
        return cleaned


class WorkspaceMemberUpdate(BaseModel):
    """Payload to update an existing member's role."""
    role: WorkspaceRole = Field(
        description="New role to assign ('admin', 'responder', 'viewer').",
    )


class WorkspaceMemberResponse(BaseModel):
    """Public representation of a workspace member."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    email: str | None = None
    role: str
    created_at: datetime
    updated_at: datetime


class WorkspaceMemberListResponse(BaseModel):
    """List of workspace members."""
    model_config = ConfigDict(from_attributes=True)

    items: list[WorkspaceMemberResponse]
    total: int
