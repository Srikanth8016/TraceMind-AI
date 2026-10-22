import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  AlertOctagon,
  Activity,
  BookOpen,
  Server,
  Terminal,
  Shield,
} from 'lucide-react';

interface SidebarProps {
  isOpen: boolean;
  onClose?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ isOpen, onClose }) => {
  const navItems = [
    {
      to: '/incidents',
      label: 'Incident Triage',
      icon: <AlertOctagon className="w-4 h-4 mr-3" />,
    },
    {
      to: '/events',
      label: 'Telemetry Events',
      icon: <Activity className="w-4 h-4 mr-3" />,
    },
    {
      to: '/knowledge',
      label: 'Runbook RAG',
      icon: <BookOpen className="w-4 h-4 mr-3" />,
    },
    {
      to: '/operations',
      label: 'Ops & Metrics',
      icon: <Server className="w-4 h-4 mr-3" />,
    },
  ];

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed top-0 bottom-0 left-0 z-50 w-64 border-r border-slate-800 bg-sre-950/95 flex flex-col transition-transform duration-200 ease-in-out lg:translate-x-0 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Logo / Brand header */}
        <div className="flex items-center px-6 h-16 border-b border-slate-800/80 bg-sre-900/50">
          <div className="p-2 bg-gradient-to-br from-cyan-600 to-blue-700 rounded-lg shadow-md shadow-cyan-900/40 mr-3">
            <Terminal className="w-5 h-5 text-white" />
          </div>
          <div>
            <span className="font-bold font-mono tracking-tight text-white text-base">TraceMind</span>
            <span className="text-cyan-400 font-mono text-xs ml-1.5 px-1.5 py-0.5 rounded bg-cyan-950/80 border border-cyan-800/60 font-semibold">AI SRE</span>
          </div>
        </div>

        {/* Navigation list */}
        <div className="flex-1 px-3 py-6 space-y-1.5 overflow-y-auto">
          <p className="px-3 text-[11px] font-mono font-semibold uppercase tracking-wider text-slate-500 mb-2">
            Incident Console
          </p>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center px-3.5 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 ${
                  isActive
                    ? 'bg-gradient-to-r from-cyan-950/80 to-blue-950/50 text-cyan-300 border-l-2 border-cyan-400 font-semibold shadow-inner'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60'
                }`
              }
            >
              {item.icon}
              {item.label}
            </NavLink>
          ))}
        </div>

        {/* System info footer */}
        <div className="p-4 border-t border-slate-800/80 bg-sre-900/30">
          <div className="flex items-center text-xs text-slate-400 font-mono">
            <Shield className="w-3.5 h-3.5 mr-2 text-emerald-400" />
            <span>Milestone 16 Architecture</span>
          </div>
          <p className="text-[10px] text-slate-500 mt-1 font-mono">v1.0.0-sre-console</p>
        </div>
      </aside>
    </>
  );
};
