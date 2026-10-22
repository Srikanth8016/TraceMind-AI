import React, { useEffect, useState, useCallback } from 'react';
import { getIncidents } from '../api/incidents';
import { Incident, IncidentFilterParams } from '../../types/incident';
import { getErrorMessage } from '../api/client';
import { StatCard } from '../components/common/StatCard';
import { IncidentFilters } from '../components/incidents/IncidentFilters';
import { IncidentTable } from '../components/incidents/IncidentTable';
import { CreateIncidentModal } from '../components/incidents/CreateIncidentModal';
import { StatusUpdateModal } from '../components/incidents/StatusUpdateModal';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorAlert } from '../components/common/ErrorAlert';
import { EmptyState } from '../components/common/EmptyState';
import {
  AlertOctagon,
  Flame,
  Search,
  CheckCircle2,
  Plus,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';

export const IncidentsPage: React.FC = () => {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [filters, setFilters] = useState<IncidentFilterParams>({
    skip: 0,
    limit: 15,
    sort_by: 'last_seen_at',
    order: 'desc',
    search: '',
    severity: '',
    status: '',
  });

  // Modals state
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [statusTargetIncident, setStatusTargetIncident] = useState<Incident | null>(null);

  const fetchIncidents = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await getIncidents(filters);
      setIncidents(res.items);
      setTotal(res.total);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchIncidents();
  }, [fetchIncidents]);

  const handleFilterChange = (updated: Partial<IncidentFilterParams>) => {
    setFilters((prev) => ({ ...prev, ...updated }));
  };

  const handleResetFilters = () => {
    setFilters({
      skip: 0,
      limit: 15,
      sort_by: 'last_seen_at',
      order: 'desc',
      search: '',
      severity: '',
      status: '',
    });
  };

  // Pagination helpers
  const currentSkip = filters.skip || 0;
  const currentLimit = filters.limit || 15;
  const currentPage = Math.floor(currentSkip / currentLimit) + 1;
  const totalPages = Math.ceil(total / currentLimit) || 1;

  const goToPage = (page: number) => {
    const newSkip = (page - 1) * currentLimit;
    setFilters((prev) => ({ ...prev, skip: newSkip }));
  };

  // Quick stats computed from current filtered items & total
  const criticalCount = incidents.filter(
    (i) => i.severity === 'CRITICAL' && (i.status === 'OPEN' || i.status === 'INVESTIGATING')
  ).length;
  const investigatingCount = incidents.filter(
    (i) => i.status === 'INVESTIGATING' || i.status === 'ACKNOWLEDGED'
  ).length;
  const resolvedCount = incidents.filter(
    (i) => i.status === 'RESOLVED' || i.status === 'CLOSED'
  ).length;

  return (
    <div className="space-y-6">
      {/* Page Title & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold font-mono text-white tracking-tight flex items-center">
            <AlertOctagon className="w-6 h-6 mr-2.5 text-cyan-400" />
            Incident Triage Console
          </h1>
          <p className="mt-1 text-xs sm:text-sm text-slate-400 font-mono">
            Correlated error fingerprints & automated AI diagnostic queues
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            onClick={fetchIncidents}
            disabled={isLoading}
            className="p-2.5 text-slate-300 hover:text-white bg-sre-900 border border-slate-800 rounded-lg hover:bg-slate-850 transition-colors"
            title="Refresh List"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setIsCreateModalOpen(true)}
            className="inline-flex items-center px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white transition-colors shadow-lg shadow-cyan-950/40"
          >
            <Plus className="w-4 h-4 mr-1.5" />
            Declare Incident
          </button>
        </div>
      </div>

      {/* Top Telemetry Stats Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total Incidents"
          value={total}
          subtext="Matching current view"
          color="blue"
          icon={<AlertOctagon className="w-5 h-5" />}
        />
        <StatCard
          label="Critical Active"
          value={criticalCount}
          subtext="Requiring immediate paging"
          color="red"
          icon={<Flame className="w-5 h-5" />}
        />
        <StatCard
          label="Under Investigation"
          value={investigatingCount}
          subtext="AI analysis in flight"
          color="purple"
          icon={<Search className="w-5 h-5" />}
        />
        <StatCard
          label="Resolved / Closed"
          value={resolvedCount}
          subtext="Mitigated production state"
          color="green"
          icon={<CheckCircle2 className="w-5 h-5" />}
        />
      </div>

      {/* Filters & Search */}
      <IncidentFilters
        filters={filters}
        onChange={handleFilterChange}
        onReset={handleResetFilters}
      />

      {/* Main Content Area */}
      {isLoading && incidents.length === 0 ? (
        <LoadingSpinner message="Querying PostgreSQL incident index..." size="lg" />
      ) : error ? (
        <ErrorAlert
          title="Incident Query Failed"
          message={error}
          onRetry={fetchIncidents}
        />
      ) : incidents.length === 0 ? (
        <EmptyState
          title="No Incidents Found"
          description="There are no incidents matching your active filter criteria or correlation window."
          action={
            <button
              onClick={() => setIsCreateModalOpen(true)}
              className="inline-flex items-center px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white"
            >
              <Plus className="w-4 h-4 mr-1.5" />
              Declare Incident
            </button>
          }
        />
      ) : (
        <div className="space-y-4">
          <IncidentTable
            incidents={incidents}
            onQuickStatusChange={(inc) => setStatusTargetIncident(inc)}
          />

          {/* Pagination Controls */}
          <div className="flex flex-col sm:flex-row items-center justify-between text-xs font-mono text-slate-400 gap-3 px-1">
            <div>
              Showing <span className="font-semibold text-slate-200">{currentSkip + 1}</span> to{' '}
              <span className="font-semibold text-slate-200">
                {Math.min(currentSkip + currentLimit, total)}
              </span>{' '}
              of <span className="font-semibold text-slate-200">{total}</span> incidents
            </div>

            <div className="flex items-center space-x-2">
              <button
                onClick={() => goToPage(currentPage - 1)}
                disabled={currentPage <= 1 || isLoading}
                className="px-2.5 py-1.5 rounded-lg border border-slate-800 bg-sre-900 hover:bg-slate-850 disabled:opacity-40 transition-colors flex items-center"
              >
                <ChevronLeft className="w-3.5 h-3.5 mr-1" />
                Previous
              </button>
              <span className="px-2 font-medium text-slate-300">
                Page {currentPage} of {totalPages}
              </span>
              <button
                onClick={() => goToPage(currentPage + 1)}
                disabled={currentPage >= totalPages || isLoading}
                className="px-2.5 py-1.5 rounded-lg border border-slate-800 bg-sre-900 hover:bg-slate-850 disabled:opacity-40 transition-colors flex items-center"
              >
                Next
                <ChevronRight className="w-3.5 h-3.5 ml-1" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modals */}
      <CreateIncidentModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onSuccess={fetchIncidents}
      />

      <StatusUpdateModal
        incident={statusTargetIncident}
        isOpen={!!statusTargetIncident}
        onClose={() => setStatusTargetIncident(null)}
        onSuccess={fetchIncidents}
      />
    </div>
  );
};
