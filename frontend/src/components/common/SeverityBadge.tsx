import React from 'react';
import { IncidentSeverity } from '../../types/incident';

interface SeverityBadgeProps {
  severity: IncidentSeverity | string;
  size?: 'sm' | 'md';
}

export const SeverityBadge: React.FC<SeverityBadgeProps> = ({ severity, size = 'sm' }) => {
  const sevUpper = (severity || 'INFO').toUpperCase();

  let colorClasses = 'bg-blue-950/60 text-blue-400 border-blue-800/60';

  switch (sevUpper) {
    case 'CRITICAL':
      colorClasses = 'bg-red-950/60 text-red-400 border-red-800/60 shadow-sm shadow-red-900/30';
      break;
    case 'ERROR':
    case 'HIGH':
      colorClasses = 'bg-orange-950/60 text-orange-400 border-orange-800/60';
      break;
    case 'WARNING':
    case 'MEDIUM':
      colorClasses = 'bg-amber-950/60 text-amber-400 border-amber-800/60';
      break;
    case 'LOW':
      colorClasses = 'bg-emerald-950/60 text-emerald-400 border-emerald-800/60';
      break;
    case 'INFO':
    case 'DEBUG':
    default:
      colorClasses = 'bg-blue-950/60 text-blue-400 border-blue-800/60';
      break;
  }

  const sizeClasses = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-sm';

  return (
    <span
      className={`inline-flex items-center font-mono font-medium rounded-full border ${sizeClasses} ${colorClasses}`}
    >
      <span className="w-1.5 h-1.5 rounded-full mr-1.5 bg-current opacity-80" />
      {sevUpper}
    </span>
  );
};
