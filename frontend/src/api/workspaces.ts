import { apiClient } from './client';
import {
  MemberAddPayload,
  MemberUpdatePayload,
  Workspace,
  WorkspaceCreatePayload,
  WorkspaceListResponse,
  WorkspaceMember,
  WorkspaceMemberListResponse,
  WorkspaceUpdatePayload,
} from '../types/workspace';

export async function listWorkspaces(): Promise<WorkspaceListResponse> {
  const response = await apiClient.get<WorkspaceListResponse>('/api/v1/workspaces');
  return response.data;
}

export async function getWorkspace(workspaceId: string): Promise<Workspace> {
  const response = await apiClient.get<Workspace>(`/api/v1/workspaces/${workspaceId}`);
  return response.data;
}

export async function createWorkspace(payload: WorkspaceCreatePayload): Promise<Workspace> {
  const response = await apiClient.post<Workspace>('/api/v1/workspaces', payload);
  return response.data;
}

export async function updateWorkspace(
  workspaceId: string,
  payload: WorkspaceUpdatePayload
): Promise<Workspace> {
  const response = await apiClient.patch<Workspace>(`/api/v1/workspaces/${workspaceId}`, payload);
  return response.data;
}

export async function listWorkspaceMembers(
  workspaceId: string
): Promise<WorkspaceMemberListResponse> {
  const response = await apiClient.get<WorkspaceMemberListResponse>(
    `/api/v1/workspaces/${workspaceId}/members`
  );
  return response.data;
}

export async function addWorkspaceMember(
  workspaceId: string,
  payload: MemberAddPayload
): Promise<WorkspaceMember> {
  const response = await apiClient.post<WorkspaceMember>(
    `/api/v1/workspaces/${workspaceId}/members`,
    payload
  );
  return response.data;
}

export async function updateWorkspaceMemberRole(
  workspaceId: string,
  userId: string,
  payload: MemberUpdatePayload
): Promise<WorkspaceMember> {
  const response = await apiClient.patch<WorkspaceMember>(
    `/api/v1/workspaces/${workspaceId}/members/${userId}`,
    payload
  );
  return response.data;
}

export async function removeWorkspaceMember(
  workspaceId: string,
  userId: string
): Promise<void> {
  await apiClient.delete(`/api/v1/workspaces/${workspaceId}/members/${userId}`);
}
