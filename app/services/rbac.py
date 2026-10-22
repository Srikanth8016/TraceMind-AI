"""
app/services/rbac.py — Centralized Role-Based Access Control and Authorization Service.

Milestone 17: Team Workspaces & Role-Based Access Control.

Role Hierarchy & Permissions Matrix
-----------------------------------
Role       | View Incidents | Modify Status | Run AI Investigate | Manage Members & Settings
-----------+----------------+---------------+--------------------+--------------------------
admin      | Yes            | Yes           | Yes                | Yes
responder  | Yes            | Yes           | Yes                | No (HTTP 403)
viewer     | Yes            | No (HTTP 403) | No (HTTP 403)      | No (HTTP 403)

Invariants Enforced:
1. Cannot remove or demote the last remaining admin in a workspace.
2. Viewers cannot escalate to responder or admin; responders cannot escalate to admin.
3. Only admins can invite/remove members or change roles.
4. Workspace isolation: users cannot view or manipulate resources of workspaces they do not belong to.
"""

from typing import Annotated, Callable, Set
import uuid

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_active_user
from app.database import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class RBACError(Exception):
    """Base exception for RBAC and workspace authorization violations."""
    pass


class WorkspaceNotFoundError(RBACError):
    """Raised when a workspace does not exist or user has no access."""
    def __init__(self, workspace_id: uuid.UUID) -> None:
        super().__init__(f"Workspace '{workspace_id}' not found.")


class WorkspaceAccessDeniedError(RBACError):
    """Raised when a user lacks sufficient permissions for an action."""
    def __init__(self, message: str = "Insufficient workspace permissions for this operation.") -> None:
        super().__init__(message)


class WorkspaceRoleEscalationError(RBACError):
    """Raised when an unauthorized role assignment or privilege escalation is attempted."""
    def __init__(self, message: str = "Privilege escalation rejected.") -> None:
        super().__init__(message)


class LastAdminError(RBACError):
    """Raised when an operation would leave a workspace with zero administrators."""
    def __init__(self, message: str = "Cannot remove or demote the last workspace administrator.") -> None:
        super().__init__(message)


class DuplicateMemberError(RBACError):
    """Raised when attempting to add a user who is already a member."""
    def __init__(self, message: str = "User is already a member of this workspace.") -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# Permission Checker Helpers
# ---------------------------------------------------------------------------

def can_manage_workspace(role: str | WorkspaceRole) -> bool:
    """Returns True if the role can manage workspace settings and members."""
    val = role.value if isinstance(role, WorkspaceRole) else str(role).lower()
    return val == WorkspaceRole.ADMIN.value


def can_write_incidents(role: str | WorkspaceRole) -> bool:
    """Returns True if the role can create, update, or resolve incidents."""
    val = role.value if isinstance(role, WorkspaceRole) else str(role).lower()
    return val in (WorkspaceRole.ADMIN.value, WorkspaceRole.RESPONDER.value)


def can_run_investigation(role: str | WorkspaceRole) -> bool:
    """Returns True if the role can trigger AI investigations."""
    val = role.value if isinstance(role, WorkspaceRole) else str(role).lower()
    return val in (WorkspaceRole.ADMIN.value, WorkspaceRole.RESPONDER.value)


# ---------------------------------------------------------------------------
# FastAPI Dependency Injection Helpers
# ---------------------------------------------------------------------------

def get_workspace_membership(
    workspace_id: Annotated[uuid.UUID, Path(description="UUID of the target workspace.")],
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> WorkspaceMembership:
    """
    FastAPI dependency that validates workspace existence and user membership.
    
    Security: Returns HTTP 404 rather than 403 if user is not a member to prevent
    information leakage regarding the existence of private workspaces.
    """
    # 1. Verify workspace exists
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_id}' not found.",
        )

    # 2. Check user's membership
    stmt = (
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == current_user.id,
        )
    )
    membership = db.execute(stmt).scalars().first()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_id}' not found.",
        )

    return membership


def require_role(allowed_roles: Set[str | WorkspaceRole]) -> Callable[..., WorkspaceMembership]:
    """
    Factory dependency requiring the user's workspace membership role to be within allowed_roles.
    """
    normalized_allowed = {
        r.value if isinstance(r, WorkspaceRole) else str(r).lower()
        for r in allowed_roles
    }

    def role_checker(
        membership: WorkspaceMembership = Depends(get_workspace_membership),
    ) -> WorkspaceMembership:
        user_role = membership.role.lower()
        if user_role not in normalized_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Action requires one of roles: {sorted(list(normalized_allowed))}. "
                    f"Your current role in this workspace is '{user_role}'."
                ),
            )
        return membership

    return role_checker


# Convenient pre-configured role dependencies
require_workspace_admin = require_role({WorkspaceRole.ADMIN})
require_workspace_responder = require_role({WorkspaceRole.ADMIN, WorkspaceRole.RESPONDER})
require_workspace_member = require_role({WorkspaceRole.ADMIN, WorkspaceRole.RESPONDER, WorkspaceRole.VIEWER})
