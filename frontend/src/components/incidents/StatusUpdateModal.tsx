import React, { useState } from 'react';
import { X, CheckCircle, AlertTriangle } from 'lucide-react';
import { Incident, IncidentStatus } from '../../types/incident';
import { updateIncidentStatus } from '../../api/incidents';
import { getErrorMessage } from '../../api/client';
import { StatusBadge } from '../common/StatusBadge';

interface StatusUpdateModalProps {
  incident: Incident | null;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (updated: Incident) => void;
}

const ALLOWED_NEXT_STATUSES: Record<string, IncidentStatus[]> = {
  OPEN: ['INVESTIGATING', 'RESOLVED', 'CLOSED'],
  INVESTIGATING: ['RESOLVED', 'CLOSED'],
  ACKNOWLEDGED: ['RESOLVED', 'CLOSED'],
  RESOLVED: ['CLOSED', 'OPEN'],
  CLOSED: ['OPEN'],
};

export const StatusUpdateModal: React.FC<StatusUpdateModalProps> = ({
  incident,
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [selectedStatus, setSelectedStatus] = useState<IncidentStatus | ''>('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen || !incident) return null;

  const currentStatus = incident.status;
  const allowed = ALLOWED_NEXT_STATUSES[currentStatus] || ['OPEN', 'INVESTIGATING', 'RESOLVED', 'CLOSED'];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedStatus) {
      setError('Please select a target status');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const updated = await updateIncidentStatus(incident.id, {
        status: selectedStatus as IncidentStatus,
      });
      onSuccess(updated);
      onClose();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="relative w-full max-w-md bg-sre-950 border border-slate-800 rounded-xl shadow-2xl p-6">
        <div className="flex items-center justify-between pb-3 border-b border-slate-800">
          <h3 className="text-sm font-semibold text-slate-100 font-mono">
            Transition Incident Lifecycle
          </h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 p-1 rounded-lg hover:bg-slate-900"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="mt-4">
          <p className="text-xs text-slate-400 font-mono">Target Incident:</p>
          <p className="text-sm font-medium text-slate-200 mt-0.5 line-clamp-1">{incident.title}</p>
          <div className="mt-2 flex items-center space-x-2 text-xs font-mono text-slate-400">
            <span>Current Status:</span>
            <StatusBadge status={currentStatus} />
          </div>
        </div>

        {error && (
          <div className="mt-4 p-3 bg-red-950/40 border border-red-900/60 rounded-lg text-xs font-mono text-red-300 flex items-start">
            <AlertTriangle className="w-4 h-4 text-red-400 mr-2 flex-shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
          <div>
            <label className="block text-xs font-mono font-medium text-slate-300 mb-2">
              Select Valid Transition:
            </label>
            <div className="space-y-2">
              {allowed.map((st) => (
                <label
                  key={st}
                  className={`flex items-center justify-between p-3 rounded-lg border cursor-pointer transition-all ${
                    selectedStatus === st
                      ? 'border-cyan-500 bg-cyan-950/30'
                      : 'border-slate-800 bg-sre-900/60 hover:bg-slate-850'
                  }`}
                >
                  <div className="flex items-center space-x-3">
                    <input
                      type="radio"
                      name="target_status"
                      value={st}
                      checked={selectedStatus === st}
                      onChange={() => setSelectedStatus(st)}
                      className="text-cyan-500 focus:ring-cyan-500 focus:ring-offset-0 bg-slate-900 border-slate-700"
                    />
                    <span className="font-mono text-xs font-semibold uppercase text-slate-200">
                      {st}
                    </span>
                  </div>
                  <span className="text-[11px] font-mono text-slate-400">
                    {st === 'INVESTIGATING'
                      ? 'Begin diagnosis'
                      : st === 'RESOLVED'
                      ? 'Mitigated in production'
                      : st === 'CLOSED'
                      ? 'Completed post-mortem'
                      : 'Reopen incident'}
                  </span>
                </label>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-end space-x-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-4 py-2 text-xs font-mono font-medium text-slate-400 hover:text-slate-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !selectedStatus}
              className="inline-flex items-center px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white disabled:opacity-50 transition-colors shadow-md shadow-cyan-900/30"
            >
              <CheckCircle className="w-3.5 h-3.5 mr-1.5" />
              {isSubmitting ? 'Updating...' : 'Confirm Transition'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
