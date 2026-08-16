'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getCameraStatus,
  connectCamera,
  disconnectCamera,
  troubleshootCamera,
  type CameraStatus,
} from '@/lib/api';
import { Camera, Power, Settings, Loader2, Wrench, Images, Workflow, Keyboard, Palette } from 'lucide-react';
import { useState, useEffect, useCallback, useRef } from 'react';
import { usePathname } from 'next/navigation';
import Link from 'next/link';
import ShortcutsModal from './ShortcutsModal';
import { setLiveViewSource } from '@/lib/api';

export default function DashboardHeader() {
  const queryClient = useQueryClient();
  const pathname = usePathname();
  const [message, setMessage] = useState<string | null>(null);
  const [showShortcuts, setShowShortcuts] = useState(false);

  const { data: status } = useQuery({
    queryKey: ['camera', 'status'],
    queryFn: () => getCameraStatus().then((res) => res.data as CameraStatus),
    refetchInterval: 5000,
  });

  const autoConnectAttempted = useRef(false);

  const connectMutation = useMutation({
    mutationFn: connectCamera,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['camera'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
      setLiveViewSource('hdmi').catch(() => {});
      setMessage(res.data.message || 'Camera connected');
      setTimeout(() => setMessage(null), 4000);
    },
    onError: (error: any) => {
      setMessage(error.response?.data?.detail || 'Connection failed');
      setTimeout(() => setMessage(null), 4000);
    },
  });

  // Automatically attempt camera connection and stream start when user lands on page
  useEffect(() => {
    if (status && !status.connected && !autoConnectAttempted.current && !connectMutation.isPending) {
      autoConnectAttempted.current = true;
      connectMutation.mutate();
    }
  }, [status, connectMutation]);

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

  const toggleShortcuts = useCallback(() => setShowShortcuts((v) => !v), []);

  const handleToggleConnection = useCallback(() => {
    if (isPending) return;
    if (isConnected) {
      disconnectMutation.mutate();
    } else {
      connectMutation.mutate();
    }
  }, [isConnected, isPending, connectMutation, disconnectMutation]);

  const handleTroubleshoot = useCallback(() => {
    if (isPending) return;
    troubleshootMutation.mutate();
  }, [isPending, troubleshootMutation]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      // Cmd/Ctrl shortcuts — work even in inputs
      if (e.metaKey || e.ctrlKey) {
        if (e.key === 'c') {
          e.preventDefault();
          handleToggleConnection();
          return;
        }
        return;
      }

      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (e.key === '?') {
        e.preventDefault();
        toggleShortcuts();
      }
    };

    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [toggleShortcuts, handleToggleConnection, handleTroubleshoot]);

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
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              pathname === '/' || pathname === '/all'
                ? 'bg-teal-600/20 text-teal-400'
                : 'text-slate-300 hover:text-white hover:bg-slate-800'
            }`}
          >
            <Camera className="w-4 h-4" />
            Dashboard
          </Link>
          <Link
            href="/gallery"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              pathname === '/gallery'
                ? 'bg-teal-600/20 text-teal-400'
                : 'text-slate-300 hover:text-white hover:bg-slate-800'
            }`}
          >
            <Images className="w-4 h-4" />
            Gallery
          </Link>
          <Link
            href="/processing"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              pathname?.startsWith('/processing')
                ? 'bg-violet-600/20 text-violet-400'
                : 'text-slate-300 hover:text-white hover:bg-slate-800'
            }`}
          >
            <Workflow className="w-4 h-4" />
            Processing
          </Link>
          <Link
            href="/image-processing"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              pathname?.startsWith('/image-processing')
                ? 'bg-teal-600/20 text-teal-400'
                : 'text-slate-300 hover:text-white hover:bg-slate-800'
            }`}
          >
            <Palette className="w-4 h-4" />
            Texturize
          </Link>
          <div className="w-px h-5 bg-slate-700" />
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
            onClick={handleToggleConnection}
            disabled={isPending}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 border ${
              isConnected
                ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40 hover:bg-red-500/20 hover:text-red-400 hover:border-red-500/40'
                : 'bg-red-500/20 text-red-400 border-red-500/40 hover:bg-emerald-500/20 hover:text-emerald-400 hover:border-emerald-500/40'
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
            onClick={handleTroubleshoot}
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
            onClick={toggleShortcuts}
            className="p-1.5 text-slate-400 hover:text-slate-200 rounded-lg hover:bg-slate-800 transition-colors"
            title="Keyboard Shortcuts (?)"
          >
            <Keyboard className="w-4 h-4" />
          </button>
          <button
            className="p-1.5 text-slate-400 hover:text-slate-200 rounded-lg hover:bg-slate-800 transition-colors"
            title="Settings"
          >
            <Settings className="w-4 h-4" />
          </button>
        </div>
      </div>

      <ShortcutsModal open={showShortcuts} onClose={() => setShowShortcuts(false)} />
    </div>
  );
}
