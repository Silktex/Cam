'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft, BarChart3, Sun, Move, Layers, Grid3x3, Shield,
  Stamp, Minimize2, Loader2, RefreshCw, Search, Check, ChevronRight,
} from 'lucide-react';
import { getBatches, syncAllBatches, getToolsStatus, Batch } from '@/lib/api';
import dynamic from 'next/dynamic';

const DashboardHeader = dynamic(() => import('../../all/components/DashboardHeader'), {
  ssr: false,
});

// Pipeline-ordered main chain tools
const pipelineTools = [
  {
    id: 'perspective',
    name: 'Perspective',
    description: 'Correct keystone and skew distortion',
    icon: Move,
    color: 'from-violet-500/20 to-violet-600/10 border-violet-500/30',
    iconColor: 'text-violet-400',
    outputFolder: 'perspective_corrected',
    inputHint: 'cropped/',
    outputHint: 'perspective_corrected/',
  },
  {
    id: 'equalize',
    name: 'Equalize',
    description: 'Match exposure and color across multi-angle captures',
    icon: BarChart3,
    color: 'from-blue-500/20 to-blue-600/10 border-blue-500/30',
    iconColor: 'text-blue-400',
    outputFolder: 'equalized',
    inputHint: 'color_calibrated/',
    outputHint: 'equalized/',
  },
  {
    id: 'flatten',
    name: 'Flatten',
    description: 'Remove surface wrinkles and folds using PBR normal maps',
    icon: Minimize2,
    color: 'from-indigo-500/20 to-indigo-600/10 border-indigo-500/30',
    iconColor: 'text-indigo-400',
    outputFolder: 'flattened',
    inputHint: 'equalized/',
    outputHint: 'flattened/',
  },
  {
    id: 'delight',
    name: 'Delight',
    description: 'Remove residual lighting gradients from calibrated images',
    icon: Sun,
    color: 'from-amber-500/20 to-amber-600/10 border-amber-500/30',
    iconColor: 'text-amber-400',
    outputFolder: 'delighted',
    inputHint: 'flattened/',
    outputHint: 'delighted/',
  },
  {
    id: 'seamless',
    name: 'Make Seamless',
    description: 'Blend edges for tileable textures without visible seams',
    icon: Layers,
    color: 'from-teal-500/20 to-teal-600/10 border-teal-500/30',
    iconColor: 'text-teal-400',
    outputFolder: 'seamless',
    inputHint: 'delighted/',
    outputHint: 'seamless/',
  },
  {
    id: 'tiling',
    name: 'Tiling',
    description: 'Preview and export repeating tile patterns with 3D preview',
    icon: Grid3x3,
    color: 'from-emerald-500/20 to-emerald-600/10 border-emerald-500/30',
    iconColor: 'text-emerald-400',
    outputFolder: 'tiled',
    inputHint: 'seamless/',
    outputHint: 'tiled/',
  },
];

const utilityTools = [
  {
    id: 'validate',
    name: 'PBR Validate',
    description: 'Verify PBR map channel ranges and accuracy',
    icon: Shield,
    color: 'from-cyan-500/20 to-cyan-600/10 border-cyan-500/30',
    iconColor: 'text-cyan-400',
    badge: 'Quality Check',
  },
  {
    id: 'clone',
    name: 'Clone Stamp',
    description: 'Remove lint, threads, dust with inpaint or clone',
    icon: Stamp,
    color: 'from-rose-500/20 to-rose-600/10 border-rose-500/30',
    iconColor: 'text-rose-400',
    badge: 'Utility',
  },
];

interface ToolsStatus {
  perspective_corrected: boolean;
  equalized: boolean;
  flattened: boolean;
  delighted: boolean;
  seamless: boolean;
  tiled: boolean;
}

