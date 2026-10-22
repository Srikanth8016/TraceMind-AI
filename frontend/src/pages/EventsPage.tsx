import React, { useEffect, useState, useCallback } from 'react';
import { getEvents, ingestEvent } from '../api/events';
import { TelemetryEvent, EventFilterParams, EventCreatePayload } from '../types/event';
import { getErrorMessage } from '../api/client';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorAlert } from '../components/common/ErrorAlert';
import { EmptyState } from '../components/common/EmptyState';
import {
  Activity,
  Plus,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Filter,
  CheckCircle,
  X,
} from 'lucide-react';

export const EventsPage: React.FC = () => {
  const [events, setEvents] = useState<TelemetryEvent[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [filters, setFilters] = useState<EventFilterParams>({
    offset: 0,
    limit: 20,
    service_name: '',
    environment: '',
    level: '',
  });

  // Ingest modal
  const [isIngestModalOpen, setIsIngestModalOpen] = useState(false);
  const [ingestForm, setIngestForm] = useState<EventCreatePayload>({
    service_name: 'payment-service',
    environment: 'production',
    level: 'ERROR',
    message: '',
    timestamp: new Date().toISOString(),
  });
  const [ingestSuccess, setIngestSuccess] = useState<string | null>(null);
  const [isIngesting, setIsIngesting] = useState(false);

  const fetchEvents = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const cleanedParams: EventFilterParams = {
        limit: filters.limit,
        offset: filters.offset,
      };
      if (filters.service_name?.trim()) cleanedParams.service_name = filters.service_name.trim();
      if (filters.environment?.trim()) cleanedParams.environment = filters.environment.trim();
      if (filters.level) cleanedParams.level = filters.level;

      const res = await getEvents(cleanedParams);
      setEvents(res.items);
      setTotal(res.total);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  const handleIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsIngesting(true);
    try {
      const payload: EventCreatePayload = {
        ...ingestForm,
        timestamp: new Date().toISOString(),
      };
      const res = await ingestEvent(payload);
      setIngestSuccess(`Event accepted (Event ID: ${res.event_id}, Job ID: ${res.job_id})`);
      fetchEvents();
      setTimeout(() => {
        setIsIngestModalOpen(false);
        setIngestSuccess(null);
        setIngestForm((prev) => ({ ...prev, message: '' }));
      }, 1500);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsIngesting(false);
    }
  };

  const currentOffset = filters.offset || 0;
  const currentLimit = filters.limit || 20;
  const currentPage = Math.floor(currentOffset / currentLimit) + 1;
  const totalPages = Math.ceil(total / currentLimit) || 1;

  const goToPage = (page: number) => {
    const newOffset = (page - 1) * currentLimit;
    setFilters((prev) => ({ ...prev, offset: newOffset }));
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold font-mono text-white tracking-tight flex items-center">
            <Activity className="w-6 h-6 mr-2.5 text-cyan-400" />
            Raw Telemetry Stream
          </h1>
          <p className="mt-1 text-xs sm:text-sm text-slate-400 font-mono">
            Unprocessed incoming log events ingested from application services
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            onClick={fetchEvents}
            disabled={isLoading}
            className="p-2.5 text-slate-300 hover:text-white bg-sre-900 border border-slate-800 rounded-lg hover:bg-slate-850"
            title="Refresh Events"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setIsIngestModalOpen(true)}
            className="inline-flex items-center px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white shadow-md shadow-cyan-950/40"
          >
            <Plus className="w-4 h-4 mr-1.5" />
            Ingest Test Event
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="bg-sre-900/60 border border-slate-800 rounded-xl p-4">
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
          <div>
            <input
              type="text"
              placeholder="Filter by microservice..."
              value={filters.service_name || ''}
              onChange={(e) => setFilters({ ...filters, service_name: e.target.value, offset: 0 })}
              className="w-full px-3 py-2 text-xs bg-sre-950 border border-slate-800 rounded-lg text-slate-100 placeholder-slate-500 font-mono focus:border-cyan-500 focus:outline-none"
            />
          </div>
          <div>
            <input
              type="text"
              placeholder="Filter by environment..."
              value={filters.environment || ''}
              onChange={(e) => setFilters({ ...filters, environment: e.target.value, offset: 0 })}
              className="w-full px-3 py-2 text-xs bg-sre-950 border border-slate-800 rounded-lg text-slate-100 placeholder-slate-500 font-mono focus:border-cyan-500 focus:outline-none"
            />
          </div>
          <div>
            <select
              value={filters.level || ''}
              onChange={(e) => setFilters({ ...filters, level: e.target.value || undefined, offset: 0 })}
              className="w-full px-3 py-2 text-xs bg-sre-950 border border-slate-800 rounded-lg text-slate-200 font-mono focus:border-cyan-500 focus:outline-none"
            >
              <option value="">All Severity Levels</option>
              <option value="CRITICAL">CRITICAL</option>
              <option value="ERROR">ERROR</option>
              <option value="WARNING">WARNING</option>
              <option value="INFO">INFO</option>
              <option value="DEBUG">DEBUG</option>
            </select>
          </div>
          <div>
            <button
              onClick={() => setFilters({ offset: 0, limit: 20, service_name: '', environment: '', level: '' })}
              className="w-full px-3 py-2 text-xs font-mono font-medium rounded-lg bg-slate-900 hover:bg-slate-850 border border-slate-800 text-slate-400 hover:text-slate-200 flex items-center justify-center"
            >
              <Filter className="w-3.5 h-3.5 mr-1.5" />
              Reset Filters
            </button>
          </div>
        </div>
      </div>

      {/* Main List */}
      {isLoading && events.length === 0 ? (
        <LoadingSpinner message="Polling telemetry feed..." size="lg" />
      ) : error ? (
        <ErrorAlert title="Failed to load events" message={error} onRetry={fetchEvents} />
      ) : events.length === 0 ? (
        <EmptyState
          title="No Telemetry Events"
          description="No event records match your current criteria. Ingest an event to trigger asynchronous correlation."
          action={
            <button
              onClick={() => setIsIngestModalOpen(true)}
              className="inline-flex items-center px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white"
            >
              <Plus className="w-4 h-4 mr-1.5" />
              Ingest Test Event
            </button>
          }
        />
      ) : (
        <div className="space-y-4">
          <div className="overflow-x-auto rounded-xl border border-slate-800 bg-sre-900/60 shadow-md">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-sre-950/80 uppercase text-slate-400 border-b border-slate-800">
                <tr>
                  <th className="px-4 py-3">Timestamp (UTC)</th>
                  <th className="px-4 py-3">Level</th>
                  <th className="px-4 py-3">Service</th>
                  <th className="px-4 py-3">Env</th>
                  <th className="px-4 py-3">Message Payload</th>
                  <th className="px-4 py-3">Correlated Incident</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {events.map((evt) => (
                  <tr key={evt.id} className="hover:bg-slate-850/50 transition-colors">
                    <td className="px-4 py-3 whitespace-nowrap text-slate-400 text-[11px]">
                      {new Date(evt.timestamp).toISOString().replace('T', ' ').substring(0, 19)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span
                        className={`font-bold ${
                          evt.level === 'CRITICAL'
                            ? 'text-red-400'
                            : evt.level === 'ERROR'
                            ? 'text-orange-400'
                            : evt.level === 'WARNING'
                            ? 'text-amber-400'
                            : 'text-blue-400'
                        }`}
                      >
                        {evt.level}
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-slate-200">
                      {evt.service_name}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-slate-400">
                      {evt.environment}
                    </td>
                    <td className="px-4 py-3 max-w-md truncate text-slate-300" title={evt.message}>
                      {evt.message}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-[11px]">
                      {evt.incident_id ? (
                        <span className="text-cyan-400 hover:underline">
                          inc:{evt.incident_id.substring(0, 8)}...
                        </span>
                      ) : (
                        <span className="text-slate-600">Pending grouping</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between text-xs font-mono text-slate-400 px-1">
            <span>
              Showing {currentOffset + 1} to {Math.min(currentOffset + currentLimit, total)} of {total} events
            </span>
            <div className="flex items-center space-x-2">
              <button
                onClick={() => goToPage(currentPage - 1)}
                disabled={currentPage <= 1 || isLoading}
                className="px-2.5 py-1.5 rounded-lg border border-slate-800 bg-sre-900 disabled:opacity-40"
              >
                <ChevronLeft className="w-3.5 h-3.5 mr-1 inline" />
                Previous
              </button>
              <span>Page {currentPage} of {totalPages}</span>
              <button
                onClick={() => goToPage(currentPage + 1)}
                disabled={currentPage >= totalPages || isLoading}
                className="px-2.5 py-1.5 rounded-lg border border-slate-800 bg-sre-900 disabled:opacity-40"
              >
                Next
                <ChevronRight className="w-3.5 h-3.5 ml-1 inline" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Ingest Modal */}
      {isIngestModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="w-full max-w-lg bg-sre-950 border border-slate-800 rounded-xl p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-sm font-semibold font-mono text-slate-100">
                Ingest Telemetry Event (HTTP POST)
              </h3>
              <button onClick={() => setIsIngestModalOpen(false)} className="text-slate-400 p-1">
                <X className="w-4 h-4" />
              </button>
            </div>

            {ingestSuccess ? (
              <div className="my-6 p-4 rounded-lg bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs font-mono flex items-center">
                <CheckCircle className="w-5 h-5 mr-2 text-emerald-400 flex-shrink-0" />
                <span>{ingestSuccess}</span>
              </div>
            ) : (
              <form onSubmit={handleIngest} className="mt-4 space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-mono text-slate-400 mb-1">Microservice</label>
                    <input
                      type="text"
                      required
                      value={ingestForm.service_name}
                      onChange={(e) => setIngestForm({ ...ingestForm, service_name: e.target.value })}
                      className="w-full px-3 py-2 text-xs bg-sre-900 border border-slate-800 rounded-lg text-slate-200 font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-mono text-slate-400 mb-1">Environment</label>
                    <input
                      type="text"
                      required
                      value={ingestForm.environment}
                      onChange={(e) => setIngestForm({ ...ingestForm, environment: e.target.value })}
                      className="w-full px-3 py-2 text-xs bg-sre-900 border border-slate-800 rounded-lg text-slate-200 font-mono"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-1">Severity Level</label>
                  <select
                    value={ingestForm.level}
                    onChange={(e) => setIngestForm({ ...ingestForm, level: e.target.value })}
                    className="w-full px-3 py-2 text-xs bg-sre-900 border border-slate-800 rounded-lg text-slate-200 font-mono"
                  >
                    <option value="CRITICAL">CRITICAL</option>
                    <option value="ERROR">ERROR</option>
                    <option value="WARNING">WARNING</option>
                    <option value="INFO">INFO</option>
                    <option value="DEBUG">DEBUG</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-1">Message Payload *</label>
                  <textarea
                    rows={4}
                    required
                    maxLength={5000}
                    placeholder="e.g. PostgresConnectionPoolExhausted: Pool size exceeded limit of 50 connections"
                    value={ingestForm.message}
                    onChange={(e) => setIngestForm({ ...ingestForm, message: e.target.value })}
                    className="w-full px-3 py-2 text-xs bg-sre-900 border border-slate-800 rounded-lg text-slate-200 font-mono focus:border-cyan-500"
                  />
                </div>

                <div className="flex items-center justify-end space-x-3 pt-3 border-t border-slate-800">
                  <button
                    type="button"
                    onClick={() => setIsIngestModalOpen(false)}
                    className="px-4 py-2 text-xs font-mono text-slate-400"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isIngesting || !ingestForm.message.trim()}
                    className="px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white disabled:opacity-50"
                  >
                    {isIngesting ? 'Dispatching...' : 'Dispatch Event'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
