import React, { ReactNode } from 'react';

interface StatCardProps {
  label: string;
  value: string | number;
  subtext?: string;
  icon?: ReactNode;
  trend?: 'up' | 'down' | 'neutral';
  color?: 'default' | 'red' | 'orange' | 'yellow' | 'green' | 'blue' | 'purple';
}

export const StatCard: React.FC<StatCardProps> = ({
  label,
  value,
  subtext,
  icon,
  color = 'default',
}) => {
  let borderTopColor = 'border-t-slate-700';
  let iconBgColor = 'bg-slate-800/80 text-slate-300';

  switch (color) {
    case 'red':
      borderTopColor = 'border-t-red-500';
      iconBgColor = 'bg-red-950/80 text-red-400';
      break;
    case 'orange':
      borderTopColor = 'border-t-orange-500';
      iconBgColor = 'bg-orange-950/80 text-orange-400';
      break;
    case 'yellow':
      borderTopColor = 'border-t-amber-500';
      iconBgColor = 'bg-amber-950/80 text-amber-400';
      break;
    case 'green':
      borderTopColor = 'border-t-emerald-500';
      iconBgColor = 'bg-emerald-950/80 text-emerald-400';
      break;
    case 'blue':
      borderTopColor = 'border-t-cyan-500';
      iconBgColor = 'bg-cyan-950/80 text-cyan-400';
      break;
    case 'purple':
      borderTopColor = 'border-t-purple-500';
      iconBgColor = 'bg-purple-950/80 text-purple-400';
      break;
  }

  return (
    <div
      className={`relative overflow-hidden rounded-xl border border-slate-800 bg-sre-900/90 p-5 shadow-lg shadow-black/20 border-t-2 ${borderTopColor}`}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-mono uppercase tracking-wider text-slate-400">{label}</p>
          <p className="mt-2 text-2xl font-bold font-mono text-white tracking-tight">{value}</p>
          {subtext && <p className="mt-1 text-xs text-slate-400 font-sans">{subtext}</p>}
        </div>
        {icon && (
          <div className={`p-3 rounded-lg ${iconBgColor}`}>
            {icon}
          </div>
        )}
      </div>
    </div>
  );
};