export default function ToolsHubPage() {
  const router = useRouter();
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [selectedBatch, setSelectedBatch] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [toolsStatus, setToolsStatus] = useState<ToolsStatus | null>(null);

  const fetchBatches = useCallback(async () => {
    try {
      const res = await getBatches();
      setBatches(res.data.batches || []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBatches();
  }, [fetchBatches]);

  // Fetch tools status when batch changes
  useEffect(() => {
    if (!selectedBatch) {
      setToolsStatus(null);
      return;
    }
    (async () => {
      try {
        const res = await getToolsStatus(selectedBatch);
        setToolsStatus(res.data);
      } catch {
        setToolsStatus(null);
      }
    })();
  }, [selectedBatch]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await syncAllBatches();
      await fetchBatches();
    } finally {
      setSyncing(false);
    }
  };

  const isCompleted = (outputFolder: string): boolean => {
    if (!toolsStatus) return false;
    return (toolsStatus as unknown as Record<string, boolean>)[outputFolder] ?? false;
  };

  const filteredBatches = batches.filter((b) =>
    b.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-gray-950 text-slate-200">
      <DashboardHeader />

      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <Link
                href="/processing"
                className="text-slate-400 hover:text-teal-400 transition-colors"
              >
                <ArrowLeft className="w-5 h-5" />
              </Link>
              <h1 className="text-2xl font-bold text-slate-100">Material Tools</h1>
            </div>
            <p className="text-sm text-slate-400 ml-8">
              Interactive tools for refining captures into production-quality tileable materials
            </p>
          </div>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-slate-700
              rounded-xl text-sm text-slate-300 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
            Sync
          </button>
        </div>

        {/* Two-column layout: select batch + pipeline tools */}
        <div className="grid grid-cols-[1fr_2fr] gap-8">
          {/* Batch selector */}
          <div>
            <h2 className="text-sm font-medium text-slate-400 mb-3">Select Batch</h2>
            <div className="relative mb-3">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Filter batches..."
                className="w-full pl-9 pr-3 py-2 bg-slate-800/50 border border-slate-700/50 rounded-xl
                  text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
              />
            </div>
            <div className="space-y-1 max-h-[60vh] overflow-y-auto pr-1">
              {loading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-5 h-5 text-teal-400 animate-spin" />
                </div>
              ) : filteredBatches.length === 0 ? (
                <p className="text-sm text-slate-500 py-4 text-center">No batches found</p>
              ) : (
                filteredBatches.map((batch) => (
                  <button
                    key={batch.name}
                    onClick={() => setSelectedBatch(batch.name)}
                    className={`w-full text-left px-3 py-2.5 rounded-xl text-sm transition-colors ${
                      selectedBatch === batch.name
                        ? 'bg-teal-500/15 text-teal-300 ring-1 ring-teal-500/40'
                        : 'text-slate-300 hover:bg-slate-800/50'
                    }`}
                  >
                    <div className="font-mono text-xs">{batch.name}</div>
                    <div className="text-[11px] text-slate-500 mt-0.5">
                      {batch.image_count} images · {batch.crop_status === 'completed' ? 'Cropped' :
                        batch.calibration_status === 'completed' ? 'Calibrated' : 'Raw'}
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>

          {/* Pipeline tools */}
          <div>
            <h2 className="text-sm font-medium text-slate-400 mb-3">
              {selectedBatch ? `Pipeline for ${selectedBatch}` : 'Select a batch first'}
            </h2>

            {/* Main pipeline chain */}
            <div className="space-y-1">
              {pipelineTools.map((tool, index) => {
                const Icon = tool.icon;
                const disabled = !selectedBatch;
                const completed = isCompleted(tool.outputFolder);
                const stepNum = index + 1;

                return (
                  <div key={tool.id}>
                    {/* Connector line between steps */}
                    {index > 0 && (
                      <div className="flex items-center ml-6 -my-1">
                        <div className={`w-px h-3 ${
                          isCompleted(pipelineTools[index - 1].outputFolder)
                            ? 'bg-teal-500/50'
                            : 'bg-slate-700/50'
                        }`} />
                      </div>
                    )}

                    <button
                      disabled={disabled}
                      onClick={() => {
                        if (selectedBatch) {
                          router.push(`/processing/tools/${tool.id}/${encodeURIComponent(selectedBatch)}`);
                        }
                      }}
                      className={`w-full text-left p-3 rounded-2xl border bg-gradient-to-br transition-all group
                        ${disabled
                          ? 'opacity-40 cursor-not-allowed border-slate-700/30 from-slate-800/30 to-slate-800/20'
                          : `${tool.color} hover:scale-[1.01] hover:shadow-lg cursor-pointer`
                        }`}
                    >
                      <div className="flex items-center gap-3">
                        {/* Step number / completion badge */}
                        <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0
                          ${completed
                            ? 'bg-teal-500 text-white'
                            : 'bg-slate-800 text-slate-400 ring-1 ring-slate-600'
                          }`}
                        >
                          {completed ? <Check className="w-3.5 h-3.5" /> : stepNum}
                        </div>

                        {/* Icon */}
                        <div className={`p-2 rounded-xl bg-slate-900/50 ${tool.iconColor}`}>
                          <Icon className="w-5 h-5" />
                        </div>

                        {/* Name & description */}
                        <div className="flex-1 min-w-0">
                          <h3 className="text-sm font-medium text-slate-200">{tool.name}</h3>
                          <p className="text-xs text-slate-400 leading-relaxed truncate">{tool.description}</p>
                        </div>

                        {/* Folder flow hint */}
                        <div className="hidden sm:flex items-center gap-1 text-[10px] text-slate-500 font-mono shrink-0">
                          <span>{tool.inputHint}</span>
                          <ChevronRight className="w-3 h-3" />
                          <span>{tool.outputHint}</span>
                        </div>

                        {/* Completion tag */}
                        {completed && (
                          <span className="px-2 py-0.5 rounded-full bg-teal-500/15 text-teal-400 text-[10px] font-medium shrink-0">
                            Done
                          </span>
                        )}
                      </div>
                    </button>
                  </div>
                );
              })}
            </div>

            {/* Separator */}
            <div className="flex items-center gap-3 mt-6 mb-3">
              <div className="h-px flex-1 bg-slate-700/50" />
              <span className="text-[10px] text-slate-500 uppercase tracking-wider">Utilities</span>
              <div className="h-px flex-1 bg-slate-700/50" />
            </div>

            {/* Utility tools */}
            <div className="grid grid-cols-2 gap-3">
              {utilityTools.map((tool) => {
                const Icon = tool.icon;
                const disabled = !selectedBatch;
                return (
                  <button
                    key={tool.id}
                    disabled={disabled}
                    onClick={() => {
                      if (selectedBatch) {
                        router.push(`/processing/tools/${tool.id}/${encodeURIComponent(selectedBatch)}`);
                      }
                    }}
                    className={`text-left p-3 rounded-2xl border bg-gradient-to-br transition-all
                      ${disabled
                        ? 'opacity-40 cursor-not-allowed border-slate-700/30 from-slate-800/30 to-slate-800/20'
                        : `${tool.color} hover:scale-[1.02] hover:shadow-lg cursor-pointer`
                      }`}
                  >
                    <div className="flex items-start gap-3">
                      <div className={`p-2 rounded-xl bg-slate-900/50 ${tool.iconColor}`}>
                        <Icon className="w-5 h-5" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-sm font-medium text-slate-200">{tool.name}</h3>
                          <span className="px-1.5 py-0.5 rounded bg-slate-700/50 text-[9px] text-slate-400 uppercase">
                            {tool.badge}
                          </span>
                        </div>
                        <p className="text-xs text-slate-400 mt-1 leading-relaxed">{tool.description}</p>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
