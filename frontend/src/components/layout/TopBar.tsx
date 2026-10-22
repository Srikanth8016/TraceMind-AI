import React, { useEffect, useState } from 'react';
import { Menu, LogOut, CheckCircle2, AlertCircle, RefreshCw, User as UserIcon } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { getReadiness } from '../../api/ops';
import { ReadinessResponse } from '../../types/ops';

interface TopBarProps {
  onToggleSidebar: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({ onToggleSidebar }) => {
  const { user, logout } = useAuth();
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [isCheckingHealth, setIsCheckingHealth] = useState<boolean>(false);

  const checkHealth = async () => {
    setIsCheckingHealth(true);
    try {
      const data = await getReadiness();
      setReadiness(data);
    } catch {
      setReadiness({ status: 'unhealthy', database: 'unreachable', redis: 'unreachable' });
    } finally {
      setIsCheckingHealth(false);
    }
  };

  useEffect(() => {
    checkHealth();
    const timer = setInterval(checkHealth, 30000); // 30s poll
    return () => clearInterval(timer);
  }, []);

  const isHealthy = readiness?.status === 'ready';

  return (
    <header className="h-16 border-b border-slate-800 bg-sre-950/80 backdrop-blur-md sticky top-0 z-30 flex items-center justify-between px-4 sm:px-6">
      {/* Left side: Hamburger button + Title */}
      <div className="flex items-center space-x-3">
        <button
          onClick={onToggleSidebar}
          className="p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-900 lg:hidden focus:outline-none"
          aria-label="Toggle Navigation"
        >
          <Menu className="w-5 h-5" />
        </button>
        <div className="hidden sm:flex items-center space-x-2">
          <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-400">
            Cluster: default
          </span>
          <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-400">
            Env: local
          </span>
        </div>
      </div>

      {/* Right side: Readiness status + User profile + Logout */}
      <div className="flex items-center space-x-4">
        {/* Backend readiness probe indicator */}
        <div
          onClick={checkHealth}
          className="flex items-center space-x-2 px-2.5 py-1 rounded-full border border-slate-800 bg-sre-900/60 text-xs font-mono cursor-pointer hover:border-slate-700 transition-colors"
          title={`Backend status: ${readiness?.status || 'checking'}, DB: ${readiness?.database || 'unknown'}, Redis: ${readiness?.redis || 'unknown'}`}
        >
          {isCheckingHealth ? (
            <RefreshCw className="w-3.5 h-3.5 text-slate-400 animate-spin" />
          ) : isHealthy ? (
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
          ) : (
            <AlertCircle className="w-3.5 h-3.5 text-rose-400" />
          )}
          <span className={isHealthy ? 'text-emerald-400' : 'text-rose-400'}>
            {isHealthy ? 'API ONLINE' : 'API DEGRADED'}
          </span>
        </div>

        {/* User Account */}
        {user && (
          <div className="flex items-center space-x-3 border-l border-slate-800 pl-4">
            <div className="flex items-center text-xs font-mono text-slate-300">
              <UserIcon className="w-3.5 h-3.5 mr-1.5 text-slate-400" />
              <span className="max-w-[140px] truncate sm:max-w-[200px]">{user.email}</span>
            </div>
            <button
              onClick={logout}
              className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-950/40 transition-colors"
              title="Sign Out"
              aria-label="Logout"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </header>
  );
};
