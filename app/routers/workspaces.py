"""
app/routers/workspaces.py — REST API router for Team Workspaces and RBAC Membership Management.

Milestone 17: Team Workspaces & Role-Based Access Control.
"""

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_active_user
from app.models.user import User
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceListResponse,
    WorkspaceMemberAdd,
    WorkspaceMemberListResponse,
    WorkspaceMemberResponse,
    WorkspaceMemberUpdate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.services.rbac import (
    DuplicateMemberError,
    LastAdminError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.services.workspace_service import WorkspaceService, get_workspace_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new workspace",
    description="Create a team workspace and automatically assign the creator as the initial ADMIN member.",
)
def create_workspace(
    workspace_in: WorkspaceCreate,
    current_user: User = Depends(get_current_active_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    """Create team workspace."""
    ws = workspace_service.create_workspace(name=workspace_in.name, creator=current_user)
    return WorkspaceResponse(
        id=ws.id,
        name=ws.name,
        created_by=ws.created_by,
        created_at=ws.created_at,
        updated_at=ws.updated_at,
        member_count=1,
        current_user_role="admin",
    )


@router.get(
    "",
    response_model=WorkspaceListResponse,
    status_code=status.HTTP_200_OK,
    summary="List authorized workspaces",
    description="Retrieve all workspaces that the authenticated user belongs to with role and member counts.",
)
def list_workspaces(
    current_user: User = Depends(get_current_active_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceListResponse:
    """List user's workspaces."""
    workspaces = workspace_service.list_user_workspaces(user_id=current_user.id)
    return WorkspaceListResponse(
        items=[WorkspaceResponse(**ws) for ws in workspaces],
        total=len(workspaces),
    )


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get workspace details",
    description="Retrieve workspace details by UUID if the authenticated user is an active member.",
)
def get_workspace(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    """Get single workspace."""
    try:
        ws_dict = workspace_service.get_workspace_for_user(workspace_id, current_user.id)
        return WorkspaceResponse(**ws_dict)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_id}' not found.",
        )


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_200_OK,
    summary="Update workspace name",
    description="Update team workspace attributes. Requires ADMIN role in the target workspace.",
)
def update_workspace(
    workspace_id: uuid.UUID,
    workspace_in: WorkspaceUpdate,
    current_user: User = Depends(get_current_active_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    """Update workspace."""
    try:
        ws = workspace_service.update_workspace(
            workspace_id=workspace_id,
            requesting_user_id=current_user.id,
            name=workspace_in.name,
        )
        ws_dict = workspace_service.get_workspace_for_user(workspace_id, current_user.id)
        return WorkspaceResponse(**ws_dict)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_id}' not found.",
        )
    except WorkspaceAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )


@router.get(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberListResponse,
    status_code=status.HTTP_200_OK,
    summary="List workspace members",
    description="Retrieve list of members and their roles. Requires active membership in workspace.",
)
def list_workspace_members(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceMemberListResponse:
    """List members."""
    try:
        members = workspace_service.list_members(workspace_id, current_user.id)
        return WorkspaceMemberListResponse(
            items=[WorkspaceMemberResponse(**m) for m in members],
            total=len(members),
        )
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_id}' not found.",
        )


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add member to workspace",
    description="Enroll a registered user into the workspace. Requires ADMIN role in workspace.",
)
def add_workspace_member(
    workspace_id: uuid.UUID,
    member_in: WorkspaceMemberAdd,
    current_user: User = Depends(get_current_active_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceMemberResponse:
    """Add member."""
    if not member_in.email and not member_in.user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Must supply either 'email' or 'user_id' to add a workspace member.",
        )

    try:
        member = workspace_service.add_member(
            workspace_id=workspace_id,
            requesting_user_id=current_user.id,
            target_email=str(member_in.email) if member_in.email else None,
            target_user_id=member_in.user_id,
            role=member_in.role,
        )
        return WorkspaceMemberResponse(**member)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_id}' not found.",
        )
    except WorkspaceAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except DuplicateMemberError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.patch(
    "/{workspace_id}/members/{user_id}",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_200_OK,
    summary="Update member role",
    description="Change a member's role (admin, responder, viewer). Requires ADMIN role. Prevents demoting the last admin.",
)
def update_workspace_member_role(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    role_in: WorkspaceMemberUpdate,
    current_user: User = Depends(get_current_active_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceMemberResponse:
    """Update role."""
    try:
        updated = workspace_service.update_member_role(
            workspace_id=workspace_id,
            requesting_user_id=current_user.id,
            target_user_id=user_id,
            new_role=role_in.role,
        )
        return WorkspaceMemberResponse(**updated)
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_id}' not found.",
        )
    except WorkspaceAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except LastAdminError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove workspace member",
    description="Remove a member from the workspace. Requires ADMIN role (or self-removal). Prevents removing the last admin.",
)
def remove_workspace_member(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    """Remove member."""
    try:
        workspace_service.remove_member(
            workspace_id=workspace_id,
            requesting_user_id=current_user.id,
            target_user_id=user_id,
        )
    except WorkspaceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_id}' not found.",
        )
    except WorkspaceAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except LastAdminError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
