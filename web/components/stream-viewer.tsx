'use client';

import { useQuery } from '@tanstack/react-query';
import { getLiveViewUrl, stopLiveView, getCameraStatus, type CameraStatus } from '@/lib/api';
import { Video, VideoOff, RefreshCw } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';

export function StreamViewer() {
  const [streamSrc, setStreamSrc] = useState<string | null>(null);
  const [key, setKey] = useState(0);

  const { data: cameraStatus } = useQuery({
    queryKey: ['camera', 'status'],
    queryFn: () => getCameraStatus().then(res => res.data as CameraStatus),
    refetchInterval: 5000,
  });

  const isConnected = cameraStatus?.connected ?? false;
  const model = cameraStatus?.model || 'No camera';

  const startStream = useCallback(() => {
    setKey(k => k + 1);
    setStreamSrc(`${getLiveViewUrl()}?t=${Date.now()}`);
  }, []);

  const stopStream = async () => {
    setStreamSrc(null);
    try {
      await stopLiveView();
    } catch (e) {
      // ignore
    }
  };

  const refreshStream = () => {
    setKey(k => k + 1);
    setStreamSrc(`${getLiveViewUrl()}?t=${Date.now()}`);
  };

  // Listen for restart event from capture panel
  useEffect(() => {
    const handleRestart = () => {
      console.log('Restarting stream after capture...');
      if (isConnected) {
        startStream();
      }
    };
    window.addEventListener('restartStream', handleRestart);
    return () => window.removeEventListener('restartStream', handleRestart);
  }, [isConnected, startStream]);

  // Auto-start stream when connected (on mount or reconnect)
  useEffect(() => {
    if (isConnected && streamSrc === null) {
      startStream();
    }
  }, [isConnected]);

  const isStreaming = streamSrc !== null;

  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Video className="w-5 h-5 text-slate-700" />
          <h2 className="text-lg font-semibold text-slate-800">Live View</h2>
        </div>

        <div className="flex items-center gap-2">
          {isStreaming ? (
            <button
              onClick={stopStream}
              className="flex items-center gap-1 px-3 py-1 text-sm bg-red-50 text-red-700 rounded-xl hover:bg-red-100 transition-colors"
            >
              <VideoOff className="w-4 h-4" />
              Stop
            </button>
          ) : (
            <button
              onClick={startStream}
              disabled={!isConnected}
              className="flex items-center gap-1 px-3 py-1 text-sm bg-teal-50 text-teal-700 rounded-xl hover:bg-teal-100 disabled:bg-slate-100 disabled:text-slate-400 transition-colors"
            >
              <Video className="w-4 h-4" />
              Start
            </button>
          )}

          <button
            onClick={refreshStream}
            disabled={!isConnected}
            className="p-1 text-slate-500 hover:text-slate-700 disabled:text-slate-300 transition-colors"
            title="Refresh stream"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="relative aspect-video bg-slate-900 rounded-xl overflow-hidden">
        {!isConnected ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-400">
            <VideoOff className="w-12 h-12 mb-2" />
            <span>Camera not connected</span>
          </div>
        ) : !isStreaming ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-400">
            <Video className="w-12 h-12 mb-2" />
            <span>Click Start to begin streaming</span>
          </div>
        ) : (
          <img
            key={key}
            src={streamSrc}
            alt="Live view"
            className="w-full h-full object-contain"
          />
        )}
      </div>

      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        <span>{model}</span>
        <span className={isStreaming ? 'text-teal-600' : 'text-slate-400'}>
          {isStreaming ? '● Streaming' : '○ Stopped'}
        </span>
      </div>
    </div>
  );
}
