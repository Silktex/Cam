'use client';

import { useQuery } from '@tanstack/react-query';
import { getLiveViewStatus, stopLiveView, getCameraStatus, type CameraStatus, type LiveViewStatus } from '@/lib/api';
import { Video, VideoOff, RefreshCw, Layers } from 'lucide-react';
import { useState, useCallback } from 'react';
import { WebRTCStreamViewer } from './WebRTCStreamViewer';

export function StreamViewer() {
  const [streamSource, setStreamSource] = useState<'hdmi' | 'ptp'>('hdmi');
  const [isFrozen, setIsFrozen] = useState(false);

  const { data: cameraStatus } = useQuery({
    queryKey: ['camera', 'status'],
    queryFn: () => getCameraStatus().then((res) => res.data as CameraStatus),
    refetchInterval: 5000,
  });

  const { data: streamStatus } = useQuery({
    queryKey: ['liveview', 'status'],
    queryFn: () => getLiveViewStatus().then((res) => res.data as LiveViewStatus),
    refetchInterval: 5000,
  });

  const isConnected = cameraStatus?.connected ?? false;
  const model = cameraStatus?.model || 'Sony ILCE-7RM3';
  const deviceName = streamStatus?.device_name || 'MacroSilicon USB 3.0 HDMI Capture Card';

  const toggleFreeze = useCallback(() => {
    setIsFrozen((prev) => !prev);
  }, []);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 text-white">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Video className="w-5 h-5 text-teal-400" />
          <h2 className="text-base font-semibold text-white">Live Stream</h2>
          <span className="text-xs font-mono px-2 py-0.5 rounded bg-teal-950/60 border border-teal-800 text-teal-400">
            {streamSource === 'hdmi' ? '1080p H.264 (HDMI HW Encoded)' : 'PTP Direct'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setStreamSource(streamSource === 'hdmi' ? 'ptp' : 'hdmi')}
            className="flex items-center gap-1 px-2.5 py-1 text-xs font-mono bg-slate-800 hover:bg-slate-700 text-teal-300 rounded-lg border border-slate-700 transition-colors"
            title="Toggle Stream Source"
          >
            <Layers className="w-3.5 h-3.5" />
            <span>SRC: {streamSource.toUpperCase()}</span>
          </button>

          <button
            onClick={toggleFreeze}
            className={`px-2.5 py-1 text-xs font-mono rounded-lg border transition-colors ${
              isFrozen
                ? 'bg-blue-600/30 text-blue-300 border-blue-500/40 font-bold'
                : 'bg-slate-800 hover:bg-slate-700 text-slate-300 border-slate-700'
            }`}
          >
            {isFrozen ? 'FROZEN' : 'FREEZE'}
          </button>
        </div>
      </div>

      <div className="relative aspect-video bg-slate-950 rounded-xl overflow-hidden border border-slate-800">
        <WebRTCStreamViewer
          streamSource={streamSource}
          onSourceChange={setStreamSource}
          isFrozen={isFrozen}
        />
      </div>

      <div className="mt-2 flex items-center justify-between text-xs text-slate-400 font-mono">
        <span>{streamSource === 'hdmi' ? deviceName : model}</span>
        <span className="text-teal-400 flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
          WebRTC (Sub-100ms Latency)
        </span>
      </div>
    </div>
  );
}
