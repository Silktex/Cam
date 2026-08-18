'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  connectCamera,
  disconnectCamera,
  troubleshootCamera,
  setLiveViewSource,
} from '@/lib/api';
import { useLightsWebSocket } from '@/hooks/useLightsWebSocket';
import { useCameraWebSocket } from '@/hooks/useCameraWebSocket';
import { Power, Loader2, RefreshCw, Keyboard } from 'lucide-react';
import { useState, useEffect, useCallback, useRef } from 'react';
import { usePathname } from 'next/navigation';
import Link from 'next/link';
import ShortcutsModal from '@/app/all/components/ShortcutsModal';

interface StudioHeaderProps {
  stationSubtitle?: string;
}

export default function StudioHeader({ stationSubtitle = 'STUDIO WORKBENCH' }: StudioHeaderProps) {
  const queryClient = useQueryClient();
  const pathname = usePathname();
  const [message, setMessage] = useState<string | null>(null);
  const [showShortcuts, setShowShortcuts] = useState(false);

  // Pushed by the backend over /api/ws/events instead of polled (#3).
  const { status, lastError } = useCameraWebSocket();

  const autoConnectAttempted = useRef(false);

  // Surface worker-recovery errors (e.g. #9's stall watchdog resetting a
  // wedged camera) so the user knows to reconnect instead of silence.
  useEffect(() => {
    if (!lastError) return;
    setMessage(lastError);
    const timer = setTimeout(() => setMessage(null), 6000);
    return () => clearTimeout(timer);
  }, [lastError]);

  const { lights, connected: esp32Connected } = useLightsWebSocket();

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
      setMessage('Camera disconnected');
      setTimeout(() => setMessage(null), 4000);
    },
  });

  const troubleshootMutation = useMutation({
    mutationFn: troubleshootCamera,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['camera'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
      setMessage(res.data.message || 'PTP re-detected successfully');
      setTimeout(() => setMessage(null), 4000);
    },
    onError: (error: any) => {
      setMessage(error.response?.data?.detail || 'Re-detect failed');
      setTimeout(() => setMessage(null), 4000);
    },
  });

  const isConnected = status?.connected ?? false;
  const model = status?.model || 'SONY A7R III';
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
  }, [toggleShortcuts, handleToggleConnection]);

  const activeLightsCount = lights.filter((l) => l.on).length;

  const navStations = [
    { href: '/', label: '1. Capture Studio', match: ['/', '/capture'] },
    { href: '/batch', label: '2. Batch Sequencer', match: ['/batch'] },
    { href: '/calibration', label: '3. Color Calibration', match: ['/calibration', '/color-calibration'] },
    { href: '/processing', label: '4. PBR Synthesis', match: ['/processing', '/pbr', '/image-processing'] },
    { href: '/gallery', label: '5. Lightbox Gallery', match: ['/gallery'] },
  ];

  return (
    <header className="h-14 border-b border-border-subtle bg-surface/90 backdrop-blur px-5 flex items-center justify-between shrink-0 sticky top-0 z-40">
      <div className="flex items-center gap-4">
        {/* Brand & Badge */}
        <Link href="/" className="flex items-center gap-2.5 group">
          <div className="w-3 h-3 rounded-full bg-accent animate-pulse"></div>
          <span className="font-display font-bold text-lg tracking-tight text-white group-hover:text-accent transition-colors">
            OPTIX<span className="text-accent">.RIG</span>
          </span>
          <span className="text-xs font-mono px-2 py-0.5 rounded bg-surface-raised border border-border-subtle text-gray-400">
            {stationSubtitle}
          </span>
        </Link>
        <div className="h-4 w-px bg-border-subtle"></div>

        {/* 5-Station Navigation Links */}
        <nav className="flex items-center gap-1">
          {navStations.map((st) => {
            const isActive = st.match.some((m) =>
              m === '/' ? pathname === '/' : pathname?.startsWith(m)
            );
            return (
              <Link
                key={st.href}
                href={st.href}
                className={`px-3 py-1 rounded text-xs transition flex items-center gap-1.5 ${
                  isActive
                    ? 'bg-accent/15 text-accent font-medium border border-accent/30 shadow-sm'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-surface-raised border border-transparent'
                }`}
              >
                {isActive && <span className="w-1.5 h-1.5 rounded-full bg-accent"></span>}
                {st.label}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Hardware Telemetry & Quick Action Badges */}
      <div className="flex items-center gap-3">
        {message && (
          <span className="text-xs font-mono text-accent bg-accent/10 px-2 py-0.5 rounded border border-accent/20 animate-pulse">
            {message}
          </span>
        )}

        {/* Camera Status Pod */}
        <div className="flex items-center gap-2 px-2.5 py-1 rounded bg-surface-raised border border-border-subtle text-xs font-mono">
          <span
            className={`w-2 h-2 rounded-full ${
              isConnected ? 'bg-status-ok animate-pulse' : 'bg-status-err'
            }`}
          />
          <span className="text-gray-300 font-semibold">{model}</span>
          <span className="text-gray-500">•</span>
          <span className="text-gray-400">61.0 MP</span>
          <button
            onClick={handleToggleConnection}
            disabled={isPending}
            title={isConnected ? 'Disconnect Camera (Ctrl+C)' : 'Connect Camera (Ctrl+C)'}
            className={`ml-1 px-2 py-0.5 rounded transition flex items-center gap-1 border-2 font-bold text-[11px] ${
              // Colored by current connection state: green while connected,
              // red while disconnected.
              isConnected
                ? 'bg-status-ok/25 text-status-ok border-status-ok hover:bg-status-ok/35'
                : 'bg-status-err/25 text-status-err border-status-err hover:bg-status-err/35'
            }`}
          >
            {connectMutation.isPending || disconnectMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Power className="w-3.5 h-3.5" />
            )}
            <span>{isConnected ? 'Disconnect' : 'Connect'}</span>
          </button>
        </div>

        {/* ESP32 Rig Status Pod */}
        <div className="flex items-center gap-2 px-2.5 py-1 rounded bg-surface-raised border border-border-subtle text-xs font-mono">
          <span
            className={`w-2 h-2 rounded-full ${
              esp32Connected ? 'bg-status-ok' : 'bg-status-warn'
            }`}
          />
          <span className="text-gray-300">ESP32 RIG</span>
          <span className="text-accent font-bold">
            {activeLightsCount}/9 LED
          </span>
        </div>

        {/* Non-destructive Re-Detect */}
        <button
          onClick={handleTroubleshoot}
          disabled={isPending}
          title="Non-destructive PTP recovery & bus rescan"
          className="px-3 py-1 rounded bg-surface-raised hover:bg-white/10 text-xs font-mono text-gray-300 border border-border-subtle transition flex items-center gap-1.5 active:scale-95 disabled:opacity-50"
        >
          {troubleshootMutation.isPending ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin text-accent" />
          ) : (
            <RefreshCw className="w-3.5 h-3.5 text-gray-400" />
          )}
          Re-Detect
        </button>

        {/* Shortcuts button */}
        <button
          onClick={toggleShortcuts}
          className="p-1.5 text-gray-400 hover:text-gray-200 rounded-lg hover:bg-surface-raised border border-border-subtle transition-colors"
          title="Keyboard Shortcuts (?)"
        >
          <Keyboard className="w-3.5 h-3.5" />
        </button>
      </div>

      <ShortcutsModal open={showShortcuts} onClose={() => setShowShortcuts(false)} />
    </header>
  );
}
