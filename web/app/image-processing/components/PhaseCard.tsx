'use client';

import { ReactNode, useState } from 'react';
import { ChevronDown, ChevronRight, Check, Clock, Loader2, SkipForward, RotateCcw } from 'lucide-react';

interface PhaseCardProps {
  phaseNumber: number;
  title: string;
  status: string;
  children: ReactNode;
  defaultOpen?: boolean;
  disabled?: boolean;
  forceOpen?: boolean;
  onRevert?: () => void;
}

const STATUS_CONFIG: Record<string, { icon: typeof Check; color: string; label: string }> = {
  completed: { icon: Check, color: 'text-teal-400', label: 'Done' },
  in_progress: { icon: Loader2, color: 'text-yellow-400', label: 'In Progress' },
  skipped: { icon: SkipForward, color: 'text-slate-500', label: 'Skipped' },
  pending: { icon: Clock, color: 'text-slate-600', label: 'Pending' },
};

export default function PhaseCard({
  phaseNumber,
  title,
  status,
  children,
  defaultOpen = false,
  disabled = false,
  forceOpen,
  onRevert,
}: PhaseCardProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const effectiveOpen = forceOpen ?? isOpen;
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  const StatusIcon = config.icon;

  return (
    <div
      className={`border rounded-xl transition-colors ${
        disabled
          ? 'border-slate-800/50 opacity-50'
          : status === 'completed'
          ? 'border-teal-800/50 bg-slate-900/30'
          : 'border-slate-800 bg-slate-900/50'
      }`}
    >
      <button
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        className="w-full flex items-center gap-3 px-4 py-3 text-left"
      >
        <span className="text-xs font-mono text-slate-600 w-4">{phaseNumber}</span>
        {effectiveOpen ? (
          <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-slate-500" />
        )}
        <span className="flex-1 text-sm font-medium text-slate-200">{title}</span>
        {onRevert && status !== 'pending' && (
          <span
            role="button"
            onClick={(e) => {
              e.stopPropagation();
              onRevert();
            }}
            className="p-1 text-slate-600 hover:text-amber-400 rounded hover:bg-slate-800 transition-colors"
            title="Revert to defaults"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </span>
        )}
        <StatusIcon
          className={`w-4 h-4 ${config.color} ${
            status === 'in_progress' ? 'animate-spin' : ''
          }`}
        />
      </button>

      {effectiveOpen && !disabled && (
        <div className="px-4 pb-4 pt-1 border-t border-slate-800/50">
          <div className="space-y-3">{children}</div>
        </div>
      )}
    </div>
  );
}
