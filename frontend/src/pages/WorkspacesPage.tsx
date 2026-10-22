import React, { useEffect, useState, useCallback } from 'react';
import {
  listWorkspaces,
  createWorkspace,
  listWorkspaceMembers,
  addWorkspaceMember,
  updateWorkspaceMemberRole,
  removeWorkspaceMember,
} from '../api/workspaces';
import { Workspace, WorkspaceMember, WorkspaceRole } from '../types/workspace';
import { getErrorMessage } from '../api/client';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorAlert } from '../components/common/ErrorAlert';
import { EmptyState } from '../components/common/EmptyState';
import {
  Users,
  Plus,
  Shield,
  Trash2,
  X,
  UserPlus,
  RefreshCw,
  Building,
} from 'lucide-react';

export const WorkspacesPage: React.FC = () => {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Modals state
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newWorkspaceName, setNewWorkspaceName] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  // Selected workspace for member management
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [isMembersLoading, setIsMembersLoading] = useState(false);
  const [membersError, setMembersError] = useState<string | null>(null);

  // Add member form
  const [newMemberEmail, setNewMemberEmail] = useState('');
  const [newMemberRole, setNewMemberRole] = useState<WorkspaceRole>('viewer');
  const [isAddingMember, setIsAddingMember] = useState(false);

  const fetchWorkspaces = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await listWorkspaces();
      setWorkspaces(res.items);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  const loadMembers = async (ws: Workspace) => {
    setSelectedWorkspace(ws);
    setIsMembersLoading(true);
    setMembersError(null);
    try {
      const res = await listWorkspaceMembers(ws.id);
      setMembers(res.items);
    } catch (err) {
      setMembersError(getErrorMessage(err));
    } finally {
      setIsMembersLoading(false);
    }
  };

  const handleCreateWorkspace = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newWorkspaceName.trim()) return;

    setIsCreating(true);
    setError(null);
    try {
      await createWorkspace({ name: newWorkspaceName.trim() });
      setNewWorkspaceName('');
      setIsCreateModalOpen(false);
      fetchWorkspaces();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsCreating(false);
    }
  };

  const handleAddMember = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedWorkspace || !newMemberEmail.trim()) return;

    setIsAddingMember(true);
    setMembersError(null);
    try {
      await addWorkspaceMember(selectedWorkspace.id, {
        email: newMemberEmail.trim(),
        role: newMemberRole,
      });
      setNewMemberEmail('');
      setNewMemberRole('viewer');
      loadMembers(selectedWorkspace);
    } catch (err) {
      setMembersError(getErrorMessage(err));
    } finally {
      setIsAddingMember(false);
    }
  };

  const handleRoleChange = async (userId: string, role: WorkspaceRole) => {
    if (!selectedWorkspace) return;
    setMembersError(null);
    try {
      await updateWorkspaceMemberRole(selectedWorkspace.id, userId, { role });
      loadMembers(selectedWorkspace);
    } catch (err) {
      setMembersError(getErrorMessage(err));
    }
  };

  const handleRemoveMember = async (userId: string) => {
    if (!selectedWorkspace) return;
    setMembersError(null);
    try {
      await removeWorkspaceMember(selectedWorkspace.id, userId);
      loadMembers(selectedWorkspace);
    } catch (err) {
      setMembersError(getErrorMessage(err));
    }
  };

  const getRoleBadge = (role?: string) => {
    const r = (role || 'viewer').toLowerCase();
    if (r === 'admin') {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium bg-rose-950/80 text-rose-300 border border-rose-800">
          <Shield className="w-3 h-3 mr-1" />
          ADMIN
        </span>
      );
    }
    if (r === 'responder') {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium bg-amber-950/80 text-amber-300 border border-amber-800">
          RESPONDER
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium bg-slate-800 text-slate-300 border border-slate-700">
        VIEWER
      </span>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold font-mono tracking-tight text-white flex items-center">
            <Building className="w-5 h-5 mr-2.5 text-cyan-400" />
            Team Workspaces
          </h1>
          <p className="mt-1 text-xs text-slate-400 font-mono">
            Multi-tenant workspace isolation and role-based access control (Admin, Responder, Viewer).
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={fetchWorkspaces}
            className="p-2 rounded-lg bg-sre-900 border border-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setIsCreateModalOpen(true)}
            className="inline-flex items-center px-3.5 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-mono text-xs font-semibold shadow-lg shadow-cyan-950/50 transition-all"
          >
            <Plus className="w-4 h-4 mr-1.5" />
            New Workspace
          </button>
        </div>
      </div>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {/* Main Grid */}
      {isLoading ? (
        <LoadingSpinner message="Loading workspaces..." />
      ) : workspaces.length === 0 ? (
        <EmptyState
          title="No Workspaces Enrolled"
          description="Create a team workspace to collaborate with responders and share incident investigations."
          actionLabel="Create First Workspace"
          onAction={() => setIsCreateModalOpen(true)}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {workspaces.map((ws) => (
            <div
              key={ws.id}
              className="rounded-xl border border-slate-800 bg-sre-900/60 p-5 hover:border-slate-700 transition-all flex flex-col justify-between"
            >
              <div>
                <div className="flex items-start justify-between">
                  <h3 className="text-base font-semibold font-mono text-slate-100 truncate pr-2">
                    {ws.name}
                  </h3>
                  {getRoleBadge(ws.current_user_role)}
                </div>

                <div className="mt-4 space-y-1.5 text-xs font-mono text-slate-400">
                  <div className="flex justify-between">
                    <span>Members:</span>
                    <span className="text-slate-200 font-semibold">{ws.member_count ?? 1}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Created:</span>
                    <span className="text-slate-300">
                      {new Date(ws.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-5 pt-4 border-t border-slate-800/80 flex items-center justify-between">
                <button
                  onClick={() => loadMembers(ws)}
                  className="inline-flex items-center text-xs font-mono text-cyan-400 hover:text-cyan-300 font-medium"
                >
                  <Users className="w-3.5 h-3.5 mr-1.5" />
                  Manage Members
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Members Modal */}
      {selectedWorkspace && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
          <div className="bg-sre-900 border border-slate-800 rounded-2xl w-full max-w-2xl overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-sre-950/60">
              <div className="flex items-center space-x-2.5">
                <Users className="w-5 h-5 text-cyan-400" />
                <h2 className="text-sm font-semibold font-mono text-slate-100">
                  {selectedWorkspace.name} — Members
                </h2>
              </div>
              <button
                onClick={() => setSelectedWorkspace(null)}
                className="text-slate-400 hover:text-slate-200 p-1 rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto space-y-5 flex-1">
              {membersError && (
                <ErrorAlert message={membersError} onDismiss={() => setMembersError(null)} />
              )}

              {/* Add Member Form (Admins only) */}
              {selectedWorkspace.current_user_role === 'admin' && (
                <form
                  onSubmit={handleAddMember}
                  className="bg-sre-950 p-4 rounded-xl border border-slate-800 space-y-3"
                >
                  <div className="flex items-center space-x-2 text-xs font-mono font-medium text-slate-300">
                    <UserPlus className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Add Member to Workspace</span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div className="sm:col-span-2">
                      <input
                        type="email"
                        required
                        placeholder="operator@company.com"
                        value={newMemberEmail}
                        onChange={(e) => setNewMemberEmail(e.target.value)}
                        className="w-full px-3 py-2 text-xs font-mono bg-sre-900 border border-slate-800 rounded-lg text-slate-100 focus:outline-none focus:border-cyan-500"
                      />
                    </div>
                    <div>
                      <select
                        value={newMemberRole}
                        onChange={(e) => setNewMemberRole(e.target.value as WorkspaceRole)}
                        className="w-full px-3 py-2 text-xs font-mono bg-sre-900 border border-slate-800 rounded-lg text-slate-200 focus:outline-none focus:border-cyan-500"
                      >
                        <option value="viewer">VIEWER</option>
                        <option value="responder">RESPONDER</option>
                        <option value="admin">ADMIN</option>
                      </select>
                    </div>
                  </div>

                  <button
                    type="submit"
                    disabled={isAddingMember}
                    className="w-full py-2 px-3 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-mono text-xs font-semibold disabled:opacity-50 transition-all flex items-center justify-center"
                  >
                    {isAddingMember ? 'Enrolling...' : 'Enroll Member'}
                  </button>
                </form>
              )}

              {/* Member List */}
              {isMembersLoading ? (
                <LoadingSpinner message="Fetching members..." />
              ) : (
                <div className="space-y-2">
                  <h4 className="text-xs font-mono font-semibold text-slate-400 uppercase tracking-wider">
                    Current Enrolled Operators ({members.length})
                  </h4>

                  <div className="divide-y divide-slate-800/80 border border-slate-800 rounded-xl overflow-hidden bg-sre-950/40">
                    {members.map((m) => (
                      <div
                        key={m.id}
                        className="p-3.5 flex items-center justify-between gap-3 text-xs font-mono"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="font-medium text-slate-200 truncate">
                            {m.email || m.user_id}
                          </p>
                          <p className="text-[11px] text-slate-500 mt-0.5">
                            Joined: {new Date(m.created_at).toLocaleDateString()}
                          </p>
                        </div>

                        <div className="flex items-center space-x-3">
                          {selectedWorkspace.current_user_role === 'admin' ? (
                            <select
                              value={m.role}
                              onChange={(e) =>
                                handleRoleChange(m.user_id, e.target.value as WorkspaceRole)
                              }
                              className="px-2 py-1 text-xs font-mono bg-sre-900 border border-slate-800 rounded text-slate-200 focus:outline-none focus:border-cyan-500"
                            >
                              <option value="admin">ADMIN</option>
                              <option value="responder">RESPONDER</option>
                              <option value="viewer">VIEWER</option>
                            </select>
                          ) : (
                            getRoleBadge(m.role)
                          )}

                          {selectedWorkspace.current_user_role === 'admin' && (
                            <button
                              onClick={() => handleRemoveMember(m.user_id)}
                              className="p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-rose-950/40 transition-colors"
                              title="Remove Member"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Create Workspace Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
          <div className="bg-sre-900 border border-slate-800 rounded-2xl w-full max-w-md overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-sre-950/60">
              <h2 className="text-sm font-semibold font-mono text-slate-100 flex items-center">
                <Plus className="w-4 h-4 mr-2 text-cyan-400" />
                Create Team Workspace
              </h2>
              <button
                onClick={() => setIsCreateModalOpen(false)}
                className="text-slate-400 hover:text-slate-200 p-1 rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateWorkspace} className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-mono font-medium text-slate-300 mb-1.5">
                  Workspace Name
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. SRE Core Platform"
                  value={newWorkspaceName}
                  onChange={(e) => setNewWorkspaceName(e.target.value)}
                  className="w-full px-3.5 py-2.5 text-sm bg-sre-950 border border-slate-800 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 font-mono"
                />
              </div>

              <div className="flex items-center justify-end space-x-3 pt-3">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 text-slate-300 font-mono text-xs hover:bg-slate-700 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isCreating || !newWorkspaceName.trim()}
                  className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-mono text-xs font-semibold shadow-lg shadow-cyan-950/50 disabled:opacity-50 transition-all"
                >
                  {isCreating ? 'Creating...' : 'Create Workspace'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
