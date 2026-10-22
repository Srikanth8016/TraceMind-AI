import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  getIncident,
  deleteIncident,
  getIncidentEvents,
} from '../api/incidents';
import {
  requestInvestigation,
  listIncidentInvestigations,
  getInvestigation,
} from '../api/investigations';
import { Incident } from '../types/incident';
import { TelemetryEvent } from '../types/event';
import { InvestigationJob, RootCauseHypothesis, RecommendedAction, RetrievedRunbookRef } from '../types/investigation';
import { getErrorMessage } from '../api/client';
import { SeverityBadge } from '../components/common/SeverityBadge';
import { StatusBadge } from '../components/common/StatusBadge';
import { StatusUpdateModal } from '../components/incidents/StatusUpdateModal';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorAlert } from '../components/common/ErrorAlert';
import {
  ArrowLeft,
  Bot,
  Layers,
  Clock,
  Trash2,
  ExternalLink,
  Sparkles,
  HelpCircle,
  FileText,
  AlertTriangle,
  Lightbulb,
  CheckCircle,
  Loader2,
} from 'lucide-react';

export const IncidentDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [incident, setIncident] = useState<Incident | null>(null);
  const [events, setEvents] = useState<TelemetryEvent[]>([]);
  const [investigation, setInvestigation] = useState<InvestigationJob | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isInvestigating, setIsInvestigating] = useState<boolean>(false);
  const [isStatusModalOpen, setIsStatusModalOpen] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [activeEvidenceHighlight, setActiveEvidenceHighlight] = useState<string | null>(null);

  const fetchIncidentDetails = useCallback(async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);

    try {
      // 1. Fetch incident metadata
      const incData = await getIncident(id);
      setIncident(incData);

      // 2. Fetch correlated child events
      try {
        const eventsData = await getIncidentEvents(id, 50, 0);
        setEvents(eventsData.items);
      } catch (err) {
        console.warn('Could not load incident events:', err);
      }

      // 3. Fetch latest investigation job
      try {
        const jobs = await listIncidentInvestigations(id);
        if (jobs && jobs.length > 0) {
          setInvestigation(jobs[0]); // most recent job
        }
      } catch (err) {
        console.warn('Could not load investigations:', err);
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchIncidentDetails();
  }, [fetchIncidentDetails]);

  // Polling mechanism when investigation job is PENDING or PROCESSING
  useEffect(() => {
    if (!investigation) return;
    if (investigation.status === 'PENDING' || investigation.status === 'PROCESSING') {
      const pollTimer = setInterval(async () => {
        try {
          const freshJob = await getInvestigation(investigation.id);
          setInvestigation(freshJob);
          if (freshJob.status === 'COMPLETED' || freshJob.status === 'FAILED') {
            clearInterval(pollTimer);
            setIsInvestigating(false);
          }
        } catch {
          clearInterval(pollTimer);
          setIsInvestigating(false);
        }
      }, 3000);

      return () => clearInterval(pollTimer);
    }
  }, [investigation]);

  const handleTriggerInvestigation = async () => {
    if (!id) return;
    setIsInvestigating(true);
    try {
      const res = await requestInvestigation(id);
      // Immediately set placeholder job
      setInvestigation({
        id: res.id,
        incident_id: id,
        status: 'PENDING',
        attempt_count: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    } catch (err) {
      setError(getErrorMessage(err));
      setIsInvestigating(false);
    }
  };

  const handleDelete = async () => {
    if (!id || !incident) return;
    if (!window.confirm(`Are you sure you want to delete incident "${incident.title}"? Child events will be preserved.`)) {
      return;
    }
    try {
      await deleteIncident(id);
      navigate('/incidents');
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  if (isLoading && !incident) {
    return <LoadingSpinner message="Loading incident diagnosis & telemetry..." size="lg" />;
  }

  if (error && !incident) {
    return (
      <div className="space-y-4">
        <Link to="/incidents" className="inline-flex items-center text-xs font-mono text-cyan-400 hover:text-cyan-300">
          <ArrowLeft className="w-3.5 h-3.5 mr-1" /> Back to Incidents
        </Link>
        <ErrorAlert title="Failed to load incident" message={error} onRetry={fetchIncidentDetails} />
      </div>
    );
  }

  if (!incident) return null;

  const report = investigation?.report;

  return (
    <div className="space-y-6">
      {/* Back button & Breadcrumb */}
      <div className="flex items-center justify-between">
        <Link
          to="/incidents"
          className="inline-flex items-center text-xs font-mono text-slate-400 hover:text-slate-200 transition-colors"
        >
          <ArrowLeft className="w-4 h-4 mr-1.5" />
          Back to Incident Triage
        </Link>
        <button
          onClick={handleDelete}
          className="inline-flex items-center text-xs font-mono text-red-400 hover:text-red-300 px-3 py-1.5 rounded-lg border border-red-900/60 hover:bg-red-950/40 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5 mr-1.5" />
          Delete Incident
        </button>
      </div>

      {/* Incident Header Card */}
      <div className="rounded-xl border border-slate-800 bg-sre-900/80 p-6 shadow-xl shadow-black/20">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={incident.severity} size="md" />
              <button
                onClick={() => setIsStatusModalOpen(true)}
                className="hover:opacity-80 transition-opacity"
                title="Change status"
              >
                <StatusBadge status={incident.status} size="md" />
              </button>
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
                {incident.service_name}
              </span>
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
                {incident.environment}
              </span>
            </div>

            <h1 className="text-xl sm:text-2xl font-bold font-mono text-white tracking-tight">
              {incident.title}
            </h1>

            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs font-mono text-slate-400">
              <span className="flex items-center">
                <Clock className="w-3.5 h-3.5 mr-1.5 text-slate-500" />
                First seen: {new Date(incident.first_seen_at).toLocaleString()}
              </span>
              <span className="flex items-center">
                <Clock className="w-3.5 h-3.5 mr-1.5 text-slate-500" />
                Last seen: {new Date(incident.last_seen_at).toLocaleString()}
              </span>
              <span className="flex items-center">
                <Layers className="w-3.5 h-3.5 mr-1.5 text-slate-500" />
                {incident.event_count} correlated events
              </span>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={() => setIsStatusModalOpen(true)}
              className="px-4 py-2 text-xs font-mono font-medium rounded-lg border border-slate-700 bg-sre-850 hover:bg-slate-800 text-slate-200 transition-colors"
            >
              Update Workflow Status
            </button>
            <button
              onClick={handleTriggerInvestigation}
              disabled={isInvestigating || investigation?.status === 'PROCESSING'}
              className="inline-flex items-center px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white disabled:opacity-50 transition-all shadow-md shadow-cyan-950/40"
            >
              {isInvestigating || investigation?.status === 'PROCESSING' ? (
                <>
                  <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                  Analyzing Telemetry...
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4 mr-1.5 text-cyan-200" />
                  {report ? 'Re-run AI Diagnosis' : 'Run AI Investigation'}
                </>
              )}
            </button>
          </div>
        </div>

        {/* Metadata Footer */}
        <div className="mt-5 pt-4 border-t border-slate-800/80 flex flex-wrap items-center justify-between text-xs font-mono text-slate-500 gap-2">
          <span className="truncate max-w-sm">Fingerprint: {incident.fingerprint}</span>
          <span>Incident ID: {incident.id}</span>
        </div>
      </div>

      {/* AI Investigation Section */}
      <div className="rounded-xl border border-slate-800 bg-sre-900/60 p-6 shadow-xl shadow-black/20 space-y-6">
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center space-x-2.5">
            <div className="p-2 bg-gradient-to-br from-purple-900/80 to-indigo-950 rounded-lg border border-purple-800/60 text-purple-300">
              <Bot className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold font-mono text-white">
                AI Diagnostic Investigation Engine
              </h2>
              <p className="text-xs text-slate-400 font-mono">
                Asynchronous LLM analysis with prompt-injection defense & evidence grounding
              </p>
            </div>
          </div>

          {investigation && (
            <span
              className={`text-xs font-mono px-2.5 py-1 rounded-full border uppercase ${
                investigation.status === 'COMPLETED'
                  ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800/60'
                  : investigation.status === 'PROCESSING' || investigation.status === 'PENDING'
                  ? 'bg-purple-950/60 text-purple-300 border-purple-800/60 animate-pulse'
                  : 'bg-red-950/60 text-red-400 border-red-800/60'
              }`}
            >
              {investigation.status}
            </span>
          )}
        </div>

        {/* Investigation State Content */}
        {!investigation ? (
          <div className="py-8 text-center">
            <Bot className="w-10 h-10 text-slate-600 mx-auto mb-3" />
            <h3 className="text-sm font-semibold text-slate-300 font-mono">No AI Investigation Run Yet</h3>
            <p className="text-xs text-slate-500 max-w-md mx-auto mt-1 font-mono">
              Execute automated root-cause analysis across correlated telemetry and indexed operational runbooks.
            </p>
            <button
              onClick={handleTriggerInvestigation}
              className="mt-4 inline-flex items-center px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white shadow-md shadow-cyan-950/40"
            >
              <Sparkles className="w-4 h-4 mr-1.5" />
              Trigger Investigation Now
            </button>
          </div>
        ) : investigation.status === 'PENDING' || investigation.status === 'PROCESSING' ? (
          <div className="py-12 flex flex-col items-center justify-center space-y-4">
            <Loader2 className="w-8 h-8 text-purple-400 animate-spin" />
            <div className="text-center">
              <p className="text-sm font-mono text-purple-300 font-semibold">
                Synthesizing Diagnostic Hypothesis...
              </p>
              <p className="text-xs text-slate-500 font-mono mt-1">
                Gathering bounded telemetry, querying vector runbooks, validating citations...
              </p>
            </div>
          </div>
        ) : investigation.status === 'FAILED' ? (
          <div className="p-4 rounded-lg bg-red-950/30 border border-red-900/60 text-red-300">
            <div className="flex items-start">
              <AlertTriangle className="w-5 h-5 text-red-400 mr-2 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-xs font-bold font-mono">Investigation Processing Failed</p>
                <p className="text-xs font-mono text-red-200/80 mt-1">{investigation.error_message}</p>
                <button
                  onClick={handleTriggerInvestigation}
                  className="mt-3 px-3 py-1.5 text-xs font-mono rounded bg-red-900/50 hover:bg-red-850 border border-red-700/60 text-red-200"
                >
                  Retry Investigation
                </button>
              </div>
            </div>
          </div>
        ) : report ? (
          <div className="space-y-6">
            {/* Executive Summary */}
            <div className="rounded-lg bg-sre-950/80 border border-slate-800 p-4">
              <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-cyan-400 mb-2 flex items-center">
                <FileText className="w-4 h-4 mr-1.5" />
                Executive Summary
              </h3>
              <p className="text-sm text-slate-200 leading-relaxed font-sans">
                {report.executive_summary}
              </p>
            </div>

            {/* Root Cause Hypotheses */}
            <div>
              <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center">
                <Lightbulb className="w-4 h-4 mr-1.5 text-amber-400" />
                Grounded Root-Cause Hypotheses ({report.hypotheses.length})
              </h3>
              <div className="space-y-3">
                {report.hypotheses.map((hyp: RootCauseHypothesis, idx: number) => (
                  <div
                    key={idx}
                    className="rounded-lg border border-slate-800 bg-sre-950/60 p-4 space-y-3 hover:border-slate-700 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <span className="text-xs font-mono text-slate-500">Hypothesis #{idx + 1}</span>
                        <h4 className="text-sm font-semibold text-slate-100">{hyp.hypothesis}</h4>
                      </div>
                      <span
                        className={`text-xs font-mono font-semibold px-2.5 py-0.5 rounded-full border ${
                          hyp.confidence === 'HIGH'
                            ? 'bg-emerald-950 text-emerald-400 border-emerald-800'
                            : hyp.confidence === 'MEDIUM'
                            ? 'bg-amber-950 text-amber-400 border-amber-800'
                            : 'bg-slate-800 text-slate-400 border-slate-700'
                        }`}
                      >
                        {hyp.confidence} CONFIDENCE
                      </span>
                    </div>

                    <p className="text-xs text-slate-300 font-sans leading-relaxed">
                      {hyp.reasoning}
                    </p>

                    {/* Cited Evidence IDs */}
                    <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-850">
                      <span className="text-[11px] font-mono text-slate-500 mr-1">Cited Evidence:</span>
                      {hyp.evidence_references.map((ref: string, rIdx: number) => (
                        <button
                          key={rIdx}
                          onClick={() => setActiveEvidenceHighlight(ref === activeEvidenceHighlight ? null : ref)}
                          className={`text-[11px] font-mono px-2 py-0.5 rounded border transition-colors ${
                            activeEvidenceHighlight === ref
                              ? 'bg-cyan-500 text-black border-cyan-400 font-bold'
                              : 'bg-slate-900 text-cyan-300 border-slate-800 hover:border-cyan-600'
                          }`}
                        >
                          {ref}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Recommended Remediation Actions */}
            {report.recommended_actions && report.recommended_actions.length > 0 && (
              <div>
                <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center">
                  <CheckCircle className="w-4 h-4 mr-1.5 text-emerald-400" />
                  Recommended Action Plan
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {report.recommended_actions.map((act: RecommendedAction, idx: number) => (
                    <div
                      key={idx}
                      className="p-3.5 rounded-lg border border-slate-800 bg-sre-950/40 space-y-1.5"
                    >
                      <div className="flex items-center justify-between">
                        <span
                          className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${
                            act.priority === 'P1'
                              ? 'bg-red-950 text-red-400 border-red-800'
                              : act.priority === 'P2'
                              ? 'bg-amber-950 text-amber-400 border-amber-800'
                              : 'bg-blue-950 text-blue-400 border-blue-800'
                          }`}
                        >
                          {act.priority}
                        </span>
                      </div>
                      <p className="text-xs font-semibold text-slate-200">{act.action}</p>
                      <p className="text-[11px] text-slate-400 font-sans">{act.rationale}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Retrieved Runbooks from RAG */}
            {report.retrieved_runbooks && report.retrieved_runbooks.length > 0 && (
              <div>
                <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center">
                  <ExternalLink className="w-4 h-4 mr-1.5 text-indigo-400" />
                  Cited Operational Runbooks ({report.retrieved_runbooks.length})
                </h3>
                <div className="space-y-2">
                  {report.retrieved_runbooks.map((rb: RetrievedRunbookRef, idx: number) => (
                    <div
                      key={idx}
                      className="p-3 rounded-lg border border-slate-800 bg-sre-950/60 text-xs font-mono"
                    >
                      <div className="flex items-center justify-between text-indigo-300 font-medium">
                        <span>{rb.document_title}</span>
                        <span className="text-[10px] text-slate-500">
                          Match: {(rb.similarity_score * 100).toFixed(1)}% | {rb.chunk_id}
                        </span>
                      </div>
                      <p className="text-slate-400 font-sans mt-1 line-clamp-2">{rb.snippet}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Missing Evidence & Limitations */}
            {(report.missing_evidence?.length > 0 || report.limitations?.length > 0) && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-3 border-t border-slate-800">
                {report.missing_evidence?.length > 0 && (
                  <div className="text-xs font-mono text-slate-400">
                    <p className="font-semibold text-slate-300 mb-1 flex items-center">
                      <HelpCircle className="w-3.5 h-3.5 mr-1 text-slate-500" />
                      Unavailable Telemetry Sources:
                    </p>
                    <ul className="list-disc list-inside space-y-0.5 text-slate-500">
                      {report.missing_evidence.map((m: string, idx: number) => (
                        <li key={idx}>{m}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {report.limitations?.length > 0 && (
                  <div className="text-xs font-mono text-slate-400">
                    <p className="font-semibold text-slate-300 mb-1 flex items-center">
                      <AlertTriangle className="w-3.5 h-3.5 mr-1 text-slate-500" />
                      Investigation Caveats:
                    </p>
                    <ul className="list-disc list-inside space-y-0.5 text-slate-500">
                      {report.limitations.map((l: string, idx: number) => (
                        <li key={idx}>{l}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : null}
      </div>

      {/* Correlated Telemetry Events List */}
      <div className="rounded-xl border border-slate-800 bg-sre-900/60 p-6 shadow-xl shadow-black/20 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <h2 className="text-sm font-semibold font-mono text-white flex items-center">
            <Layers className="w-4 h-4 mr-2 text-cyan-400" />
            Correlated Raw Events ({events.length})
          </h2>
          {activeEvidenceHighlight && (
            <span className="text-xs font-mono text-cyan-400">
              Filtering highlight: {activeEvidenceHighlight}
            </span>
          )}
        </div>

        {events.length === 0 ? (
          <p className="text-xs font-mono text-slate-500 py-4 text-center">
            No correlated events linked to this incident.
          </p>
        ) : (
          <div className="space-y-2 overflow-y-auto max-h-96 pr-1 font-mono text-xs">
            {events.map((evt) => {
              const eventRefId = `event:${evt.id}`;
              const isHighlighted = activeEvidenceHighlight === eventRefId;

              return (
                <div
                  key={evt.id}
                  className={`p-3 rounded-lg border transition-all ${
                    isHighlighted
                      ? 'bg-cyan-950/40 border-cyan-500 shadow-md shadow-cyan-900/20'
                      : 'bg-sre-950/60 border-slate-800/80 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between text-[11px] text-slate-400 mb-1">
                    <div className="flex items-center space-x-2">
                      <span
                        className={`font-semibold ${
                          evt.level === 'CRITICAL'
                            ? 'text-red-400'
                            : evt.level === 'ERROR'
                            ? 'text-orange-400'
                            : 'text-blue-400'
                        }`}
                      >
                        [{evt.level}]
                      </span>
                      <span className="text-slate-300">{evt.service_name}</span>
                      <span className="text-slate-500">({evt.environment})</span>
                    </div>
                    <span>{new Date(evt.timestamp).toISOString()}</span>
                  </div>
                  <p className="text-slate-200 text-xs break-words">{evt.message}</p>
                  <div className="mt-1 flex items-center justify-between text-[10px] text-slate-500">
                    <span>ID: {evt.id}</span>
                    {isHighlighted && <span className="text-cyan-400 font-bold">CITED AS EVIDENCE</span>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Status Transition Modal */}
      <StatusUpdateModal
        incident={incident}
        isOpen={isStatusModalOpen}
        onClose={() => setIsStatusModalOpen(false)}
        onSuccess={(updated) => setIncident(updated)}
      />
    </div>
  );
};
