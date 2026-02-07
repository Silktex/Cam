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
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Video className="w-5 h-5 text-gray-700" />
          <h2 className="text-lg font-semibold text-gray-900">Live View</h2>
        </div>
        
        <div className="flex items-center gap-2">
          {isStreaming ? (
            <button
              onClick={stopStream}
              className="flex items-center gap-1 px-3 py-1 text-sm bg-red-100 text-red-700 rounded hover:bg-red-200 transition-colors"
            >
              <VideoOff className="w-4 h-4" />
              Stop
            </button>
          ) : (
            <button
              onClick={startStream}
              disabled={!isConnected}
              className="flex items-center gap-1 px-3 py-1 text-sm bg-green-100 text-green-700 rounded hover:bg-green-200 disabled:bg-gray-100 disabled:text-gray-400 transition-colors"
            >
              <Video className="w-4 h-4" />
              Start
            </button>
          )}
          
          <button
            onClick={refreshStream}
            disabled={!isConnected}
            className="p-1 text-gray-500 hover:text-gray-700 disabled:text-gray-300 transition-colors"
            title="Refresh stream"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="relative aspect-video bg-gray-900 rounded-lg overflow-hidden">
        {!isConnected ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-400">
            <VideoOff className="w-12 h-12 mb-2" />
            <span>Camera not connected</span>
          </div>
        ) : !isStreaming ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-400">
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

      <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
        <span>{model}</span>
        <span className={isStreaming ? 'text-green-600' : 'text-gray-400'}>
          {isStreaming ? '● Streaming' : '○ Stopped'}
        </span>
      </div>
    </div>
  );
}
