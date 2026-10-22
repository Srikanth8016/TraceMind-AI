import React, { useEffect, useState, useCallback } from 'react';
import { getHealth, getDbHealth, getReadiness, getMetrics } from '../api/ops';
import { HealthResponse, DbHealthResponse, ReadinessResponse, MetricsSnapshot } from '../types/ops';
import { getErrorMessage } from '../api/client';
import { StatCard } from '../components/common/StatCard';
import { ErrorAlert } from '../components/common/ErrorAlert';
import {
  Server,
  Database,
  Activity,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Clock,
  Gauge,
  TrendingDown,
} from 'lucide-react';

export const OperationsPage: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [dbHealth, setDbHealth] = useState<DbHealthResponse | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchOperationalTelemetry = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [hRes, dbRes, rRes, mRes] = await Promise.all([
        getHealth().catch(() => ({ status: 'unreachable' })),
        getDbHealth().catch(() => ({ status: 'degraded', database: 'unreachable' })),
        getReadiness().catch(() => ({ status: 'unhealthy', database: 'unreachable', redis: 'unreachable' })),
        getMetrics().catch(() => null),
      ]);

      setHealth(hRes);
      setDbHealth(dbRes);
      setReadiness(rRes);
      if (mRes) setMetrics(mRes);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOperationalTelemetry();
    const interval = setInterval(fetchOperationalTelemetry, 15000); // 15s auto-refresh
    return () => clearInterval(interval);
  }, [fetchOperationalTelemetry]);

  const formatUptime = (seconds?: number) => {
    if (!seconds) return '0s';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return `${hrs}h ${mins}m ${secs}s`;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold font-mono text-white tracking-tight flex items-center">
            <Server className="w-6 h-6 mr-2.5 text-cyan-400" />
            Operational Health & Telemetry
          </h1>
          <p className="mt-1 text-xs sm:text-sm text-slate-400 font-mono">
            Probes, dependency connectivity (PostgreSQL/Redis), and request rate metrics
          </p>
        </div>
        <button
          onClick={fetchOperationalTelemetry}
          disabled={isLoading}
          className="inline-flex items-center px-4 py-2 text-xs font-mono font-medium rounded-lg bg-sre-900 border border-slate-800 text-slate-300 hover:text-white hover:bg-slate-850"
        >
          <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh Status
        </button>
      </div>

      {error && <ErrorAlert title="Telemetry Poll Error" message={error} onRetry={fetchOperationalTelemetry} />}

      {/* Health Probes Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Liveness */}
        <div className="rounded-xl border border-slate-800 bg-sre-900/60 p-5 shadow-lg">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-mono uppercase text-slate-400">Pod Liveness (/health)</span>
            {health?.status === 'healthy' ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            ) : (
              <AlertTriangle className="w-5 h-5 text-rose-400" />
            )}
          </div>
          <p className="text-xl font-bold font-mono text-white capitalize">{health?.status || 'Unknown'}</p>
          <p className="text-xs text-slate-500 font-mono mt-1">Web server process running</p>
        </div>

        {/* Database Readiness */}
        <div className="rounded-xl border border-slate-800 bg-sre-900/60 p-5 shadow-lg">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-mono uppercase text-slate-400">PostgreSQL (/health/db)</span>
            <Database className="w-5 h-5 text-cyan-400" />
          </div>
          <p className="text-xl font-bold font-mono text-white capitalize">{dbHealth?.database || 'Unknown'}</p>
          <p className="text-xs text-slate-500 font-mono mt-1">Connection pool pre-ping verified</p>
        </div>

        {/* Overall Readiness */}
        <div className="rounded-xl border border-slate-800 bg-sre-900/60 p-5 shadow-lg">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-mono uppercase text-slate-400">Readiness Probe (/ready)</span>
            {readiness?.status === 'ready' ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            ) : (
              <AlertTriangle className="w-5 h-5 text-rose-400" />
            )}
          </div>
          <p className="text-xl font-bold font-mono text-white uppercase">{readiness?.status || 'Unknown'}</p>
          <div className="mt-1 flex items-center space-x-3 text-xs font-mono text-slate-400">
            <span>DB: {readiness?.database}</span>
            <span>Redis: {readiness?.redis}</span>
          </div>
        </div>
      </div>

      {/* Telemetry Metrics Snapshot */}
      {metrics && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold font-mono text-slate-300 uppercase tracking-wider flex items-center">
            <Activity className="w-4 h-4 mr-2 text-cyan-400" />
            Traffic & Latency Telemetry (/metrics)
          </h2>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              label="Uptime"
              value={formatUptime(metrics.uptime_seconds)}
              subtext="Process longevity"
              color="blue"
              icon={<Clock className="w-5 h-5" />}
            />
            <StatCard
              label="Total Requests"
              value={metrics.total_requests}
              subtext="Handled since startup"
              color="purple"
              icon={<Gauge className="w-5 h-5" />}
            />
            <StatCard
              label="Avg Latency"
              value={`${metrics.avg_latency_ms.toFixed(1)} ms`}
              subtext="Monotonic request duration"
              color="green"
              icon={<TrendingDown className="w-5 h-5" />}
            />
            <StatCard
              label="Error Rate"
              value={`${metrics.error_rate_pct.toFixed(2)}%`}
              subtext={`${metrics.total_errors_4xx} 4xx | ${metrics.total_errors_5xx} 5xx`}
              color={metrics.error_rate_pct > 5 ? 'red' : 'default'}
              icon={<AlertTriangle className="w-5 h-5" />}
            />
          </div>

          {/* HTTP Status Breakdown */}
          {metrics.status_counts && Object.keys(metrics.status_counts).length > 0 && (
            <div className="rounded-xl border border-slate-800 bg-sre-900/60 p-6 shadow-xl">
              <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-slate-400 mb-4">
                HTTP Status Code Distribution
              </h3>
              <div className="flex flex-wrap gap-3">
                {Object.entries(metrics.status_counts).map(([code, count]) => {
                  const num = parseInt(code, 10);
                  const badgeColor =
                    num < 300
                      ? 'bg-emerald-950/80 text-emerald-300 border-emerald-800/60'
                      : num < 500
                      ? 'bg-amber-950/80 text-amber-300 border-amber-800/60'
                      : 'bg-red-950/80 text-red-300 border-red-800/60';

                  return (
                    <div
                      key={code}
                      className={`px-3.5 py-2 rounded-lg border font-mono text-xs flex items-center space-x-2 ${badgeColor}`}
                    >
                      <span className="font-bold">{code}</span>
                      <span className="text-slate-400 font-sans">({String(count)} requests)</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
