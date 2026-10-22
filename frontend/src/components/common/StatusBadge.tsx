import React from 'react';
import { IncidentStatus } from '../../types/incident';

interface StatusBadgeProps {
  status: IncidentStatus | string;
  size?: 'sm' | 'md';
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, size = 'sm' }) => {
  const stUpper = (status || 'OPEN').toUpperCase();

  let colorClasses = 'bg-slate-800 text-slate-300 border-slate-700';

  switch (stUpper) {
    case 'OPEN':
      colorClasses = 'bg-rose-950/60 text-rose-400 border-rose-800/60 animate-pulse';
      break;
    case 'INVESTIGATING':
    case 'ACKNOWLEDGED':
      colorClasses = 'bg-purple-950/60 text-purple-300 border-purple-800/60';
      break;
    case 'RESOLVED':
      colorClasses = 'bg-emerald-950/60 text-emerald-400 border-emerald-800/60';
      break;
    case 'CLOSED':
      colorClasses = 'bg-slate-900/80 text-slate-400 border-slate-800';
      break;
  }

  const sizeClasses = size === 'sm' ? 'px-2.5 py-0.5 text-xs' : 'px-3 py-1 text-sm';

  return (
    <span
      className={`inline-flex items-center font-mono font-medium rounded-full border uppercase tracking-wider ${sizeClasses} ${colorClasses}`}
    >
      {stUpper}
    </span>
  );
};
