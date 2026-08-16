'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import {
  Camera,
  Play,
  Square,
  Loader2,
  CheckCircle,
  AlertCircle,
  Sun,
} from 'lucide-react';
import { api } from '@/lib/api';
import { getWebSocketBaseUrl, getApiBaseUrl } from '@/lib/urlHelpers';

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

interface ProfileInfo {
  name: string;
  created_at?: string;
}

export default function BatchCaptureForm() {
  const defaultFolder = `batch_${Date.now()}`;
  const [folder, setFolder] = useState(defaultFolder);
  const [prefix, setPrefix] = useState(defaultFolder);
  const [prefixTouched, setPrefixTouched] = useState(false);
  const [lightDelay, setLightDelay] = useState(0.5);
  const [profile, setProfile] = useState('CHECKER-17FEB.npz');
  const [profiles, setProfiles] = useState<ProfileInfo[]>([]);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState<BatchProgress | null>(null);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [toast, setToast] = useState<string | null>(null);

  // Next batch prep (editable while current is running)
  const [nextFolder, setNextFolder] = useState('');
  const [nextPrefix, setNextPrefix] = useState('');
  const [nextPrefixTouched, setNextPrefixTouched] = useState(false);
  const [nextDelay, setNextDelay] = useState(0.5);
  const [topLightAfter, setTopLightAfter] = useState(true);

  const wsRef = useRef<WebSocket | null>(null);

  const startBatchCapture = useCallback(() => {
    setIsRunning(true);
    setProgress(null);
    setResult(null);
    setError(null);

    // Pre-fill next batch with prefix from current folder (e.g. "MALVERN-GREEN" → "MALVERN-")
    const dashIdx = folder.lastIndexOf('-');
    const nextPre = dashIdx > 0 ? folder.substring(0, dashIdx + 1) : '';
    setNextFolder(nextPre);
    setNextPrefix(nextPre);
    setNextPrefixTouched(false);

    const wsUrl = getWebSocketBaseUrl();
    const ws = new WebSocket(`${wsUrl}/api/batch/ws`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          action: 'start',
          folder,
          prefix,
          light_stabilize_delay: lightDelay,
          profile,
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
          // Turn on top light for next sample placement
          if (topLightAfter) {
            api.post('/api/lights/0', { on: true, brightness: 100 }).catch(() => {});
          }
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
  }, [folder, prefix, lightDelay, profile, topLightAfter]);

  const cancelBatchCapture = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'cancel' }));
    }
  }, []);

  // Fetch available calibration profiles
  useEffect(() => {
    const apiUrl = getApiBaseUrl();
    fetch(`${apiUrl}/api/colorchecker/profiles`)
      .then(res => res.json())
      .then(data => {
        if (data.profiles && data.profiles.length > 0) {
          setProfiles(data.profiles);
        }
      })
      .catch(err => console.error('Failed to fetch profiles:', err));
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
        if (!isRunning) {
          startBatchCapture();
        }
      }
    };
    window.addEventListener('keydown', handleSave);
    return () => window.removeEventListener('keydown', handleSave);
  });

  // When batch completes, apply next batch values so the config form shows pre-filled
  useEffect(() => {
    if (!result) return;
    const useNext = nextFolder.trim() !== '';
    const newFolder = useNext ? nextFolder.trim() : `batch_${Date.now()}`;
    const newPrefix = useNext && nextPrefix.trim() ? nextPrefix.trim() : newFolder;
    setFolder(newFolder);
    setPrefix(newPrefix);
    setPrefixTouched(useNext && nextPrefixTouched);
    if (useNext) setLightDelay(nextDelay);
    setNextFolder('');
    setNextPrefix('');
    setNextPrefixTouched(false);
    // Auto-dismiss the completion banner after 30s
    const timer = setTimeout(() => { setResult(null); setToast(null); }, 30000);
    return () => clearTimeout(timer);
  }, [result]); // eslint-disable-line react-hooks/exhaustive-deps

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
  if (!isRunning) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
        {/* Completion banner */}
        {result && (
          <div className={`mb-4 p-3 rounded-lg flex items-center gap-2 ${result.success ? 'bg-teal-500/10 border border-teal-500/30' : 'bg-red-500/10 border border-red-500/30'}`}>
            {result.success ? (
              <CheckCircle className="w-4 h-4 text-teal-400 flex-shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
            )}
            <div className="flex-1 min-w-0">
              <span className={`text-sm font-medium ${result.success ? 'text-teal-300' : 'text-red-300'}`}>
                {result.success
                  ? `${result.folder}: ${result.total_captures} captures in ${result.duration_seconds.toFixed(1)}s`
                  : `${result.folder}: completed with errors`}
              </span>
              {result.errors.length > 0 && (
                <p className="text-xs text-red-400 mt-0.5 truncate">{result.errors[0]}</p>
              )}
              {toast && (
                <p className="text-xs text-slate-400 mt-0.5">{toast}</p>
              )}
            </div>
            <button
              onClick={() => { setResult(null); setToast(null); }}
              className="text-xs text-slate-400 hover:text-white flex-shrink-0"
            >
              Dismiss
            </button>
          </div>
        )}

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

          <div className="flex gap-3">
            <div className="flex-1">
              <label className="block text-sm text-slate-400 mb-1">
                Light Delay (s)
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
            <div className="flex-1">
              <label className="block text-sm text-slate-400 mb-1">
                Calibration Profile
              </label>
              <select
                value={profile}
                onChange={(e) => setProfile(e.target.value)}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none"
              >
                {profiles.length === 0 && (
                  <option value="CHECKER-17FEB.npz">CHECKER-17FEB</option>
                )}
                {profiles.map((p) => (
                  <option key={p.name} value={p.name.endsWith('.npz') ? p.name : `${p.name}.npz`}>
                    {p.name.replace('.npz', '')}
                  </option>
                ))}
              </select>
            </div>
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

        {/* Next batch prep */}
        <div className="mt-4 pt-4 border-t border-slate-800">
          <p className="text-xs font-medium text-slate-400 mb-2">Prepare Next Batch</p>
          <div className="space-y-2">
            <input
              type="text"
              value={nextFolder}
              onChange={(e) => {
                setNextFolder(e.target.value);
                if (!nextPrefixTouched) setNextPrefix(e.target.value);
              }}
              className="w-full px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 text-xs focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none"
              placeholder="Next folder name"
            />
            <div className="flex gap-2">
              <input
                type="text"
                value={nextPrefix}
                onChange={(e) => { setNextPrefixTouched(true); setNextPrefix(e.target.value); }}
                className="flex-1 px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 text-xs focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none"
                placeholder="Prefix"
              />
              <input
                type="number"
                value={nextDelay}
                onChange={(e) => setNextDelay(parseFloat(e.target.value))}
                min={0.1}
                max={10}
                step={0.1}
                className="w-20 px-2 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-white text-xs focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none"
                title="Light delay (s)"
              />
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <button
                type="button"
                onClick={() => setTopLightAfter(!topLightAfter)}
                className={`w-8 h-4 rounded-full transition-colors relative ${topLightAfter ? 'bg-teal-600' : 'bg-slate-700'}`}
              >
                <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${topLightAfter ? 'left-4' : 'left-0.5'}`} />
              </button>
              <Sun className="w-3 h-3 text-slate-400" />
              <span className="text-xs text-slate-400">Top light on after capture</span>
            </label>
          </div>
        </div>
      </div>
    );
  }

  return null;
}
