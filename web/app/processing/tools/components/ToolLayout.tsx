'use client';

import { ReactNode } from 'react';
import Link from 'next/link';
import { ArrowLeft, Loader2 } from 'lucide-react';

interface ToolLayoutProps {
  batchName: string;
  toolName: string;
  toolIcon?: ReactNode;
  children: ReactNode;
  sidebar: ReactNode;
  actionBar?: ReactNode;
  loading?: boolean;
  error?: string | null;
}

export default function ToolLayout({
  batchName,
  toolName,
  toolIcon,
  children,
  sidebar,
  actionBar,
  loading,
  error,
}: ToolLayoutProps) {
  return (
    <div className="h-screen flex flex-col bg-gray-950 text-slate-200 overflow-hidden">
      {/* Top bar — breadcrumb + batch name */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-slate-900/80 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <Link
            href="/processing"
            className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-teal-400 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Processing
          </Link>
          <span className="text-slate-600">/</span>
          <Link
            href="/processing/tools"
            className="text-sm text-slate-400 hover:text-teal-400 transition-colors"
          >
            Tools
          </Link>
          <span className="text-slate-600">/</span>
          <div className="flex items-center gap-1.5">
            {toolIcon}
            <span className="text-sm font-medium text-slate-200">{toolName}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">Batch:</span>
          <span className="text-sm font-mono text-teal-400">{decodeURIComponent(batchName)}</span>
        </div>
      </div>

      {/* Main area */}
      {loading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
        </div>
      ) : error ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-red-400 mb-2">{error}</p>
            <Link href="/processing" className="text-sm text-teal-400 hover:underline">
              Back to Processing
            </Link>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex overflow-hidden">
          {/* Canvas area */}
          <div className="flex-1 overflow-auto p-4">
            {children}
          </div>

          {/* Sidebar — parameters */}
          <div className="w-80 border-l border-slate-800 bg-slate-900/50 overflow-y-auto">
            <div className="p-4 space-y-4">
              {sidebar}
            </div>
          </div>
        </div>
      )}

      {/* Action bar — sticky bottom */}
      {actionBar && (
        <div className="px-4 py-3 bg-slate-900/80 border-t border-slate-800 flex items-center justify-end gap-3">
          {actionBar}
        </div>
      )}
    </div>
  );
}

// Action button styles
interface ActionButtonProps {
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  variant?: 'primary' | 'secondary' | 'danger';
  children: ReactNode;
}

export function ActionButton({
  onClick, disabled, loading, variant = 'primary', children
}: ActionButtonProps) {
  const variants = {
    primary: 'bg-teal-600 hover:bg-teal-500 text-white',
    secondary: 'bg-slate-700 hover:bg-slate-600 text-slate-200',
    danger: 'bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-600/30',
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className={`px-4 py-2 rounded-xl text-sm font-medium transition-colors
        ${variants[variant]} ${(disabled || loading) ? 'opacity-50 cursor-not-allowed' : ''}`}
    >
      {loading ? (
        <span className="flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" />
          Processing...
        </span>
      ) : (
        children
      )}
    </button>
  );
}
