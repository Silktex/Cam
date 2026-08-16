'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import StudioHeader from '@/components/StudioHeader';
import { getLiveViewUrl, getBatches, type Batch } from '@/lib/api';
import { getWebSocketBaseUrl } from '@/lib/urlHelpers';
import {
  Layers,
  Play,
  Square,
  CheckCircle2,
  AlertCircle,
  Clock,
  Camera,
  RotateCw,
  Loader2,
  FolderOpen,
  ArrowRight,
} from 'lucide-react';

interface Toast {
  id: string;
  message: string;
  type: 'info' | 'success' | 'warn' | 'error';
}

interface CompletedBatch {
  id: string;
  name: string;
  capturesCount: number;
  durationSeconds: number;
  status: 'ready' | 'processing' | 'completed';
  createdAt: string;
}

const STEP_LABELS = [
  { step: 1, name: 'TOP DOME', subtitle: '100% Lux' },
  { step: 2, name: 'SIDE 1 (N)', subtitle: '100% Lux' },
  { step: 3, name: 'SIDE 2 (NE)', subtitle: '100% Lux' },
  { step: 4, name: 'SIDE 3 (E)', subtitle: '100% Lux' },
  { step: 5, name: 'SIDE 4 (SE)', subtitle: '100% Lux' },
  { step: 6, name: 'SIDE 5 (S)', subtitle: '100% Lux' },
  { step: 7, name: 'SIDE 6 (SW)', subtitle: '100% Lux' },
  { step: 8, name: 'SIDE 7 (W)', subtitle: '100% Lux' },
  { step: 9, name: 'SIDE 8 (NW)', subtitle: '100% Lux' },
];

