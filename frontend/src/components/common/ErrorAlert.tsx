import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorAlertProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export const ErrorAlert: React.FC<ErrorAlertProps> = ({
  title = 'Operation Error',
  message,
  onRetry,
  onDismiss,
}) => {
  return (
    <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-red-200">
      <div className="flex items-start">
        <AlertTriangle className="w-5 h-5 text-red-400 mt-0.5 mr-3 flex-shrink-0" />
        <div className="flex-1">
          <h4 className="text-sm font-semibold text-red-300">{title}</h4>
          <p className="mt-1 text-sm font-mono text-red-200/90 break-words">{message}</p>
        </div>
        {onRetry && (
          <button
            onClick={onRetry}
            className="ml-4 inline-flex items-center px-3 py-1.5 text-xs font-medium rounded bg-red-900/40 hover:bg-red-850 border border-red-700/60 text-red-200 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
            Retry
          </button>
        )}
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="ml-3 text-red-400 hover:text-red-200 text-xs font-medium"
            aria-label="Dismiss error"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
};
