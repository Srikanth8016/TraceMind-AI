"""
app/services/workspace_service.py — Business logic and database operations for Workspaces and RBAC.

Milestone 17: Team Workspaces & Role-Based Access Control.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Sequence
import uuid

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.rbac import (
    DuplicateMemberError,
    LastAdminError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
    can_manage_workspace,
)

logger = logging.getLogger(__name__)


class WorkspaceService:
    """
    Encapsulates all workspace and membership operations with strict RBAC enforcement.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_workspace(self, name: str, creator: User) -> Workspace:
        """
        Create a new team workspace and atomically enroll the creator as ADMIN.
        """
        clean_name = name.strip()
        now = datetime.now(timezone.utc)

        workspace = Workspace(
            id=uuid.uuid4(),
            name=clean_name,
            created_by=creator.id,
            created_at=now,
            updated_at=now,
        )

        # Atomic creator membership assignment
        admin_membership = WorkspaceMembership(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            user_id=creator.id,
            role=WorkspaceRole.ADMIN.value,
            created_at=now,
            updated_at=now,
        )

        try:
            self.db.add(workspace)
            self.db.add(admin_membership)
            self.db.commit()
            self.db.refresh(workspace)
            logger.info("Created workspace %s (%r) with owner %s", workspace.id, workspace.name, creator.id)
            return workspace
        except Exception as exc:
            self.db.rollback()
            logger.error("Failed creating workspace %r: %s", clean_name, exc, exc_info=True)
            raise

    def list_user_workspaces(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        """
        List all workspaces where user_id has an active membership.
        Annotates each workspace with user's current role and total member count.
        """
        stmt = (
            select(
                Workspace,
                WorkspaceMembership.role.label("current_user_role"),
                func.count(WorkspaceMembership.id).over(partition_by=Workspace.id).label("member_count"),
            )
            .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
            .where(WorkspaceMembership.user_id == user_id)
            .order_by(Workspace.created_at.desc())
        )
        rows = self.db.execute(stmt).all()

        results = []
        for ws, role, count in rows:
            results.append({
                "id": ws.id,
                "name": ws.name,
                "created_by": ws.created_by,
                "created_at": ws.created_at,
                "updated_at": ws.updated_at,
                "current_user_role": role,
                "member_count": count,
            })
        return results

    def get_workspace_for_user(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
        """
        Retrieve workspace details ensuring user is an authorized member.
        """
        stmt = (
            select(Workspace, WorkspaceMembership.role)
            .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
            .where(
                Workspace.id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        )
        row = self.db.execute(stmt).first()
        if row is None:
            raise WorkspaceNotFoundError(workspace_id)

        ws, role = row
        member_count = self.db.scalar(
            select(func.count(WorkspaceMembership.id)).where(WorkspaceMembership.workspace_id == workspace_id)
        ) or 0

        return {
            "id": ws.id,
            "name": ws.name,
            "created_by": ws.created_by,
            "created_at": ws.created_at,
            "updated_at": ws.updated_at,
            "current_user_role": role,
            "member_count": member_count,
        }

    def update_workspace(self, workspace_id: uuid.UUID, requesting_user_id: uuid.UUID, name: str) -> Workspace:
        """
        Update workspace name (Requires ADMIN role).
        """
        membership = self._get_membership(workspace_id, requesting_user_id)
        if not can_manage_workspace(membership.role):
            raise WorkspaceAccessDeniedError("Only workspace administrators can update workspace settings.")

        ws = self.db.get(Workspace, workspace_id)
        if ws is None:
            raise WorkspaceNotFoundError(workspace_id)

        ws.name = name.strip()
        ws.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(ws)
        return ws

    def list_members(self, workspace_id: uuid.UUID, requesting_user_id: uuid.UUID) -> list[dict[str, Any]]:
        """
        List all members of a workspace (Requires valid membership).
        """
        self._get_membership(workspace_id, requesting_user_id)  # Auth check

        stmt = (
            select(WorkspaceMembership, User.email)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .order_by(WorkspaceMembership.created_at.asc())
        )
        rows = self.db.execute(stmt).all()

        return [
            {
                "id": m.id,
                "workspace_id": m.workspace_id,
                "user_id": m.user_id,
                "email": email,
                "role": m.role,
                "created_at": m.created_at,
                "updated_at": m.updated_at,
            }
            for m, email in rows
        ]

    def add_member(
        self,
        workspace_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        target_email: str | None = None,
        target_user_id: uuid.UUID | None = None,
        role: WorkspaceRole = WorkspaceRole.VIEWER,
    ) -> dict[str, Any]:
        """
        Add a registered user to the workspace with specified role (Requires ADMIN role).
        """
        membership = self._get_membership(workspace_id, requesting_user_id)
        if not can_manage_workspace(membership.role):
            raise WorkspaceAccessDeniedError("Only workspace administrators can add members.")

        # Find target user
        if target_user_id is not None:
            target_user = self.db.get(User, target_user_id)
        elif target_email:
            target_user = self.db.execute(
                select(User).where(func.lower(User.email) == target_email.strip().lower())
            ).scalars().first()
        else:
            raise ValueError("Must specify either email or user_id.")

        if target_user is None:
            raise ValueError(f"User account not found.")

        # Check for duplicate
        existing = self.db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == target_user.id,
            )
        ).scalars().first()
        if existing is not None:
            raise DuplicateMemberError(f"User '{target_user.email}' is already a member of this workspace.")

        now = datetime.now(timezone.utc)
        new_membership = WorkspaceMembership(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            user_id=target_user.id,
            role=role.value if isinstance(role, WorkspaceRole) else str(role),
            created_at=now,
            updated_at=now,
        )

        try:
            self.db.add(new_membership)
            self.db.commit()
            self.db.refresh(new_membership)
            logger.info("Added member %s (%s) to workspace %s as %s", target_user.id, target_user.email, workspace_id, role)
            return {
                "id": new_membership.id,
                "workspace_id": new_membership.workspace_id,
                "user_id": new_membership.user_id,
                "email": target_user.email,
                "role": new_membership.role,
                "created_at": new_membership.created_at,
                "updated_at": new_membership.updated_at,
            }
        except IntegrityError as exc:
            self.db.rollback()
            raise DuplicateMemberError(f"User is already a member of this workspace.") from exc

    def update_member_role(
        self,
        workspace_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        target_user_id: uuid.UUID,
        new_role: WorkspaceRole | str,
    ) -> dict[str, Any]:
        """
        Modify member's role (Requires ADMIN role).
        Enforces invariant: cannot demote the last remaining workspace admin.
        """
        requesting_membership = self._get_membership(workspace_id, requesting_user_id)
        if not can_manage_workspace(requesting_membership.role):
            raise WorkspaceAccessDeniedError("Only workspace administrators can update member roles.")

        target_membership = self.db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == target_user_id,
            )
        ).scalars().first()
        if target_membership is None:
            raise ValueError(f"Member '{target_user_id}' not found in workspace.")

        clean_role = new_role.value if isinstance(new_role, WorkspaceRole) else str(new_role)

        # Check last-admin protection
        if target_membership.role == WorkspaceRole.ADMIN.value and clean_role != WorkspaceRole.ADMIN.value:
            admin_count = self._count_admins(workspace_id)
            if admin_count <= 1:
                raise LastAdminError("Cannot remove or demote the last remaining workspace administrator.")

        target_membership.role = clean_role
        target_membership.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(target_membership)

        target_user = self.db.get(User, target_user_id)
        return {
            "id": target_membership.id,
            "workspace_id": target_membership.workspace_id,
            "user_id": target_membership.user_id,
            "email": target_user.email if target_user else None,
            "role": target_membership.role,
            "created_at": target_membership.created_at,
            "updated_at": target_membership.updated_at,
        }

    def remove_member(
        self,
        workspace_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        target_user_id: uuid.UUID,
    ) -> None:
        """
        Remove a user from workspace (Requires ADMIN role, or user leaving voluntarily).
        Enforces invariant: cannot remove the last remaining workspace admin.
        """
        # Authorization: either admin or user self-removing
        if requesting_user_id != target_user_id:
            requesting_membership = self._get_membership(workspace_id, requesting_user_id)
            if not can_manage_workspace(requesting_membership.role):
                raise WorkspaceAccessDeniedError("Only workspace administrators can remove other members.")

        target_membership = self.db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == target_user_id,
            )
        ).scalars().first()
        if target_membership is None:
            raise ValueError(f"Member '{target_user_id}' not found in workspace.")

        # Check last-admin protection
        if target_membership.role == WorkspaceRole.ADMIN.value:
            admin_count = self._count_admins(workspace_id)
            if admin_count <= 1:
                raise LastAdminError("Cannot remove or demote the last remaining workspace administrator.")

        self.db.delete(target_membership)
        self.db.commit()
        logger.info("Removed member %s from workspace %s", target_user_id, workspace_id)

    # Internal helpers
    def _get_membership(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> WorkspaceMembership:
        stmt = select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
        membership = self.db.execute(stmt).scalars().first()
        if membership is None:
            raise WorkspaceNotFoundError(workspace_id)
        return membership

    def _count_admins(self, workspace_id: uuid.UUID) -> int:
        return self.db.scalar(
            select(func.count(WorkspaceMembership.id)).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role == WorkspaceRole.ADMIN.value,
            )
        ) or 0


def get_workspace_service(db: Session = Depends(get_db)) -> WorkspaceService:
    """Dependency injection helper for WorkspaceService."""
    return WorkspaceService(db=db)
