import React, { ReactNode } from 'react';
import { Inbox } from 'lucide-react';

interface EmptyStateProps {
  title: string;
  description: string;
  icon?: ReactNode;
  action?: ReactNode;
  actionLabel?: string;
  onAction?: () => void;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  icon,
  action,
  actionLabel,
  onAction,
}) => {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-center rounded-xl border border-dashed border-slate-800 bg-slate-900/30">
      <div className="p-3 bg-slate-800/60 rounded-full text-slate-400 mb-4">
        {icon || <Inbox className="w-8 h-8" />}
      </div>
      <h3 className="text-base font-semibold text-slate-200">{title}</h3>
      <p className="mt-1 text-sm text-slate-400 max-w-sm">{description}</p>
      {action && <div className="mt-5">{action}</div>}
      {!action && actionLabel && onAction && (
        <div className="mt-5">
          <button
            onClick={onAction}
            className="px-4 py-2 text-xs font-mono font-medium rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white shadow-lg shadow-cyan-900/20 transition-all"
          >
            {actionLabel}
          </button>
        </div>
      )}
    </div>
  );
};
