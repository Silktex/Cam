'use client';

import { Loader2, RefreshCw, FolderOpen, ChevronRight } from 'lucide-react';
import type { PipelineBatch } from '@/lib/api';

const PHASE_NAMES = [
  'crop_align',
  'color',
  'pbr',
  'map_refine',
  'seamless_tiling',
  'validate_export',
];

const PHASE_LABELS: Record<string, string> = {
  crop_align: 'Crop',
  color: 'Color',
  pbr: 'PBR',
  map_refine: 'Refine',
  seamless_tiling: 'Seamless',
  validate_export: 'Export',
};

function PhaseDotsCompact({ statuses }: { statuses: Record<string, string> }) {
  return (
    <div className="flex items-center gap-1">
      {PHASE_NAMES.map((phase) => {
        const status = statuses[phase] || 'pending';
        const color =
          status === 'completed'
            ? 'bg-teal-400'
            : status === 'in_progress'
            ? 'bg-yellow-400 animate-pulse'
            : status === 'skipped'
            ? 'bg-slate-500'
            : 'bg-slate-600';
        return (
          <div
            key={phase}
            className={`w-2 h-2 rounded-full ${color}`}
            title={`${PHASE_LABELS[phase]}: ${status}`}
          />
        );
      })}
    </div>
  );
}

interface BatchListViewProps {
  batches: PipelineBatch[];
  isLoading: boolean;
  onSelect: (name: string) => void;
  onSync: () => void;
}

export default function BatchListView({
  batches,
  isLoading,
  onSelect,
  onSync,
}: BatchListViewProps) {
  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-semibold text-white">Texturize</h2>
          <p className="text-sm text-slate-400 mt-1">
            Photometric PBR pipeline — select a batch to begin
          </p>
        </div>
        <button
          onClick={onSync}
          disabled={isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700
            text-sm text-slate-300 rounded-lg transition-colors disabled:opacity-50"
        >
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          Refresh
        </button>
      </div>

      {isLoading && batches.length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 text-teal-400 animate-spin" />
        </div>
      ) : batches.length === 0 ? (
        <div className="text-center py-20 text-slate-500">
          <FolderOpen className="w-12 h-12 mx-auto mb-3 opacity-40" />
          <p>No batch folders found</p>
          <p className="text-xs mt-1">Capture images first, then process them here</p>
        </div>
      ) : (
        <div className="space-y-2">
          {batches.map((batch) => {
            const label =
              batch.completed_phases === 0
                ? 'New'
                : batch.completed_phases >= batch.total_phases
                ? 'Done'
                : `Phase ${batch.completed_phases}/${batch.total_phases}`;

            return (
              <button
                key={batch.name}
                onClick={() => onSelect(batch.name)}
                className="w-full flex items-center gap-4 px-4 py-3 bg-slate-900/60
                  hover:bg-slate-800/80 border border-slate-800 hover:border-slate-700
                  rounded-xl transition-colors text-left group"
              >
                <FolderOpen className="w-5 h-5 text-slate-500 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-medium text-slate-200 truncate">
                      {batch.name}
                    </span>
                    <span className="text-xs text-slate-500">
                      {batch.image_count} images
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-1">
                    <PhaseDotsCompact statuses={batch.phase_statuses} />
                    <span className="text-xs text-slate-500">{label}</span>
                  </div>
                </div>
                <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-400 transition-colors" />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
