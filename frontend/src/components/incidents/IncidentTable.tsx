import React from 'react';
import { Link } from 'react-router-dom';
import { Incident } from '../../types/incident';
import { SeverityBadge } from '../common/SeverityBadge';
import { StatusBadge } from '../common/StatusBadge';
import { ArrowRight, Clock, Layers } from 'lucide-react';

interface IncidentTableProps {
  incidents: Incident[];
  onQuickStatusChange?: (incident: Incident) => void;
}

export const IncidentTable: React.FC<IncidentTableProps> = ({
  incidents,
  onQuickStatusChange,
}) => {
  const formatDate = (isoString: string) => {
    try {
      const d = new Date(isoString);
      return d.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800 bg-sre-900/60 shadow-md shadow-black/20">
      <table className="w-full text-left text-sm">
        <thead className="bg-sre-950/80 text-xs font-mono uppercase tracking-wider text-slate-400 border-b border-slate-800">
          <tr>
            <th className="px-4 py-3.5">Severity</th>
            <th className="px-4 py-3.5">Title & Fingerprint</th>
            <th className="px-4 py-3.5">Service / Env</th>
            <th className="px-4 py-3.5 text-center">Events</th>
            <th className="px-4 py-3.5">Status</th>
            <th className="px-4 py-3.5">Last Seen</th>
            <th className="px-4 py-3.5 text-right">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/60 font-sans">
          {incidents.map((inc) => (
            <tr
              key={inc.id}
              className="hover:bg-slate-850/50 transition-colors group"
            >
              <td className="px-4 py-3.5 whitespace-nowrap">
                <SeverityBadge severity={inc.severity} />
              </td>

              <td className="px-4 py-3.5 max-w-xs sm:max-w-md">
                <Link
                  to={`/incidents/${inc.id}`}
                  className="font-medium text-slate-100 hover:text-cyan-400 transition-colors line-clamp-1 group-hover:underline"
                >
                  {inc.title}
                </Link>
                <div className="mt-0.5 flex items-center text-xs font-mono text-slate-500">
                  <span className="truncate max-w-[160px]">fp:{inc.fingerprint.substring(0, 12)}</span>
                </div>
              </td>

              <td className="px-4 py-3.5 whitespace-nowrap text-xs font-mono text-slate-300">
                <span className="px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700/60 mr-1.5">
                  {inc.service_name}
                </span>
                <span className="text-slate-500">{inc.environment}</span>
              </td>

              <td className="px-4 py-3.5 whitespace-nowrap text-center">
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-mono bg-slate-800/60 text-slate-300">
                  <Layers className="w-3 h-3 mr-1 text-slate-400" />
                  {inc.event_count}
                </span>
              </td>

              <td className="px-4 py-3.5 whitespace-nowrap">
                {onQuickStatusChange ? (
                  <button
                    onClick={() => onQuickStatusChange(inc)}
                    className="hover:opacity-80 transition-opacity"
                    title="Click to update status"
                  >
                    <StatusBadge status={inc.status} />
                  </button>
                ) : (
                  <StatusBadge status={inc.status} />
                )}
              </td>

              <td className="px-4 py-3.5 whitespace-nowrap text-xs text-slate-400 font-mono">
                <div className="flex items-center">
                  <Clock className="w-3.5 h-3.5 mr-1.5 text-slate-500" />
                  {formatDate(inc.last_seen_at)}
                </div>
              </td>

              <td className="px-4 py-3.5 whitespace-nowrap text-right">
                <Link
                  to={`/incidents/${inc.id}`}
                  className="inline-flex items-center text-xs font-mono font-medium text-cyan-400 hover:text-cyan-300 px-2.5 py-1.5 rounded-md hover:bg-cyan-950/40 transition-colors"
                >
                  Investigate
                  <ArrowRight className="w-3.5 h-3.5 ml-1" />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
