import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getErrorMessage } from '../api/client';
import { Terminal, Shield, LogIn, AlertCircle } from 'lucide-react';

export const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      await login({ email, password });
      navigate('/incidents');
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-sre-950 flex flex-col justify-center items-center px-4 sm:px-6">
      <div className="w-full max-w-md">
        {/* Brand header */}
        <div className="text-center mb-8">
          <div className="inline-flex p-3 bg-gradient-to-br from-cyan-600 to-blue-700 rounded-2xl shadow-xl shadow-cyan-950/60 mb-4">
            <Terminal className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold font-mono tracking-tight text-white">TraceMind AI</h1>
          <p className="mt-1 text-sm text-slate-400 font-mono">SRE Incident Investigation Console</p>
        </div>

        {/* Login Card */}
        <div className="rounded-2xl border border-slate-800 bg-sre-900/90 p-8 shadow-2xl shadow-black/40">
          <h2 className="text-lg font-semibold text-slate-100 font-mono mb-6">
            Authenticate Session
          </h2>

          {error && (
            <div className="mb-6 p-4 rounded-lg bg-red-950/40 border border-red-900/60 text-red-300 text-xs font-mono flex items-start">
              <AlertCircle className="w-4 h-4 text-red-400 mr-2.5 flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs font-mono font-medium text-slate-300 mb-1.5">
                Operator Email
              </label>
              <input
                type="email"
                required
                placeholder="sre@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3.5 py-2.5 text-sm bg-sre-950 border border-slate-800 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 font-mono"
              />
            </div>

            <div>
              <label className="block text-xs font-mono font-medium text-slate-300 mb-1.5">
                Password
              </label>
              <input
                type="password"
                required
                placeholder="••••••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3.5 py-2.5 text-sm bg-sre-950 border border-slate-800 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 font-mono"
              />
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full mt-2 inline-flex items-center justify-center py-2.5 px-4 rounded-lg bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-mono text-sm font-semibold shadow-lg shadow-cyan-950/50 disabled:opacity-50 transition-all"
            >
              <LogIn className="w-4 h-4 mr-2" />
              {isLoading ? 'Authenticating...' : 'Sign In'}
            </button>
          </form>

          <div className="mt-6 pt-5 border-t border-slate-800/80 text-center">
            <p className="text-xs text-slate-400 font-mono">
              New team member?{' '}
              <Link to="/register" className="text-cyan-400 hover:text-cyan-300 font-semibold underline">
                Create user account
              </Link>
            </p>
          </div>
        </div>

        <div className="mt-8 text-center text-xs font-mono text-slate-500 flex items-center justify-center space-x-1.5">
          <Shield className="w-3.5 h-3.5 text-slate-500" />
          <span>Protected by PBKDF2 & JWT Security</span>
        </div>
      </div>
    </div>
  );
};
