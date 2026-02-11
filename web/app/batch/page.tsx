'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import Link from 'next/link';
import { Camera, ArrowLeft, Play, Square, Loader2, CheckCircle, AlertCircle, Lightbulb } from 'lucide-react';

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

export default function BatchCapturePage() {
  const [folder, setFolder] = useState(`batch_${Date.now()}`);
  const [prefix, setPrefix] = useState('capture');
  const [lightDelay, setLightDelay] = useState(2.0);
  
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState<BatchProgress | null>(null);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  
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
      console.log('Batch capture WebSocket connected');
      ws.send(JSON.stringify({
        action: 'start',
        folder,
        prefix,
        light_stabilize_delay: lightDelay
      }));
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log('Batch WS message:', data);

      switch (data.type) {
        case 'started':
          setProgress({
            current_step: 0,
            total_steps: 9,
            current_light: 'Initializing...',
            status: 'starting',
            message: 'Starting batch capture...',
            captures: []
          });
          break;

        case 'progress':
          setProgress(data.data);
          break;

        case 'complete':
          setResult(data.data);
          setIsRunning(false);
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

    ws.onerror = (err) => {
      console.error('WebSocket error:', err);
      setError('WebSocket connection failed');
      setIsRunning(false);
    };

    ws.onclose = () => {
      console.log('Batch capture WebSocket closed');
      wsRef.current = null;
    };
  }, [folder, prefix, lightDelay]);

  const cancelBatchCapture = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'cancel' }));
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'waiting_light': return 'text-yellow-400';
      case 'capturing': return 'text-blue-400';
      case 'processing': return 'text-green-400';
      case 'complete': return 'text-green-500';
      case 'error': return 'text-red-500';
      default: return 'text-gray-400';
    }
  };

  const getLightIndicators = () => {
    const lights = [];
    // First indicator is Top Light (step 1)
    const topIsActive = progress && progress.current_step === 1;
    const topIsComplete = progress && progress.current_step > 1;
    lights.push(
      <div
        key="top"
        className={`w-10 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-all
          ${topIsActive ? 'bg-amber-500 text-black animate-pulse' : ''}
          ${topIsComplete ? 'bg-green-500 text-white' : ''}
          ${!topIsActive && !topIsComplete ? 'bg-gray-700 text-gray-400' : ''}
        `}
      >
        Top
      </div>
    );
    // Side lights 1-8 (steps 2-9)
    for (let i = 1; i <= 8; i++) {
      const step = i + 1; // Side 1 = step 2, Side 2 = step 3, etc.
      const isActive = progress && progress.current_step === step;
      const isComplete = progress && progress.current_step > step;
      lights.push(
        <div
          key={i}
          className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-all
            ${isActive ? 'bg-amber-500 text-black animate-pulse' : ''}
            ${isComplete ? 'bg-green-500 text-white' : ''}
            ${!isActive && !isComplete ? 'bg-gray-700 text-gray-400' : ''}
          `}
        >
          {i}
        </div>
      );
    }
    return lights;
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900 text-white p-6">
      {/* Header */}
      <header className="max-w-4xl mx-auto mb-8">
        <div className="flex items-center gap-4 mb-4">
          <Link
            href="/"
            className="p-2 rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="flex items-center gap-3">
            <Camera className="w-8 h-8 text-amber-400" />
            <div>
              <h1 className="text-2xl font-bold">Batch Capture</h1>
              <p className="text-sm text-gray-400">Multi-light sequential photography</p>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto space-y-6">
        {/* Configuration */}
        {!isRunning && !result && (
          <div className="bg-white/5 backdrop-blur rounded-xl p-6 border border-white/10">
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Lightbulb className="w-5 h-5 text-amber-400" />
              Capture Settings
            </h2>
            
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
              <div>
                <label className="block text-sm text-gray-400 mb-2">Folder Name</label>
                <input
                  type="text"
                  value={folder}
                  onChange={(e) => setFolder(e.target.value)}
                  className="w-full px-4 py-2 bg-white/10 rounded-lg border border-white/20 focus:border-amber-500 focus:outline-none"
                  placeholder="session_1"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-2">Filename Prefix</label>
                <input
                  type="text"
                  value={prefix}
                  onChange={(e) => setPrefix(e.target.value)}
                  className="w-full px-4 py-2 bg-white/10 rounded-lg border border-white/20 focus:border-amber-500 focus:outline-none"
                  placeholder="capture"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-2">Light Stabilize Delay (s)</label>
                <input
                  type="number"
                  value={lightDelay}
                  onChange={(e) => setLightDelay(parseFloat(e.target.value))}
                  min={0.5}
                  max={10}
                  step={0.5}
                  className="w-full px-4 py-2 bg-white/10 rounded-lg border border-white/20 focus:border-amber-500 focus:outline-none"
                />
              </div>
            </div>

            <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-4 mb-6">
              <p className="text-sm text-amber-200">
                <strong>Capture Sequence:</strong> Top Light → Side 1 → Side 2 → ... → Side 8
                <br />
                <span className="text-gray-400">Each light turns ON, captures, then OFF before the next. Wait {lightDelay}s per light. Total: 9 images.</span>
              </p>
            </div>

            <button
              onClick={startBatchCapture}
              className="w-full py-3 bg-gradient-to-r from-amber-500 to-orange-500 rounded-lg font-semibold
                hover:from-amber-400 hover:to-orange-400 transition-all flex items-center justify-center gap-2"
            >
              <Play className="w-5 h-5" />
              Start Batch Capture
            </button>
          </div>
        )}

        {/* Progress */}
        {isRunning && progress && (
          <div className="bg-white/5 backdrop-blur rounded-xl p-6 border border-white/10">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold">Capturing...</h2>
              <button
                onClick={cancelBatchCapture}
                className="px-4 py-2 bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors flex items-center gap-2"
              >
                <Square className="w-4 h-4" />
                Cancel
              </button>
            </div>

            {/* Light indicators */}
            <div className="flex justify-center gap-3 mb-6">
              {getLightIndicators()}
            </div>

            {/* Progress bar */}
            <div className="h-2 bg-gray-700 rounded-full mb-4 overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-amber-500 to-orange-500 transition-all duration-500"
                style={{ width: `${(progress.current_step / progress.total_steps) * 100}%` }}
              />
            </div>

            {/* Status */}
            <div className="text-center">
              <p className={`text-lg font-medium ${getStatusColor(progress.status)}`}>
                {progress.status === 'waiting_light' && <Loader2 className="w-5 h-5 inline mr-2 animate-spin" />}
                {progress.status === 'capturing' && <Camera className="w-5 h-5 inline mr-2 animate-pulse" />}
                {progress.message}
              </p>
              <p className="text-sm text-gray-400 mt-2">
                Step {progress.current_step} of {progress.total_steps} • {progress.captures.length} captured
              </p>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-6 flex items-center gap-4">
            <AlertCircle className="w-8 h-8 text-red-500 flex-shrink-0" />
            <div>
              <h3 className="font-semibold text-red-400">Error</h3>
              <p className="text-gray-300">{error}</p>
            </div>
            <button
              onClick={() => { setError(null); setResult(null); }}
              className="ml-auto px-4 py-2 bg-white/10 rounded-lg hover:bg-white/20"
            >
              Try Again
            </button>
          </div>
        )}

        {/* Result */}
        {result && (
          <div className="space-y-6">
            <div className={`rounded-xl p-6 border ${result.success ? 'bg-green-500/10 border-green-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
              <div className="flex items-center gap-4 mb-4">
                {result.success ? (
                  <CheckCircle className="w-10 h-10 text-green-500" />
                ) : (
                  <AlertCircle className="w-10 h-10 text-red-500" />
                )}
                <div>
                  <h2 className="text-xl font-bold">
                    {result.success ? 'Batch Capture Complete!' : 'Batch Capture Finished with Errors'}
                  </h2>
                  <p className="text-gray-400">
                    {result.total_captures} images captured in {result.duration_seconds.toFixed(1)} seconds
                  </p>
                </div>
              </div>

              {result.errors.length > 0 && (
                <div className="bg-red-500/20 rounded-lg p-4 mb-4">
                  <p className="font-semibold text-red-400 mb-2">Errors:</p>
                  <ul className="list-disc list-inside text-sm text-gray-300">
                    {result.errors.map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="flex gap-3">
                <button
                  onClick={() => { setResult(null); setFolder(`batch_${Date.now()}`); }}
                  className="px-6 py-2 bg-amber-500 text-black rounded-lg font-semibold hover:bg-amber-400"
                >
                  New Batch
                </button>
                <Link
                  href={`/gallery?folder=${result.folder}`}
                  className="px-6 py-2 bg-white/10 rounded-lg hover:bg-white/20"
                >
                  View in Gallery
                </Link>
              </div>
            </div>

            {/* Captured images grid */}
            <div className="bg-white/5 backdrop-blur rounded-xl p-6 border border-white/10">
              <h3 className="text-lg font-semibold mb-4">Captured Images</h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {result.captures.map((capture, i) => (
                  <div key={i} className="bg-white/5 rounded-lg p-3">
                    <div className="aspect-square bg-gray-800 rounded-lg mb-2 flex items-center justify-center">
                      <Camera className="w-8 h-8 text-gray-600" />
                    </div>
                    <p className="text-xs text-gray-400 truncate">{capture.filename}</p>
                    <p className="text-xs text-amber-400">{capture.light_name}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
