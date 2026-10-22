import { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error in React component tree:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-sre-950 flex flex-col items-center justify-center p-6 text-slate-200">
          <div className="max-w-lg w-full bg-sre-900 border border-rose-800/60 rounded-xl p-6 shadow-2xl">
            <div className="flex items-center space-x-3 mb-4">
              <div className="p-2 bg-rose-950/80 border border-rose-800/80 rounded-lg text-rose-400">
                <AlertTriangle className="w-6 h-6" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white font-mono">Console Render Error</h2>
                <p className="text-xs text-rose-300">An unexpected client-side error occurred</p>
              </div>
            </div>

            <div className="bg-slate-950/80 border border-slate-800 rounded-lg p-3.5 mb-5 font-mono text-xs text-rose-300 overflow-x-auto whitespace-pre-wrap max-h-48">
              {this.state.error?.message || 'Unknown runtime error'}
            </div>

            <button
              onClick={() => window.location.reload()}
              className="w-full flex items-center justify-center px-4 py-2.5 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-medium text-sm rounded-lg shadow-lg shadow-cyan-950/50 transition-all font-mono"
            >
              <RefreshCw className="w-4 h-4 mr-2" />
              Reload Application
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
