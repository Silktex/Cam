'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import {
  Camera,
  Play,
  Square,
  Loader2,
  CheckCircle,
  AlertCircle,
} from 'lucide-react';

interface CaptureInfo {
  step: number;
  light_id: number;
  light_name: string;
  suffix: string;
  filename: string;
  file_url: string;
  file_size: number;
  captured_at: string;
}

interface BatchProgress {
  current_step: number;
  total_steps: number;
  current_light: string;
  status: string;
  message: string;
  captures: string[];
}

interface BatchResult {
  success: boolean;
  folder: string;
  total_captures: number;
  captures: CaptureInfo[];
  started_at: string;
  completed_at: string;
  duration_seconds: number;
  errors: string[];
}

export default function BatchCaptureForm() {
  const defaultFolder = `batch_${Date.now()}`;
  const [folder, setFolder] = useState(defaultFolder);
  const [prefix, setPrefix] = useState(defaultFolder);
  const [prefixTouched, setPrefixTouched] = useState(false);
  const [lightDelay, setLightDelay] = useState(2.0);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState<BatchProgress | null>(null);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [toast, setToast] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  const startBatchCapture = useCallback(() => {
    setIsRunning(true);
    setProgress(null);
    setResult(null);
    setError(null);

    const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
    const ws = new WebSocket(`${wsUrl}/api/batch/ws`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          action: 'start',
          folder,
          prefix,
          light_stabilize_delay: lightDelay,
        })
      );
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      switch (data.type) {
        case 'started':
          setProgress({
            current_step: 0,
            total_steps: 9,
            current_light: 'Initializing...',
            status: 'starting',
            message: 'Starting batch capture...',
            captures: [],
          });
          break;
        case 'progress':
          setProgress(data.data);
          break;
        case 'complete':
          setResult(data.data);
          setIsRunning(false);
          setToast('Capture complete. Calibration & crop queued.');
          setTimeout(() => setToast(null), 5000);
          ws.close();
          break;
        case 'error':
          setError(data.data.message);
          setIsRunning(false);
          ws.close();
          break;
        case 'cancelled':
          setError('Batch capture cancelled');
          setIsRunning(false);
          ws.close();
          break;
      }
    };

    ws.onerror = () => {
      setError('WebSocket connection failed');
      setIsRunning(false);
    };

    ws.onclose = () => {
      wsRef.current = null;
    };
  }, [folder, prefix, lightDelay]);

  const cancelBatchCapture = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'cancel' }));
    }
  }, []);

  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  // Auto-focus folder input on mount
  useEffect(() => {
    folderInputRef.current?.focus();
    folderInputRef.current?.select();
  }, []);

  // Listen for global 'F' shortcut to re-focus folder input
  useEffect(() => {
    const handleFocus = () => {
      folderInputRef.current?.focus();
      folderInputRef.current?.select();
    };
    window.addEventListener('focusFolderInput', handleFocus);
    return () => window.removeEventListener('focusFolderInput', handleFocus);
  }, []);

  useEffect(() => {
    const handleSave = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        if (!isRunning && !result) {
          startBatchCapture();
        }
      }
    };
    window.addEventListener('keydown', handleSave);
    return () => window.removeEventListener('keydown', handleSave);
  });

  const handleFolderChange = (value: string) => {
    setFolder(value);
    if (!prefixTouched) {
      setPrefix(value);
    }
  };

  const handlePrefixChange = (value: string) => {
    setPrefixTouched(true);
    setPrefix(value);
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'waiting_light':
        return 'text-yellow-400';
      case 'capturing':
        return 'text-teal-400';
      case 'processing':
      case 'complete':
        return 'text-teal-500';
      case 'error':
        return 'text-red-500';
      default:
        return 'text-slate-400';
    }
  };

  // Config state
  if (!isRunning && !result) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
        <div className="flex items-center gap-2 mb-4">
          <Camera className="w-5 h-5 text-teal-400" />
          <h2 className="text-base font-semibold text-white">Batch Capture</h2>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-sm text-slate-400 mb-1">
              Folder Name
            </label>
            <input
              ref={folderInputRef}
              type="text"
              value={folder}
              onChange={(e) => handleFolderChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.currentTarget.blur();
                }
              }}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 text-sm focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none"
              placeholder="batch_001"
            />
          </div>

          <div>
            <label className="block text-sm text-slate-400 mb-1">
              Filename Prefix
            </label>
            <input
              type="text"
              value={prefix}
              onChange={(e) => handlePrefixChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.currentTarget.blur();
                }
              }}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 text-sm focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none"
              placeholder="capture"
            />
          </div>

          <div>
            <label className="block text-sm text-slate-400 mb-1">
              Light Stabilize Delay (s)
            </label>
            <input
              type="number"
              value={lightDelay}
              onChange={(e) => setLightDelay(parseFloat(e.target.value))}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.currentTarget.blur();
                }
              }}
              min={0.5}
              max={10}
              step={0.5}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none"
            />
          </div>

          <div className="bg-teal-500/10 border border-teal-500/20 rounded-lg p-3">
            <p className="text-xs text-teal-300">
              <strong>Sequence:</strong> Top Light → Side 1-8
            </p>
            <p className="text-xs text-slate-400 mt-0.5">
              {lightDelay}s delay per light. 9 total captures.
            </p>
          </div>

          <button
            onClick={startBatchCapture}
            className="w-full flex items-center justify-center gap-2 py-3 bg-teal-600 text-white rounded-xl font-medium hover:bg-teal-500 transition-colors"
          >
            <Play className="w-5 h-5" />
            Start Batch Capture
          </button>
        </div>

        {error && (
          <div className="mt-3 p-3 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
            <span className="text-sm text-red-300">{error}</span>
            <button
              onClick={() => setError(null)}
              className="ml-auto text-xs text-slate-400 hover:text-white"
            >
              Dismiss
            </button>
          </div>
        )}
      </div>
    );
  }

  // Running state
  if (isRunning && progress) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Camera className="w-5 h-5 text-teal-400" />
            <h2 className="text-base font-semibold text-white">
              Capturing...
            </h2>
          </div>
          <button
            onClick={cancelBatchCapture}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors"
          >
            <Square className="w-3.5 h-3.5" />
            Cancel
          </button>
        </div>

        {/* Light step pills */}
        <div className="flex justify-center gap-1.5 mb-4">
          {/* Top light */}
          <div
            className={`px-2 py-1 rounded-lg text-[10px] font-bold transition-all ${
              progress.current_step === 1
                ? 'bg-teal-500 text-slate-900 animate-pulse'
                : progress.current_step > 1
                  ? 'bg-teal-600 text-white'
                  : 'bg-slate-700 text-slate-400'
            }`}
          >
            Top
          </div>
          {/* Side lights */}
          {Array.from({ length: 8 }, (_, i) => {
            const step = i + 2;
            return (
              <div
                key={i}
                className={`w-7 py-1 rounded-lg text-[10px] font-bold text-center transition-all ${
                  progress.current_step === step
                    ? 'bg-teal-500 text-slate-900 animate-pulse'
                    : progress.current_step > step
                      ? 'bg-teal-600 text-white'
                      : 'bg-slate-700 text-slate-400'
                }`}
              >
                {i + 1}
              </div>
            );
          })}
        </div>

        {/* Progress bar */}
        <div className="h-1.5 bg-slate-700 rounded-full mb-3 overflow-hidden">
          <div
            className="h-full bg-teal-500 transition-all duration-500"
            style={{
              width: `${(progress.current_step / progress.total_steps) * 100}%`,
            }}
          />
        </div>

        {/* Status */}
        <div className="text-center">
          <p className={`text-sm font-medium ${getStatusColor(progress.status)}`}>
            {progress.status === 'waiting_light' && (
              <Loader2 className="w-4 h-4 inline mr-1 animate-spin" />
            )}
            {progress.status === 'capturing' && (
              <Camera className="w-4 h-4 inline mr-1 animate-pulse" />
            )}
            {progress.message}
          </p>
          <p className="text-xs text-slate-500 mt-1">
            Step {progress.current_step}/{progress.total_steps} •{' '}
            {progress.captures.length} captured
          </p>
        </div>
      </div>
    );
  }

  // Result state
  if (result) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
        <div className="flex items-center gap-3 mb-3">
          {result.success ? (
            <CheckCircle className="w-6 h-6 text-teal-400" />
          ) : (
            <AlertCircle className="w-6 h-6 text-red-400" />
          )}
          <div>
            <h2 className="text-base font-semibold text-white">
              {result.success
                ? 'Batch Complete!'
                : 'Finished with Errors'}
            </h2>
            <p className="text-xs text-slate-400">
              {result.total_captures} images in{' '}
              {result.duration_seconds.toFixed(1)}s
            </p>
          </div>
        </div>

        {result.errors.length > 0 && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-2 mb-3">
            <p className="text-xs text-red-300">
              {result.errors.join(', ')}
            </p>
          </div>
        )}

        <div className="flex gap-2">
          <button
            onClick={() => {
              const newFolder = `batch_${Date.now()}`;
              setResult(null);
              setToast(null);
              setFolder(newFolder);
              setPrefix(newFolder);
              setPrefixTouched(false);
            }}
            className="flex-1 py-2 text-sm font-medium bg-teal-600 text-white rounded-lg hover:bg-teal-500 transition-colors"
          >
            New Batch
          </button>
          <a
            href={`/gallery?folder=${result.folder}`}
            className="flex-1 py-2 text-sm font-medium text-center bg-slate-800 text-slate-300 rounded-lg hover:bg-slate-700 transition-colors"
          >
            View Gallery
          </a>
        </div>

        {/* Toast notification */}
        {toast && (
          <div className="mt-3 p-2.5 bg-teal-500/10 border border-teal-500/30 rounded-lg flex items-center gap-2">
            <CheckCircle className="w-3.5 h-3.5 text-teal-400 flex-shrink-0" />
            <span className="text-xs text-teal-300">{toast}</span>
          </div>
        )}
      </div>
    );
  }

  return null;
}
