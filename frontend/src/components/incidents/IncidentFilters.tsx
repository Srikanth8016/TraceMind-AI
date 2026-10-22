import React, { useEffect, useState } from 'react';
import { Search, Filter, ArrowUpDown } from 'lucide-react';
import { IncidentFilterParams } from '../../types/incident';
import { listWorkspaces } from '../../api/workspaces';
import { Workspace } from '../../types/workspace';

interface IncidentFiltersProps {
  filters: IncidentFilterParams;
  onChange: (updated: Partial<IncidentFilterParams>) => void;
  onReset: () => void;
}

export const IncidentFilters: React.FC<IncidentFiltersProps> = ({
  filters,
  onChange,
  onReset,
}) => {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);

  useEffect(() => {
    listWorkspaces()
      .then((res) => setWorkspaces(res.items))
      .catch(() => {});
  }, []);
  return (
    <div className="bg-sre-900/60 border border-slate-800 rounded-xl p-4 mb-6 shadow-sm">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
        {/* Search input */}
        <div className="lg:col-span-2 relative">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3 pointer-events-none" />
          <input
            type="text"
            placeholder="Search incident title..."
            value={filters.search || ''}
            onChange={(e) => onChange({ search: e.target.value, skip: 0 })}
            className="w-full pl-9 pr-3 py-2 text-sm bg-sre-950 border border-slate-800 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition-colors font-mono"
          />
        </div>

        {/* Severity Filter */}
        <div>
          <select
            value={filters.severity || ''}
            onChange={(e) => onChange({ severity: e.target.value || undefined, skip: 0 })}
            className="w-full px-3 py-2 text-sm bg-sre-950 border border-slate-800 rounded-lg text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
          >
            <option value="">All Severities</option>
            <option value="CRITICAL">CRITICAL</option>
            <option value="ERROR">ERROR</option>
            <option value="WARNING">WARNING</option>
            <option value="INFO">INFO</option>
          </select>
        </div>

        {/* Status Filter */}
        <div>
          <select
            value={filters.status || ''}
            onChange={(e) => onChange({ status: e.target.value || undefined, skip: 0 })}
            className="w-full px-3 py-2 text-sm bg-sre-950 border border-slate-800 rounded-lg text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
          >
            <option value="">All Statuses</option>
            <option value="OPEN">OPEN</option>
            <option value="INVESTIGATING">INVESTIGATING</option>
            <option value="RESOLVED">RESOLVED</option>
            <option value="CLOSED">CLOSED</option>
          </select>
        </div>

        {/* Workspace Filter */}
        <div>
          <select
            value={filters.workspace_id || ''}
            onChange={(e) => onChange({ workspace_id: e.target.value || undefined, skip: 0 })}
            className="w-full px-3 py-2 text-sm bg-sre-950 border border-slate-800 rounded-lg text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
          >
            <option value="">All Workspaces</option>
            {workspaces.map((ws) => (
              <option key={ws.id} value={ws.id}>
                {ws.name}
              </option>
            ))}
          </select>
        </div>

        {/* Sort By */}
        <div>
          <select
            value={filters.sort_by || 'last_seen_at'}
            onChange={(e) => onChange({ sort_by: e.target.value })}
            className="w-full px-3 py-2 text-sm bg-sre-950 border border-slate-800 rounded-lg text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
          >
            <option value="last_seen_at">Sort: Last Seen</option>
            <option value="created_at">Sort: Created At</option>
            <option value="first_seen_at">Sort: First Seen</option>
            <option value="event_count">Sort: Event Count</option>
            <option value="severity">Sort: Severity</option>
            <option value="title">Sort: Title</option>
          </select>
        </div>

        {/* Sort Order & Reset */}
        <div className="flex items-center space-x-2">
          <button
            type="button"
            onClick={() => onChange({ order: filters.order === 'asc' ? 'desc' : 'asc' })}
            className="flex-1 px-3 py-2 text-xs font-mono font-medium rounded-lg bg-slate-900 hover:bg-slate-850 border border-slate-800 text-slate-300 flex items-center justify-center transition-colors"
            title="Toggle Ascending/Descending"
          >
            <ArrowUpDown className="w-3.5 h-3.5 mr-1 text-slate-400" />
            {filters.order === 'asc' ? 'ASC' : 'DESC'}
          </button>
          <button
            type="button"
            onClick={onReset}
            className="px-3 py-2 text-xs font-mono font-medium rounded-lg bg-slate-900/60 hover:bg-slate-850 border border-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
            title="Reset Filters"
          >
            <Filter className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
