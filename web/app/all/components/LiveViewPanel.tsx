'use client';

import { useQuery } from '@tanstack/react-query';
import {
  getLiveViewUrl,
  stopLiveView,
  getCameraStatus,
  triggerAutofocus,
  type CameraStatus,
} from '@/lib/api';
import { useMutation } from '@tanstack/react-query';
import { Video, VideoOff, RefreshCw, Focus } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';

export default function LiveViewPanel() {
  const [streamSrc, setStreamSrc] = useState<string | null>(null);
  const [key, setKey] = useState(0);

  const { data: cameraStatus } = useQuery({
    queryKey: ['camera', 'status'],
    queryFn: () => getCameraStatus().then((res) => res.data as CameraStatus),
    refetchInterval: 5000,
  });

  const isConnected = cameraStatus?.connected ?? false;
  const model = cameraStatus?.model || 'No camera';

  const startStream = useCallback(() => {
    setKey((k) => k + 1);
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
    setKey((k) => k + 1);
    setStreamSrc(`${getLiveViewUrl()}?t=${Date.now()}`);
  };

  // Listen for restart event from capture panel
  useEffect(() => {
    const handleRestart = () => {
      if (isConnected) {
        startStream();
      }
    };
    window.addEventListener('restartStream', handleRestart);
    return () => window.removeEventListener('restartStream', handleRestart);
  }, [isConnected, startStream]);

  // Auto-start stream when connected
  useEffect(() => {
    if (isConnected && streamSrc === null) {
      startStream();
    }
  }, [isConnected]);

  const isStreaming = streamSrc !== null;

  const autofocusMutation = useMutation({
    mutationFn: () => triggerAutofocus(),
  });

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Video className="w-5 h-5 text-teal-400" />
          <h2 className="text-base font-semibold text-white">Live View</h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => autofocusMutation.mutate()}
            disabled={!isConnected || autofocusMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-slate-700 text-slate-200 rounded-lg hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-500 transition-colors"
            title="Trigger autofocus (half-shutter)"
          >
            <Focus className={`w-3.5 h-3.5 ${autofocusMutation.isPending ? 'animate-pulse' : ''}`} />
            Focus
          </button>
          {isStreaming ? (
            <button
              onClick={stopStream}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors"
            >
              <VideoOff className="w-3.5 h-3.5" />
              Stop
            </button>
          ) : (
            <button
              onClick={startStream}
              disabled={!isConnected}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-teal-600 text-white rounded-lg hover:bg-teal-500 disabled:bg-slate-700 disabled:text-slate-500 transition-colors"
            >
              <Video className="w-3.5 h-3.5" />
              Start
            </button>
          )}
          <button
            onClick={refreshStream}
            disabled={!isConnected}
            className="p-1.5 text-slate-400 hover:text-slate-200 disabled:text-slate-600 rounded-lg hover:bg-slate-800 transition-colors"
            title="Refresh stream"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="relative aspect-video bg-slate-950 rounded-xl overflow-hidden">
        {!isConnected ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-500">
            <VideoOff className="w-12 h-12 mb-2 opacity-50" />
            <span className="text-sm">Camera not connected</span>
          </div>
        ) : !isStreaming ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-500">
            <Video className="w-12 h-12 mb-2 opacity-50" />
            <span className="text-sm">Click Start to begin streaming</span>
          </div>
        ) : (
          <>
            <img
              key={key}
              src={streamSrc}
              alt="Live view"
              className="w-full h-full object-contain"
            />
            {/* Camera-style focus overlays */}
            <div className="absolute inset-0 pointer-events-none flex items-center justify-center">
              {/* Center circle */}
              <div className="w-[18%] aspect-square rounded-full border-2 border-red-500" />
              {/* Center focus square */}
              <div className="absolute w-[6%] aspect-square border-2 border-red-500" />
              {/* Crosshair lines */}
              <div className="absolute w-[2%] h-px bg-red-500" />
              <div className="absolute h-[3%] w-px bg-red-500" />
            </div>
            <div className="absolute top-3 left-3 flex items-center gap-1.5 px-2 py-1 bg-slate-900/80 backdrop-blur-sm rounded-md">
              <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
              <span className="text-xs text-teal-400 font-medium">
                Live streaming...
              </span>
            </div>
          </>
        )}
      </div>

      <div className="mt-2 flex items-center justify-between text-xs">
        <span className="text-slate-500">{model}</span>
        <span
          className={`flex items-center gap-1 ${
            isStreaming ? 'text-teal-400' : 'text-slate-500'
          }`}
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              isStreaming ? 'bg-teal-400' : 'bg-slate-600'
            }`}
          />
          {isStreaming ? 'Streaming' : 'Stopped'}
        </span>
      </div>
    </div>
  );
}
