'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getCameraStatus,
  connectCamera,
  disconnectCamera,
  troubleshootCamera,
  type CameraStatus,
} from '@/lib/api';
import { Camera, Power, Settings, Loader2, Wrench } from 'lucide-react';
import { useState } from 'react';

export default function DashboardHeader() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);

  const { data: status } = useQuery({
    queryKey: ['camera', 'status'],
    queryFn: () => getCameraStatus().then((res) => res.data as CameraStatus),
    refetchInterval: 5000,
  });

  const connectMutation = useMutation({
    mutationFn: connectCamera,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['camera'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
    },
    onError: (error: any) => {
      setMessage(error.response?.data?.detail || 'Connection failed');
      setTimeout(() => setMessage(null), 4000);
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: disconnectCamera,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['camera'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
    },
  });

  const troubleshootMutation = useMutation({
    mutationFn: troubleshootCamera,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['camera'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
      setMessage(res.data.message);
      setTimeout(() => setMessage(null), 4000);
    },
  });

  const isConnected = status?.connected ?? false;
  const model = status?.model || 'No camera detected';
  const isPending =
    connectMutation.isPending ||
    disconnectMutation.isPending ||
    troubleshootMutation.isPending;

  return (
    <div>
      {/* Row 1: Title + connection status */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <Camera className="w-6 h-6 text-teal-400" />
          <div>
            <h1 className="text-lg font-semibold text-white">Camera Control</h1>
            <p className="text-xs text-slate-400">{model} via gphoto2</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`w-2.5 h-2.5 rounded-full ${
              isConnected ? 'bg-teal-400 animate-pulse' : 'bg-red-400'
            }`}
          />
          <span
            className={`text-sm font-medium ${
              isConnected ? 'text-teal-400' : 'text-red-400'
            }`}
          >
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
      </div>

      {/* Row 2: Camera bar */}
      <div className="flex items-center justify-between px-6 py-2.5 bg-slate-900/80 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <Camera className="w-4 h-4 text-slate-400" />
          <span className="text-sm text-slate-300">Camera</span>
          <span className="text-sm text-slate-500">{model}</span>
          {message && (
            <span className="text-xs text-yellow-400 ml-2">{message}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() =>
              isConnected
                ? disconnectMutation.mutate()
                : connectMutation.mutate()
            }
            disabled={isPending}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 ${
              isConnected
                ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
                : 'bg-teal-600 text-white hover:bg-teal-500'
            }`}
          >
            {connectMutation.isPending || disconnectMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Power className="w-3.5 h-3.5" />
            )}
            {isConnected ? 'Disconnect' : 'Connect'}
          </button>
          <button
            onClick={() => troubleshootMutation.mutate()}
            disabled={isPending}
            title="Troubleshoot camera connection"
            className="p-1.5 text-slate-400 hover:text-slate-200 rounded-lg hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            {troubleshootMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Wrench className="w-4 h-4" />
            )}
          </button>
          <button
            className="p-1.5 text-slate-400 hover:text-slate-200 rounded-lg hover:bg-slate-800 transition-colors"
            title="Settings"
          >
            <Settings className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