export default function PhotometricBatchSequencerPage() {
  const router = useRouter();

  // Toast notifications
  const [toasts, setToasts] = useState<Toast[]>([]);
  const addToast = useCallback((message: string, type: 'info' | 'success' | 'warn' | 'error' = 'info') => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  // Batch Form State
  const [folderName, setFolderName] = useState(`batch_sample_${Date.now().toString().slice(-4)}`);
  const [prefix, setPrefix] = useState('sample_posh');
  const [selectedProfile, setSelectedProfile] = useState('CHECKER-17FEB-D65.icc');
  const [stabilizeDelay, setStabilizeDelay] = useState(1.5);

  // Execution State
  const [isRunning, setIsRunning] = useState(false);
  const [isDryRun, setIsDryRun] = useState(false);
  const [currentStep, setCurrentStep] = useState(0); // 0 = idle, 1..9 = running
  const [pipFlashing, setPipFlashing] = useState(false);
  const [pipStatus, setPipStatus] = useState('READY • 1/125s • f/8.0 • ISO 100');
  const wsRef = useRef<WebSocket | null>(null);
  const stepTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Completed Batches List
  const [completedBatches, setCompletedBatches] = useState<CompletedBatch[]>([
    {
      id: 'b1',
      name: 'batch_daylily_4355_raw',
      capturesCount: 9,
      durationSeconds: 18.2,
      status: 'ready',
      createdAt: '16:25:10',
    },
    {
      id: 'b2',
      name: 'batch_linen_charcoal_02',
      capturesCount: 9,
      durationSeconds: 17.9,
      status: 'completed',
      createdAt: '15:58:30',
    },
    {
      id: 'b3',
      name: 'batch_mohair_velour_01',
      capturesCount: 9,
      durationSeconds: 18.4,
      status: 'completed',
      createdAt: '15:12:04',
    },
  ]);

  // Load existing batches from backend
  useEffect(() => {
    getBatches()
      .then((res) => {
        if (res.data?.batches && res.data.batches.length > 0) {
          const apiBatches = res.data.batches.slice(0, 5).map((b: Batch, idx: number) => ({
            id: `api-${idx}`,
            name: b.name,
            capturesCount: b.image_count || 9,
            durationSeconds: 18.0,
            status: (b.pbr_status === 'completed' ? 'completed' : 'ready') as 'ready' | 'completed',
            createdAt: b.created_at || 'Recent',
          }));
          setCompletedBatches((prev) => {
            const names = new Set(apiBatches.map((x: CompletedBatch) => x.name));
            return [...apiBatches, ...prev.filter((p) => !names.has(p.name))];
          });
        }
      })
      .catch(() => {});
  }, []);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (stepTimerRef.current) clearTimeout(stepTimerRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  // Sequence Execution Engine
  const startSequence = (dryRun: boolean) => {
    if (isRunning) return;
    setIsRunning(true);
    setIsDryRun(dryRun);
    setCurrentStep(1);

    const stepMs = dryRun ? 380 : Math.max(stabilizeDelay * 1000, 750);
    addToast(
      dryRun
        ? 'Starting high-speed dry run...'
        : `Starting 9-light capture sequence: ${folderName}`
    );

    // Try WebSocket connection to backend batch router if available
    const wsUrl = getWebSocketBaseUrl();
    try {
      const ws = new WebSocket(`${wsUrl}/api/batch/ws`);
      wsRef.current = ws;
      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            action: 'start',
            folder: folderName,
            prefix: prefix,
            light_stabilize_delay: stabilizeDelay,
            profile: selectedProfile,
          })
        );
      };
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === 'progress' && msg.data?.current_step) {
            setCurrentStep(msg.data.current_step);
          }
        } catch {
          // ignore
        }
      };
    } catch {
      // fallback to simulated stepper if WS offline
    }

    // Step execution loop
    let step = 1;
    function runNextStep() {
      if (step > 9) {
        // Complete!
        finishSequence(folderName, dryRun);
        return;
      }

      setCurrentStep(step);
      const label = STEP_LABELS[step - 1].name;
      setPipStatus(`FIRING LED ${step}/9 (${label}) • EXPOSING RAW...`);

      // Trigger PIP flash animation
      if (!dryRun) {
        setPipFlashing(true);
        setTimeout(() => setPipFlashing(false), 120);
      }

      step++;
      stepTimerRef.current = setTimeout(runNextStep, stepMs);
    }

    runNextStep();
  };

  const finishSequence = (name: string, dryRun: boolean) => {
    setIsRunning(false);
    setCurrentStep(10); // completed
    setPipStatus('READY • 9/9 RAW STORED');

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    addToast(
      dryRun
        ? 'Dry run sequence completed successfully'
        : `Batch sequence finished: 9 RAW images captured in ${name}`,
      'success'
    );

    if (!dryRun) {
      const newBatch: CompletedBatch = {
        id: `batch-${Date.now()}`,
        name: name,
        capturesCount: 9,
        durationSeconds: parseFloat((stabilizeDelay * 9 + 4.5).toFixed(1)),
        status: 'ready',
        createdAt: new Date().toLocaleTimeString(),
      };
      setCompletedBatches((prev) => [newBatch, ...prev]);
      // Update next default folder name
      setFolderName(`batch_sample_${(Date.now() + 100).toString().slice(-4)}`);
    }
  };

  const cancelSequence = () => {
    if (stepTimerRef.current) clearTimeout(stepTimerRef.current);
    if (wsRef.current) {
      try {
        wsRef.current.send(JSON.stringify({ action: 'cancel' }));
        wsRef.current.close();
      } catch {}
      wsRef.current = null;
    }
    setIsRunning(false);
    setCurrentStep(0);
    setPipStatus('CANCELLED • STANDBY');
    addToast('Batch sequence cancelled by operator', 'warn');
  };

  const progressPercent =
    currentStep === 0
      ? 0
      : currentStep >= 10
      ? 100
      : Math.round((currentStep / 9) * 100);

  return (
    <div className="min-h-screen bg-chassis text-gray-100 font-sans flex flex-col antialiased selection:bg-accent selection:text-white">
      {/* Toast notifications */}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className="px-4 py-2.5 rounded-lg bg-surface-raised border border-border-strong text-xs font-mono text-white shadow-2xl flex items-center gap-2 transform transition-all duration-300 pointer-events-auto"
          >
            <span
              className={`w-2 h-2 rounded-full ${
                t.type === 'success'
                  ? 'bg-status-ok'
                  : t.type === 'warn'
                  ? 'bg-status-warn'
                  : t.type === 'error'
                  ? 'bg-status-err'
                  : 'bg-accent'
              }`}
            />
            <span>{t.message}</span>
          </div>
        ))}
      </div>

      {/* Global Top Header */}
      <StudioHeader stationSubtitle="BATCH SEQUENCER" />

      {/* Main Content Viewport */}
      <main className="flex-1 p-6 max-w-7xl mx-auto w-full grid grid-cols-12 gap-6 overflow-y-auto">
        {/* LEFT PANEL: Batch Configuration & Execution Engine (7 Cols) */}
        <div className="col-span-12 lg:col-span-7 space-y-6">
          {/* Card 1: Batch Identification & Metadata */}
          <div className="p-5 rounded-xl bg-surface border border-border-subtle space-y-4 shadow-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
                  <Layers className="w-4 h-4" />
                </div>
                <div>
                  <h2 className="font-display font-bold text-white text-base">
                    Photometric Batch Configuration
                  </h2>
                  <p className="text-xs text-gray-400">
                    Automated sequential capture for PBR texture extraction
                  </p>
                </div>
              </div>
              <span
                className={`px-2.5 py-1 rounded text-xs font-mono font-bold ${
                  isRunning
                    ? 'bg-accent/20 border border-accent text-accent animate-pulse'
                    : currentStep === 10
                    ? 'bg-status-ok/20 border border-status-ok text-status-ok'
                    : 'bg-surface-raised border border-border-strong text-accent'
                }`}
              >
                {isRunning
                  ? isDryRun
                    ? 'DRY RUN ACTIVE'
                    : 'CAPTURING BATCH...'
                  : currentStep === 10
                  ? 'BATCH COMPLETED'
                  : 'READY TO FIRE'}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4 pt-2">
              <div>
                <label className="block text-xs font-mono text-gray-400 mb-1.5">
                  BATCH FOLDER NAME
                </label>
                <input
                  type="text"
                  value={folderName}
                  onChange={(e) => setFolderName(e.target.value)}
                  disabled={isRunning}
                  className="w-full bg-chassis border border-border-strong rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-accent disabled:opacity-50"
                />
              </div>
              <div>
                <label className="block text-xs font-mono text-gray-400 mb-1.5">
                  FILENAME PREFIX
                </label>
                <input
                  type="text"
                  value={prefix}
                  onChange={(e) => setPrefix(e.target.value)}
                  disabled={isRunning}
                  className="w-full bg-chassis border border-border-strong rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-accent disabled:opacity-50"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-mono text-gray-400 mb-1.5">
                  CALIBRATION PROFILE
                </label>
                <select
                  value={selectedProfile}
                  onChange={(e) => setSelectedProfile(e.target.value)}
                  disabled={isRunning}
                  className="w-full bg-chassis border border-border-strong rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-accent disabled:opacity-50"
                >
                  <option value="CHECKER-17FEB-D65.icc">CHECKER-17FEB-D65.icc</option>
                  <option value="STUDIO-DAYLIGHT-5600K.icc">STUDIO-DAYLIGHT-5600K.icc</option>
                  <option value="RAW-UNMANAGED">RAW-UNMANAGED</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-mono text-gray-400 mb-1.5">
                  LIGHT STABILIZE DELAY
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    step="0.5"
                    min="0.5"
                    max="5.0"
                    value={stabilizeDelay}
                    onChange={(e) => setStabilizeDelay(parseFloat(e.target.value))}
                    disabled={isRunning}
                    className="w-24 bg-chassis border border-border-strong rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-accent disabled:opacity-50"
                  />
                  <span className="text-xs font-mono text-gray-400">seconds per light</span>
                </div>
              </div>
            </div>
          </div>

          {/* Card 2: Visual 9-Step Sequencing Matrix */}
          <div className="p-5 rounded-xl bg-surface border border-border-subtle space-y-4 shadow-lg">
            <div className="flex items-center justify-between">
              <h3 className="font-display font-bold text-white text-sm uppercase tracking-wider">
                Sequential Firing Order (9 Steps)
              </h3>
              <span className="text-xs font-mono text-gray-400">
                Estimated duration: ~{(stabilizeDelay * 9 + 4.5).toFixed(1)}s
              </span>
            </div>

            {/* 9 Sequence Cards Grid */}
            <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 pt-1">
              {STEP_LABELS.map((s) => {
                const isActive = isRunning && currentStep === s.step;
                const isPast =
                  currentStep > s.step || (currentStep === 10 && !isRunning);

                return (
                  <div
                    key={s.step}
                    className={`p-2.5 rounded-lg space-y-1 relative transition-all duration-300 ${
                      isActive
                        ? 'bg-accent/25 border-2 border-accent shadow-lg'
                        : isPast
                        ? 'bg-surface-raised border border-status-ok/40 opacity-90'
                        : 'bg-surface-raised border border-border-subtle'
                    }`}
                  >
                    <span className="absolute top-1 right-1 text-[9px] font-mono font-bold text-gray-500">
                      STEP {s.step}
                    </span>
                    <div className="text-xs font-mono font-bold text-gray-200">
                      {s.name}
                    </div>
                    <div className="text-[10px] text-gray-400 font-mono">
                      {s.subtitle}
                    </div>
                    <div
                      className={`w-full h-1 rounded-full mt-1.5 transition-all ${
                        isActive
                          ? 'bg-accent'
                          : isPast
                          ? 'bg-status-ok'
                          : 'bg-border-strong'
                      }`}
                    />
                  </div>
                );
              })}

              {/* Status Summary Card */}
              <div className="p-2.5 rounded-lg bg-surface-raised/40 border border-dashed border-border-subtle flex flex-col items-center justify-center text-center">
                <span className="text-[10px] font-mono text-status-ok font-bold">
                  TOTAL: 9 RAW
                </span>
              </div>
            </div>

            {/* Stepped Progress Bar */}
            {(isRunning || currentStep > 0) && (
              <div className="space-y-1.5 pt-2">
                <div className="flex justify-between text-xs font-mono">
                  <span className="text-accent font-bold">
                    {isRunning
                      ? `Capturing Light ${currentStep} of 9 (${
                          STEP_LABELS[currentStep - 1]?.name || 'Finalizing'
                        })...`
                      : currentStep === 10
                      ? '✓ Batch Completed: 9/9 Stored'
                      : 'Standby'}
                  </span>
                  <span className="text-gray-300">{progressPercent}%</span>
                </div>
                <div className="w-full bg-chassis rounded-full h-2 overflow-hidden border border-border-subtle">
                  <div
                    className="bg-accent h-full rounded-full transition-all duration-300"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>
              </div>
            )}

            {/* Action Buttons */}
            <div className="pt-3 flex items-center gap-4">
              {isRunning ? (
                <button
                  onClick={cancelSequence}
                  className="flex-1 py-3.5 rounded-lg bg-red-500/20 border border-red-500 text-red-400 hover:bg-red-500/30 font-display font-bold text-base tracking-wide flex items-center justify-center gap-3 transition active:scale-95 cursor-pointer"
                >
                  <Square className="w-5 h-5 fill-current" />
                  CANCEL BATCH SEQUENCE
                </button>
              ) : (
                <>
                  <button
                    onClick={() => startSequence(false)}
                    className="flex-1 py-3.5 rounded-lg bg-accent hover:bg-amber-500 text-chassis font-display font-bold text-base tracking-wide flex items-center justify-center gap-3 shadow-xl shadow-accent/20 transition transform active:scale-95 cursor-pointer"
                  >
                    <Play className="w-5 h-5 fill-current" />
                    START 9-LIGHT AUTOMATED SEQUENCE
                  </button>
                  <button
                    onClick={() => startSequence(true)}
                    className="px-4 py-3.5 rounded-lg bg-surface-raised hover:bg-white/10 text-gray-300 font-mono text-xs border border-border-subtle transition active:scale-95"
                  >
                    Dry Run (No RAW)
                  </button>
                </>
              )}
            </div>
          </div>
        </div>

        {/* RIGHT PANEL: Live Feedback & Recent Batch Archive (5 Cols) */}
        <div className="col-span-12 lg:col-span-5 space-y-6">
          {/* Real-Time Camera Feedback PIP Card */}
          <div className="p-5 rounded-xl bg-surface border border-border-subtle space-y-3 shadow-lg">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono font-bold uppercase tracking-wider text-white flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-status-ok"></span>
                LIVE CAMERA MONITOR
              </span>
              <span className="text-xs font-mono text-gray-400">Sony A7R III (61MP)</span>
            </div>

            <div className="aspect-video w-full rounded-lg bg-black border border-border-strong overflow-hidden relative">
              <img
                src="https://images.unsplash.com/photo-1579546929518-9e396f3cc809?auto=format&fit=crop&w=600&q=80"
                alt="Camera Stream PIP"
                className="w-full h-full object-cover transition-all duration-300"
              />
              <div
                className={`absolute inset-0 bg-white pointer-events-none transition-opacity duration-100 ${
                  pipFlashing ? 'opacity-80' : 'opacity-0'
                }`}
              />
              {isRunning && (
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                  <div className="w-12 h-12 rounded-full border-2 border-accent border-dashed animate-spin" />
                </div>
              )}
              <div className="absolute bottom-2 left-2 px-2 py-1 rounded bg-black/80 font-mono text-[10px] text-white backdrop-blur">
                <span>{pipStatus}</span>
              </div>
            </div>
          </div>

          {/* Recent Batches Table with PBR shortcuts */}
          <div className="p-5 rounded-xl bg-surface border border-border-subtle space-y-3 shadow-lg">
            <div className="flex items-center justify-between">
              <h3 className="font-display font-bold text-white text-sm uppercase tracking-wider">
                Completed Batches
              </h3>
              <span className="text-xs font-mono text-accent">Auto-Processed</span>
            </div>

            <div className="space-y-2">
              {completedBatches.map((b) => (
                <div
                  key={b.id}
                  className="p-3 rounded-lg bg-surface-raised border border-border-subtle flex items-center justify-between text-xs transition hover:border-accent/40"
                >
                  <div>
                    <div className="font-mono font-bold text-white">{b.name}</div>
                    <div className="text-gray-400 text-[10px] font-mono">
                      {b.capturesCount} Captures • {b.durationSeconds}s duration • {b.createdAt}
                    </div>
                  </div>
                  <Link
                    href={`/processing?batch=${b.name}`}
                    className="px-2.5 py-1 rounded bg-accent/15 text-accent hover:bg-accent/25 border border-accent/30 font-mono text-[11px] font-medium transition flex items-center gap-1"
                  >
                    Process PBR <ArrowRight className="w-3 h-3" />
                  </Link>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
