export type WorkspaceRole = 'admin' | 'responder' | 'viewer';

export interface Workspace {
  id: string;
  name: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  member_count?: number;
  current_user_role?: WorkspaceRole | string;
}

export interface WorkspaceListResponse {
  items: Workspace[];
  total: number;
}

export interface WorkspaceMember {
  id: string;
  workspace_id: string;
  user_id: string;
  email?: string;
  role: WorkspaceRole | string;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceMemberListResponse {
  items: WorkspaceMember[];
  total: number;
}

export interface WorkspaceCreatePayload {
  name: string;
}

export interface WorkspaceUpdatePayload {
  name: string;
}

export interface MemberAddPayload {
  email?: string;
  user_id?: string;
  role: WorkspaceRole;
}

export interface MemberUpdatePayload {
  role: WorkspaceRole;
}
