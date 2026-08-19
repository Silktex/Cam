'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getCameraStatus, connectCamera, disconnectCamera, troubleshootCamera, type CameraStatus } from '@/lib/api';
import { Power, Wrench, Loader2 } from 'lucide-react';
import { useState } from 'react';

export function CameraControl() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);

  const { data: status } = useQuery({
    queryKey: ['camera', 'status'],
    queryFn: () => getCameraStatus().then(res => res.data as CameraStatus),
    refetchInterval: 5000, // Poll every 5s for faster sync
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
  const isPending = connectMutation.isPending || disconnectMutation.isPending || troubleshootMutation.isPending;

  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-4">
      <div className="flex gap-2">
        {/* Main connect/disconnect button */}
        <button
          onClick={() => isConnected ? disconnectMutation.mutate() : connectMutation.mutate()}
          disabled={isPending}
          className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl font-medium border-2 transition-colors disabled:opacity-50 text-white ${
            // Colored by current connection state: green while connected,
            // red while disconnected.
            isConnected
              ? 'bg-emerald-600 border-emerald-600 hover:bg-emerald-700 shadow-sm'
              : 'bg-red-600 border-red-600 hover:bg-red-700 shadow-sm'
          }`}
        >
          {(connectMutation.isPending || disconnectMutation.isPending) ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <Power className="w-5 h-5" />
          )}
          {isConnected ? 'Disconnect' : 'Connect'}
        </button>

        {/* Troubleshoot button - smaller */}
        <button
          onClick={() => troubleshootMutation.mutate()}
          disabled={isPending}
          title="Kill processes & reset"
          className="px-3 py-3 bg-slate-100 text-slate-600 rounded-xl hover:bg-slate-200 transition-colors disabled:opacity-50"
        >
          {troubleshootMutation.isPending ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <Wrench className="w-5 h-5" />
          )}
        </button>
      </div>

      {message && (
        <div className="mt-2 p-2 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-600">
          {message}
        </div>
      )}
    </div>
  );
}
