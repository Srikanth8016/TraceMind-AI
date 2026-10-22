import React, { useState } from 'react';
import { AlertOctagon, X, Plus } from 'lucide-react';
import { IncidentCreatePayload, IncidentSeverity } from '../../types/incident';
import { createIncident } from '../../api/incidents';
import { listWorkspaces } from '../../api/workspaces';
import { Workspace } from '../../types/workspace';
import { getErrorMessage } from '../../api/client';

interface CreateIncidentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export const CreateIncidentModal: React.FC<CreateIncidentModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [formData, setFormData] = useState<IncidentCreatePayload>({
    title: '',
    description: '',
    service_name: 'api-service',
    environment: 'production',
    severity: 'ERROR',
    workspace_id: null,
  });
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  React.useEffect(() => {
    if (isOpen) {
      listWorkspaces()
        .then((res) => setWorkspaces(res.items))
        .catch(() => {});
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.title.trim()) {
      setError('Title is required');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await createIncident(formData);
      onSuccess();
      onClose();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="relative w-full max-w-lg bg-sre-950 border border-slate-800 rounded-xl shadow-2xl p-6">
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center space-x-2.5">
            <div className="p-2 bg-red-950/80 text-red-400 rounded-lg border border-red-900/60">
              <AlertOctagon className="w-5 h-5" />
            </div>
            <h3 className="text-base font-semibold text-slate-100">Declare New Incident</h3>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 p-1 rounded-lg hover:bg-slate-900"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {error && (
          <div className="mt-4 p-3 bg-red-950/40 border border-red-900/60 rounded-lg text-xs font-mono text-red-300">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className="block text-xs font-mono font-medium text-slate-300 mb-1">
              Title / Normalized Signature *
            </label>
            <input
              type="text"
              required
              maxLength={255}
              placeholder="e.g., ConnectionRefusedError: payment gateway timeout"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              className="w-full px-3 py-2 text-sm bg-sre-900 border border-slate-800 rounded-lg text-slate-100 focus:outline-none focus:border-cyan-500 font-mono"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-mono font-medium text-slate-300 mb-1">
                Microservice *
              </label>
              <input
                type="text"
                required
                maxLength={100}
                value={formData.service_name}
                onChange={(e) => setFormData({ ...formData, service_name: e.target.value })}
                className="w-full px-3 py-2 text-sm bg-sre-900 border border-slate-800 rounded-lg text-slate-100 focus:outline-none focus:border-cyan-500 font-mono"
              />
            </div>
            <div>
              <label className="block text-xs font-mono font-medium text-slate-300 mb-1">
                Environment *
              </label>
              <input
                type="text"
                required
                maxLength={50}
                value={formData.environment}
                onChange={(e) => setFormData({ ...formData, environment: e.target.value })}
                className="w-full px-3 py-2 text-sm bg-sre-900 border border-slate-800 rounded-lg text-slate-100 focus:outline-none focus:border-cyan-500 font-mono"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-mono font-medium text-slate-300 mb-1">
              Initial Severity
            </label>
            <select
              value={formData.severity}
              onChange={(e) => setFormData({ ...formData, severity: e.target.value as IncidentSeverity })}
              className="w-full px-3 py-2 text-sm bg-sre-900 border border-slate-800 rounded-lg text-slate-100 focus:outline-none focus:border-cyan-500 font-mono"
            >
              <option value="CRITICAL">CRITICAL</option>
              <option value="ERROR">ERROR</option>
              <option value="WARNING">WARNING</option>
              <option value="INFO">INFO</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-mono font-medium text-slate-300 mb-1">
              Target Team Workspace (Optional)
            </label>
            <select
              value={formData.workspace_id || ''}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  workspace_id: e.target.value ? e.target.value : null,
                })
              }
              className="w-full px-3 py-2 text-sm bg-sre-900 border border-slate-800 rounded-lg text-slate-100 focus:outline-none focus:border-cyan-500 font-mono"
            >
              <option value="">Personal / Unassigned</option>
              {workspaces.map((ws) => (
                <option key={ws.id} value={ws.id}>
                  {ws.name} ({ws.current_user_role?.toUpperCase() || 'MEMBER'})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-mono font-medium text-slate-300 mb-1">
              Description (Optional)
            </label>
            <textarea
              rows={3}
              maxLength={2000}
              placeholder="Additional operational context or symptoms..."
              value={formData.description || ''}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full px-3 py-2 text-sm bg-sre-900 border border-slate-800 rounded-lg text-slate-100 focus:outline-none focus:border-cyan-500"
            />
          </div>

          <div className="flex items-center justify-end space-x-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-4 py-2 text-xs font-mono font-medium text-slate-300 hover:text-white rounded-lg hover:bg-slate-900"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex items-center px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white disabled:opacity-50 transition-colors shadow-md shadow-cyan-900/30"
            >
              <Plus className="w-4 h-4 mr-1.5" />
              {isSubmitting ? 'Creating...' : 'Create Incident'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
