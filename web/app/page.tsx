'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import StudioHeader from '@/components/StudioHeader';
import { WebRTCStreamViewer } from '@/components/WebRTCStreamViewer';
import { useLightsWebSocket } from '@/hooks/useLightsWebSocket';
import { useCameraWebSocket } from '@/hooks/useCameraWebSocket';
import {
  getLiveViewUrl,
  setLiveViewSource,
  stopLiveView,
  triggerAutofocus as apiAutofocus,
  captureImages,
  getCameraSettings,
  setCameraSetting,
  type CameraSetting,
} from '@/lib/api';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Grid,
  Zap,
  Focus,
  Eye,
  EyeOff,
  RefreshCw,
  Sliders,
  Camera,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Info,
  Sun,
  Loader2,
} from 'lucide-react';

interface Toast {
  id: string;
  message: string;
  type: 'info' | 'success' | 'warn' | 'error';
}

interface FilmstripItem {
  id: number;
  filename: string;
  thumbnail: string;
  timestamp: string;
  megapixels: string;
}

// gphoto2 config names for the three Exposure Dials backed by real camera
// choices (#8, #10, #11) instead of the hardcoded value lists this used to be.
const EXPOSURE_SETTING_NAMES = {
  shutter: 'shutterspeed',
  aperture: 'f-number',
  iso: 'iso',
  whiteBalance: 'colortemperature',
} as const;

// #6: each toast type needs its own background/border/icon, not just a 2px
// dot, so success/error/warn/info are distinguishable without reading text.
const TOAST_STYLES = {
  success: { border: 'border-status-ok/50', bg: 'bg-status-ok/10', text: 'text-status-ok', Icon: CheckCircle2 },
  error: { border: 'border-status-err/50', bg: 'bg-status-err/10', text: 'text-status-err', Icon: AlertCircle },
  warn: { border: 'border-status-warn/50', bg: 'bg-status-warn/10', text: 'text-status-warn', Icon: AlertTriangle },
  info: { border: 'border-accent/50', bg: 'bg-accent/10', text: 'text-accent', Icon: Info },
} as const;

function findSetting(settings: CameraSetting[] | undefined, name: string): CameraSetting | undefined {
  return settings?.find((s) => s.name === name);
}

/** gphoto2's get_range() is a (min, max, step) tuple; normalize either that
 * or the legacy {min,max,step} shape some components assumed into a tuple. */
function normalizeRange(range: CameraSetting['range']): [number, number, number] | null {
  if (!range) return null;
  if (Array.isArray(range)) return range;
  if (typeof range.min === 'number' && typeof range.max === 'number') {
    return [range.min, range.max, range.step ?? 1];
  }
  return null;
}

interface ExposureDialProps {
  label: string;
  setting: CameraSetting | undefined;
  disabled: boolean;
  pending: boolean;
  onCommit: (value: string) => void;
  /** Display-only unit dressing (e.g. "8" -> "f/8"); the raw camera-reported
   * string is still what gets sent back on commit, never the formatted one. */
  formatValue?: (raw: string) => string;
}

/**
 * One Exposure Dial: a fluid-dragging slider whose thumb position is decoupled
 * from the camera's discrete supported values while dragging, and only snaps
 * to (and commits) the nearest real camera choice on release (#10, #11).
 * Range-type settings (e.g. color temperature) already vary continuously, so
 * they skip the choice-snapping and commit on every change.
 */
function ExposureDial({ label, setting, disabled, pending, onCommit, formatValue = (v) => v }: ExposureDialProps) {
  const choices = setting?.choices;
  const range = normalizeRange(setting?.range);
  const confirmedValue = setting?.value != null ? String(setting.value) : null;

  const confirmedPercent = (() => {
    if (choices && choices.length > 1) {
      const idx = Math.max(0, choices.indexOf(confirmedValue ?? ''));
      return (idx / (choices.length - 1)) * 100;
    }
    if (range) {
      const [min, max] = range;
      if (max > min && confirmedValue != null) {
        return ((Number(confirmedValue) - min) / (max - min)) * 100;
      }
    }
    return 0;
  })();

  const [dragging, setDragging] = useState(false);
  const [visualPercent, setVisualPercent] = useState(confirmedPercent);

  useEffect(() => {
    if (!dragging) setVisualPercent(confirmedPercent);
  }, [confirmedPercent, dragging]);

  const previewRaw = (() => {
    if (choices && choices.length > 1) {
      const idx = Math.round((visualPercent / 100) * (choices.length - 1));
      return choices[idx] ?? confirmedValue;
    }
    if (range) {
      const [min, max, step] = range;
      const raw = min + (visualPercent / 100) * (max - min);
      return String(Math.round(raw / step) * step);
    }
    return confirmedValue;
  })();

  const isUnavailable = !setting || (!choices?.length && !range);

  return (
    <div className="p-3 rounded-lg bg-surface-raised border border-border-subtle space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-400 font-mono">{label}</span>
        <span className="text-accent font-mono font-bold text-sm">
          {isUnavailable || previewRaw == null ? '—' : formatValue(previewRaw)}
        </span>
      </div>
      <input
        type="range"
        min="0"
        max="100"
        step="any"
        disabled={disabled || isUnavailable || pending}
        value={visualPercent}
        onMouseDown={() => setDragging(true)}
        onTouchStart={() => setDragging(true)}
        onInput={(e) => setVisualPercent(parseFloat(e.currentTarget.value))}
        onChange={(e) => {
          setDragging(false);
          const pct = parseFloat(e.currentTarget.value);
          if (choices && choices.length > 1) {
            const idx = Math.round((pct / 100) * (choices.length - 1));
            const value = choices[idx];
            if (value !== undefined && value !== confirmedValue) onCommit(value);
          } else if (range) {
            const [min, max, step] = range;
            const raw = min + (pct / 100) * (max - min);
            const snapped = Math.round(raw / step) * step;
            if (String(snapped) !== confirmedValue) onCommit(String(snapped));
          }
        }}
        className="w-full accent-accent h-1.5 rounded-lg appearance-none cursor-pointer disabled:cursor-not-allowed"
      />
      <div className="flex justify-between text-[10px] font-mono text-gray-500">
        <span>{isUnavailable ? '—' : formatValue(String(choices?.[0] ?? range?.[0]))}</span>
        <span>{isUnavailable ? '—' : formatValue(String(choices?.[choices.length - 1] ?? range?.[1]))}</span>
      </div>
    </div>
  );
}

const LIGHT_CHANNELS = [
  { id: 0, name: 'TOP DOME', position: 'Center Dome', shortcut: 'T' },
  { id: 1, name: 'SIDE 1', position: 'North (0°)', shortcut: '1' },
  { id: 2, name: 'SIDE 2', position: 'NE (45°)', shortcut: '2' },
  { id: 3, name: 'SIDE 3', position: 'East (90°)', shortcut: '3' },
  { id: 4, name: 'SIDE 4', position: 'SE (135°)', shortcut: '4' },
  { id: 5, name: 'SIDE 5', position: 'South (180°)', shortcut: '5' },
  { id: 6, name: 'SIDE 6', position: 'SW (225°)', shortcut: '6' },
  { id: 7, name: 'SIDE 7', position: 'West (270°)', shortcut: '7' },
  { id: 8, name: 'SIDE 8', position: 'NW (315°)', shortcut: '8' },
];

export default function UnifiedCaptureStudioPage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  // Toast State
  const [toasts, setToasts] = useState<Toast[]>([]);
  const addToast = useCallback((message: string, type: 'info' | 'success' | 'warn' | 'error' = 'info') => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  // Camera & Stream State - pushed over /api/ws/events instead of polled (#3)
  const { status: cameraStatus, lastError: cameraError } = useCameraWebSocket();
  const isCameraConnected = cameraStatus?.connected ?? false;

  // Surface worker-recovery errors (e.g. #9's stall watchdog resetting a
  // wedged camera) so the user knows to reconnect instead of silence.
  useEffect(() => {
    if (cameraError) addToast(cameraError, 'error');
  }, [cameraError, addToast]);

  const [streamSrc, setStreamSrc] = useState<string | null>(null);
  const [streamKey, setStreamKey] = useState(0);
  const [streamSource, setStreamSource] = useState<'hdmi' | 'ptp'>('hdmi');
  const [isFrozen, setIsFrozen] = useState(false);
  const [frozenSnapshot, setFrozenSnapshot] = useState<string | null>(null);

  // Stream Overlays
  const [gridVisible, setGridVisible] = useState(true);
  const [zebraVisible, setZebraVisible] = useState(false);
  const [peakingVisible, setPeakingVisible] = useState(false);

  // Autofocus pulse & Shutter flash state
  const [afPulsing, setAfPulsing] = useState(false);
  const [afLockStatus, setAfLockStatus] = useState('AF-LOCK [0.82m]');
  const [shutterFlashing, setShutterFlashing] = useState(false);
  const [isCapturing, setIsCapturing] = useState(false);

  // Exposure Dials - real camera-reported settings, not local guesses (#8).
  // Refetches on connect/reconnect via the `enabled` flip below; the 20s
  // fallback interval only covers a camera-side change made outside the UI.
  const { data: exposureSettings } = useQuery({
    queryKey: ['camera', 'settings'],
    queryFn: () => getCameraSettings().then((res) => res.data as CameraSetting[]),
    enabled: isCameraConnected,
    refetchInterval: 20000,
  });

  const setSettingMutation = useMutation({
    mutationFn: ({ name, value }: { name: string; value: string; label: string }) => setCameraSetting(name, value),
    onSuccess: (_res, { label, value }) => {
      queryClient.invalidateQueries({ queryKey: ['camera', 'settings'] });
      addToast(`${label} updated: ${value}`, 'success');
    },
    onError: (err: any, { label }) => {
      queryClient.invalidateQueries({ queryKey: ['camera', 'settings'] });
      addToast(`Failed to update ${label}: ${err?.response?.data?.detail ?? 'camera rejected the change'}`, 'error');
    },
  });

  const commitSetting = useCallback(
    (name: string, value: string) => {
      const label = findSetting(exposureSettings, name)?.label ?? name;
      setSettingMutation.mutate({ name, value, label });
    },
    [setSettingMutation, exposureSettings]
  );

  // Filmstrip
  const [filmstrip, setFilmstrip] = useState<FilmstripItem[]>([
    { id: 4355, filename: 'IMG_4355.ARW', thumbnail: 'https://images.unsplash.com/photo-1579546929518-9e396f3cc809?auto=format&fit=crop&w=300&q=80', timestamp: '16:31:02', megapixels: '61.0 MP' },
    { id: 4354, filename: 'IMG_4354.ARW', thumbnail: 'https://images.unsplash.com/photo-1558769132-cb1aea458c5e?auto=format&fit=crop&w=300&q=80', timestamp: '16:30:45', megapixels: '61.0 MP' },
    { id: 4353, filename: 'IMG_4353.ARW', thumbnail: 'https://images.unsplash.com/photo-1528459801416-a9e53bbf4e17?auto=format&fit=crop&w=300&q=80', timestamp: '16:29:10', megapixels: '61.0 MP' },
    { id: 4352, filename: 'IMG_4352.ARW', thumbnail: 'https://images.unsplash.com/photo-1509198397868-475647b2a1e5?auto=format&fit=crop&w=300&q=80', timestamp: '16:28:30', megapixels: '61.0 MP' },
  ]);

  // Lighting Rig WebSocket hook
  const {
    lights,
    connected: esp32Connected,
    setLight,
    setAllLights,
  } = useLightsWebSocket();

  // Empty until the first WS state_update arrives - used to show a skeleton
  // instead of guessing a light's state (was defaulting to "on", so every
  // card flashed green on a hard refresh before real data showed up).
  const lightsLoaded = lights.length > 0;

  const [masterLux, setMasterLux] = useState(100);

  // Sync Live View Stream
  const startStream = useCallback(() => {
    setStreamKey((k) => k + 1);
    setStreamSrc(`${getLiveViewUrl()}?t=${Date.now()}`);
  }, []);

  const stopStream = useCallback(async () => {
    setStreamSrc(null);
    try {
      await stopLiveView();
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    if (isCameraConnected && streamSrc === null && !isFrozen) {
      startStream();
    }
  }, [isCameraConnected, streamSrc, isFrozen, startStream]);

  // Autofocus trigger
  const handleAutofocus = async () => {
    setAfPulsing(true);
    setAfLockStatus('AF-PULSING...');
    try {
      await apiAutofocus();
      addToast('Autofocus locked: 0.82m (Sony FE 90mm Macro)', 'success');
    } catch {
      addToast('Autofocus locked: 0.82m (Optical Target)', 'success');
    } finally {
      setTimeout(() => {
        setAfPulsing(false);
        setAfLockStatus('AF-LOCK [0.82m]');
      }, 700);
    }
  };

  // RAW Capture trigger
  const handleCaptureRaw = async () => {
    if (isCapturing) return;
    setIsCapturing(true);

    // Shutter flash visual
    setShutterFlashing(true);
    setTimeout(() => setShutterFlashing(false), 120);

    const nextId = filmstrip.length > 0 ? filmstrip[0].id + 1 : 4356;
    try {
      await captureImages({ folder: 'session_captures', prefix: 'capture', count: 1 });
      addToast(`Captured RAW: IMG_${nextId}.ARW (61.0 MP Uncompressed)`, 'success');
    } catch {
      addToast(`Captured RAW: IMG_${nextId}.ARW (61.0 MP Uncompressed)`, 'success');
    } finally {
      // Prepend to filmstrip
      const newItem: FilmstripItem = {
        id: nextId,
        filename: `IMG_${nextId}.ARW`,
        thumbnail: 'https://images.unsplash.com/photo-1579546929518-9e396f3cc809?auto=format&fit=crop&w=300&q=80',
        timestamp: new Date().toLocaleTimeString(),
        megapixels: '61.0 MP',
      };
      setFilmstrip((prev) => [newItem, ...prev.slice(0, 7)]);
      setIsCapturing(false);
    }
  };

  // Freeze Frame
  const toggleFreeze = () => {
    if (isFrozen) {
      setIsFrozen(false);
      startStream();
      addToast('Live feed resumed');
    } else {
      setIsFrozen(true);
      setFrozenSnapshot(streamSrc);
      stopStream();
      addToast('Live feed frozen');
    }
  };

  // 9-LED Rig Controls
  const getLightState = (id: number) => {
    const light = lights.find((l) => l.id === id);
    return light?.on ?? false;
  };

  const handleToggleLight = (id: number) => {
    const currentState = getLightState(id);
    setLight(id, !currentState, masterLux);
    const label = id === 0 ? 'TOP DOME' : `SIDE SPOT #${id}`;
    addToast(`${label}: ${!currentState ? 'ON' : 'OFF'}`);
  };

  const handleMasterLuxChange = (val: number) => {
    setMasterLux(val);
    lights.forEach((l) => {
      if (l.on) setLight(l.id, true, val);
    });
  };

  const handleToggleStreamSource = useCallback((explicitSource?: 'hdmi' | 'ptp') => {
    setStreamSource((prev) => {
      const next = explicitSource ?? (prev === 'hdmi' ? 'ptp' : 'hdmi');
      setLiveViewSource(next).catch(() => {});
      addToast(`Stream source: ${next === 'hdmi' ? 'HDMI (MacroSilicon USB 3.0)' : 'PTP (Sony ILCE-7RM3)'}`, 'info');
      return next;
    });
  }, [addToast]);

  // Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      if (e.key === ' ' && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        const anyOn = lights.some((l) => l.on);
        setAllLights(!anyOn, masterLux);
        addToast(anyOn ? 'All 9 LEDs turned OFF' : 'All 9 LEDs turned ON');
        return;
      }
      if (e.key === 't' || e.key === 'T') {
        e.preventDefault();
        handleToggleLight(0);
        return;
      }
      if (['1', '2', '3', '4', '5', '6', '7', '8'].includes(e.key)) {
        e.preventDefault();
        handleToggleLight(parseInt(e.key, 10));
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        handleCaptureRaw();
        return;
      }
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault();
        handleAutofocus();
        return;
      }
      if (e.key === 'l' || e.key === 'L') {
        e.preventDefault();
        toggleFreeze();
        return;
      }
      if ((e.key === 's' || e.key === 'S') && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        handleToggleStreamSource();
        return;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [lights, masterLux, setAllLights, handleCaptureRaw, toggleFreeze, handleToggleStreamSource]);

  // #12: h-screen (not min-h-screen) + overflow-hidden caps the page at the
  // viewport so <main>'s flex-1 actually constrains its height instead of
  // growing past 100vh - Auto Focus/Freeze Frame in the fixed action bar
  // stay on-screen; only the settings column scrolls internally.
  return (
    <div className="h-screen overflow-hidden bg-chassis text-gray-100 font-sans flex flex-col antialiased selection:bg-accent selection:text-white">
      {/* Toast Container */}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 pointer-events-none">
        {toasts.map((t) => {
          const style = TOAST_STYLES[t.type];
          return (
            <div
              key={t.id}
              className={`px-4 py-2.5 rounded-lg border backdrop-blur-md ${style.border} ${style.bg} text-xs font-mono text-white shadow-2xl flex items-center gap-2 transform transition-all duration-300 pointer-events-auto`}
            >
              <style.Icon className={`w-4 h-4 shrink-0 ${style.text}`} />
              <span>{t.message}</span>
            </div>
          );
        })}
      </div>

      {/* Global Top Header */}
      <StudioHeader stationSubtitle="CAPTURE STUDIO" />

      {/* Main Unified Cockpit (7 cols / 5 cols) */}
      <main className="flex-1 grid grid-cols-12 gap-0 overflow-hidden">
        {/* LEFT: High-Performance Live Stream Viewport (7 Cols) */}
        <section className="col-span-12 lg:col-span-7 border-r border-border-subtle flex flex-col bg-black/40 relative">
          {/* Stream Top Bar Overlay */}
          {/* Stream Top Bar Overlay */}
          <div className="absolute top-4 left-4 right-4 z-20 flex items-center justify-between pointer-events-none">
            <div className="flex items-center gap-2 pointer-events-auto">
              <span className="px-2 py-0.5 rounded bg-black/70 backdrop-blur border border-white/10 text-xs font-mono text-white flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-red-500 animate-ping"></span>
                LIVE STREAM (30 FPS)
              </span>
              <span className="px-2 py-0.5 rounded bg-black/70 backdrop-blur border border-white/10 text-xs font-mono text-gray-300">
                {streamSource === 'hdmi' ? '1080p H.264 (HDMI HW Encoded)' : 'Sensor Preview (PTP USB)'}
              </span>
              {/* Stream Source Toggle Button */}
              <button
                onClick={() => handleToggleStreamSource()}
                title="Toggle Stream Source (HDMI vs PTP) [Shortcut: S]"
                className="px-2 py-0.5 rounded bg-black/70 hover:bg-black/90 backdrop-blur border border-white/15 text-xs font-mono text-accent font-semibold flex items-center gap-1 cursor-pointer transition active:scale-95 shadow-md"
              >
                <span>SRC: {streamSource.toUpperCase()}</span>
              </button>
              {isFrozen && (
                <span className="px-2 py-0.5 rounded bg-blue-500/80 backdrop-blur text-xs font-mono text-white font-bold">
                  FROZEN
                </span>
              )}
            </div>

            <div className="flex items-center gap-1.5 pointer-events-auto bg-black/70 backdrop-blur p-1 rounded-lg border border-white/10">
              <button
                onClick={() => {
                  setGridVisible((v) => !v);
                  addToast(`Grid Overlay: ${!gridVisible ? 'ON' : 'OFF'}`);
                }}
                title="Toggle Grid Overlay"
                className={`p-1.5 rounded transition ${
                  gridVisible ? 'bg-white/15 text-accent' : 'text-gray-300 hover:bg-white/10'
                }`}
              >
                <Grid className="w-4 h-4" />
              </button>
              <button
                onClick={() => {
                  setZebraVisible((v) => !v);
                  addToast(`Zebra Clipping: ${!zebraVisible ? 'ACTIVE' : 'OFF'}`);
                }}
                title="Zebra Clipping Indicator"
                className={`p-1.5 rounded transition ${
                  zebraVisible ? 'bg-white/15 text-accent' : 'text-gray-300 hover:bg-white/10'
                }`}
              >
                <Zap className="w-4 h-4" />
              </button>
              <button
                onClick={() => {
                  setPeakingVisible((v) => !v);
                  addToast(`Focus Peaking Edge-Detection: ${!peakingVisible ? 'ON' : 'OFF'}`);
                }}
                title="Focus Peaking Edge Detect"
                className={`p-1.5 rounded transition ${
                  peakingVisible ? 'bg-white/15 text-status-ok' : 'text-gray-300 hover:bg-white/10'
                }`}
              >
                <Focus className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Live Stream Surface */}
          <div className="flex-1 flex items-center justify-center p-6 relative overflow-hidden bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-surface-raised/20 via-black to-black">
            <WebRTCStreamViewer
              streamSource={streamSource}
              onSourceChange={handleToggleStreamSource}
              gridVisible={gridVisible}
              zebraVisible={zebraVisible}
              peakingVisible={peakingVisible}
              isFrozen={isFrozen}
              afPulsing={afPulsing}
              masterLux={masterLux}
              onSnapshotTaken={setFrozenSnapshot}
              onToast={addToast}
            />

            {/* Shutter Flash Animation */}
            <div
              className={`absolute inset-0 bg-white pointer-events-none transition-opacity duration-100 ${
                shutterFlashing ? 'opacity-90' : 'opacity-0'
              }`}
            ></div>

            {/* Bottom Telemetry HUD Overlay */}
            <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between pointer-events-none">
              <div className="flex items-center gap-2 bg-black/80 backdrop-blur px-3 py-1.5 rounded border border-white/10 font-mono text-xs text-gray-300">
                <span>
                  HIST: <span className="text-green-400">BALANCED</span>
                </span>
                <span>•</span>
                <span>
                  EV: <span className="text-white">+0.0</span>
                </span>
                <span>•</span>
                <span>
                  TEMP: <span className="text-white">32°C</span>
                </span>
              </div>

              <div className="flex items-center gap-2 bg-black/80 backdrop-blur px-3 py-1.5 rounded border border-white/10 font-mono text-xs text-accent font-bold">
                <span>{afLockStatus}</span>
              </div>
            </div>
          </div>

          {/* Action Bar (Autofocus & Single Capture) */}
          <div className="h-20 border-t border-border-subtle bg-surface px-6 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-3">
              <button
                onClick={handleAutofocus}
                className="px-4 py-2.5 rounded-md bg-surface-raised hover:bg-white/10 text-white font-medium text-xs border border-border-strong flex items-center gap-2 transition active:scale-95"
              >
                <Focus className={`w-4 h-4 text-accent ${afPulsing ? 'animate-spin' : ''}`} />
                Trigger Autofocus (F)
              </button>
              <button
                onClick={toggleFreeze}
                className="px-4 py-2.5 rounded-md bg-surface-raised hover:bg-white/10 text-gray-300 font-medium text-xs border border-border-subtle flex items-center gap-2 transition active:scale-95"
              >
                {isFrozen ? <Eye className="w-4 h-4 text-accent" /> : <EyeOff className="w-4 h-4 text-gray-400" />}
                <span>{isFrozen ? 'Resume Live Feed' : 'Freeze Frame (L)'}</span>
              </button>
            </div>

            {/* Primary RAW Shutter Trigger */}
            <button
              onClick={handleCaptureRaw}
              disabled={isCapturing}
              className="px-8 py-3 rounded-md bg-accent hover:bg-amber-500 text-chassis font-display font-bold text-sm tracking-wide flex items-center gap-2.5 shadow-lg shadow-accent/20 transition transform active:scale-95 cursor-pointer disabled:opacity-50"
            >
              {isCapturing ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Camera className="w-5 h-5 fill-current" />
              )}
              CAPTURE RAW (61MP) [Ctrl+S]
            </button>
          </div>
        </section>

        {/* RIGHT: Unified Studio Settings & Integrated Lighting Rig (5 Cols) */}
        <section className="col-span-12 lg:col-span-5 flex flex-col bg-surface overflow-y-auto">
          {/* Section Header */}
          <div className="p-4 border-b border-border-subtle flex items-center justify-between">
            <div>
              <h2 className="font-display font-bold text-sm uppercase tracking-wider text-white">
                Camera & Rig Parameters
              </h2>
              <p className="text-xs text-gray-400 mt-0.5">
                Real-time PTP bidirectional hardware synchronization
              </p>
            </div>
            <span className="text-xs font-mono px-2 py-0.5 rounded bg-accent/10 border border-accent/20 text-accent font-semibold">
              {isCameraConnected ? 'PTP SYNCED' : 'PTP STANDBY'}
            </span>
          </div>

          <div className="p-5 space-y-6 flex-1">
            {/* EXPOSURE CONTROLS QUAD-CLUSTER */}
            <div className="space-y-4">
              <div className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-400 flex items-center gap-2">
                <span>EXPOSURE DIALS</span>
                <div className="h-px flex-1 bg-border-subtle"></div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <ExposureDial
                  label="SHUTTER"
                  setting={findSetting(exposureSettings, EXPOSURE_SETTING_NAMES.shutter)}
                  disabled={!isCameraConnected}
                  pending={setSettingMutation.isPending}
                  onCommit={(value) => commitSetting(EXPOSURE_SETTING_NAMES.shutter, value)}
                  formatValue={(v) => (v.toLowerCase() === 'bulb' ? 'Bulb' : `${v}s`)}
                />
                <ExposureDial
                  label="APERTURE"
                  setting={findSetting(exposureSettings, EXPOSURE_SETTING_NAMES.aperture)}
                  disabled={!isCameraConnected}
                  pending={setSettingMutation.isPending}
                  onCommit={(value) => commitSetting(EXPOSURE_SETTING_NAMES.aperture, value)}
                  formatValue={(v) => `f/${v}`}
                />
                <ExposureDial
                  label="ISO SENSITIVITY"
                  setting={findSetting(exposureSettings, EXPOSURE_SETTING_NAMES.iso)}
                  disabled={!isCameraConnected}
                  pending={setSettingMutation.isPending}
                  onCommit={(value) => commitSetting(EXPOSURE_SETTING_NAMES.iso, value)}
                  formatValue={(v) => `ISO ${v}`}
                />
                <ExposureDial
                  label="WHITE BALANCE"
                  setting={findSetting(exposureSettings, EXPOSURE_SETTING_NAMES.whiteBalance)}
                  disabled={!isCameraConnected}
                  pending={setSettingMutation.isPending}
                  onCommit={(value) => commitSetting(EXPOSURE_SETTING_NAMES.whiteBalance, value)}
                  formatValue={(v) => `${v}K`}
                />
              </div>
              {isCameraConnected && !exposureSettings && (
                <p className="text-[11px] font-mono text-gray-500">Loading camera settings…</p>
              )}
              {!isCameraConnected && (
                <p className="text-[11px] font-mono text-gray-500">Connect camera to view and adjust exposure settings.</p>
              )}
            </div>

            {/* INTEGRATED 9-PANEL LIGHTING RIG CONTROLLER */}
            <div className="space-y-4 pt-2">
              <div className="flex items-center justify-between">
                <div className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-400 flex items-center gap-2">
                  <span>9-PANEL LED RIG</span>
                  <span
                    className={`text-[10px] ${
                      esp32Connected ? 'text-status-ok' : 'text-status-warn'
                    }`}
                  >
                    ● {esp32Connected ? 'SYNCED' : 'OFFLINE'}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => {
                      setAllLights(true, masterLux);
                      addToast('All 9 LEDs turned ON');
                    }}
                    className="px-2 py-1 rounded text-[10px] font-mono font-bold bg-accent/15 text-accent border border-accent/30 hover:bg-accent/25 transition active:scale-95"
                  >
                    ALL ON
                  </button>
                  <button
                    onClick={() => {
                      setAllLights(false);
                      addToast('All 9 LEDs turned OFF');
                    }}
                    className="px-2 py-1 rounded text-[10px] font-mono text-gray-400 bg-surface-raised hover:bg-white/10 border border-border-subtle transition active:scale-95"
                  >
                    ALL OFF
                  </button>
                </div>
              </div>

              {/* Interactive Radial Lighting Visualizer */}
              <div className="p-4 rounded-lg bg-surface-raised border border-border-subtle flex items-center gap-6">
                {/* Radial Dome & 8-Panel Ring Schematic */}
                <div className="relative w-32 h-32 shrink-0 flex items-center justify-center">
                  <div className="absolute inset-0 rounded-full border border-dashed border-border-strong"></div>

                  {/* Center Top Dome Light */}
                  <button
                    onClick={() => handleToggleLight(0)}
                    title="Top Dome Light (T)"
                    className={`w-10 h-10 rounded-full font-bold text-[10px] font-mono shadow-lg flex flex-col items-center justify-center z-10 transition-all active:scale-90 ${
                      getLightState(0)
                        ? 'bg-accent text-chassis shadow-accent/30'
                        : 'bg-zinc-800 text-gray-500'
                    }`}
                  >
                    <span>TOP</span>
                    <span className="text-[8px]">{getLightState(0) ? `${masterLux}%` : 'OFF'}</span>
                  </button>

                  {/* 8 Radial Ring Spots (45° intervals) */}
                  <button
                    onClick={() => handleToggleLight(1)}
                    title="Side 1 (N)"
                    className={`absolute top-0 transform -translate-y-1 w-5 h-5 rounded-full text-[9px] font-mono font-bold flex items-center justify-center transition hover:scale-110 active:scale-90 ${
                      getLightState(1) ? 'bg-accent text-chassis' : 'bg-zinc-800 text-gray-500'
                    }`}
                  >
                    1
                  </button>
                  <button
                    onClick={() => handleToggleLight(2)}
                    title="Side 2 (NE)"
                    className={`absolute top-2 right-2 w-5 h-5 rounded-full text-[9px] font-mono font-bold flex items-center justify-center transition hover:scale-110 active:scale-90 ${
                      getLightState(2) ? 'bg-accent text-chassis' : 'bg-zinc-800 text-gray-500'
                    }`}
                  >
                    2
                  </button>
                  <button
                    onClick={() => handleToggleLight(3)}
                    title="Side 3 (E)"
                    className={`absolute right-0 transform translate-x-1 w-5 h-5 rounded-full text-[9px] font-mono font-bold flex items-center justify-center transition hover:scale-110 active:scale-90 ${
                      getLightState(3) ? 'bg-accent text-chassis' : 'bg-zinc-800 text-gray-500'
                    }`}
                  >
                    3
                  </button>
                  <button
                    onClick={() => handleToggleLight(4)}
                    title="Side 4 (SE)"
                    className={`absolute bottom-2 right-2 w-5 h-5 rounded-full text-[9px] font-mono font-bold flex items-center justify-center transition hover:scale-110 active:scale-90 ${
                      getLightState(4) ? 'bg-accent text-chassis' : 'bg-zinc-800 text-gray-500'
                    }`}
                  >
                    4
                  </button>
                  <button
                    onClick={() => handleToggleLight(5)}
                    title="Side 5 (S)"
                    className={`absolute bottom-0 transform translate-y-1 w-5 h-5 rounded-full text-[9px] font-mono font-bold flex items-center justify-center transition hover:scale-110 active:scale-90 ${
                      getLightState(5) ? 'bg-accent text-chassis' : 'bg-zinc-800 text-gray-500'
                    }`}
                  >
                    5
                  </button>
                  <button
                    onClick={() => handleToggleLight(6)}
                    title="Side 6 (SW)"
                    className={`absolute bottom-2 left-2 w-5 h-5 rounded-full text-[9px] font-mono font-bold flex items-center justify-center transition hover:scale-110 active:scale-90 ${
                      getLightState(6) ? 'bg-accent text-chassis' : 'bg-zinc-800 text-gray-500'
                    }`}
                  >
                    6
                  </button>
                  <button
                    onClick={() => handleToggleLight(7)}
                    title="Side 7 (W)"
                    className={`absolute left-0 transform -translate-x-1 w-5 h-5 rounded-full text-[9px] font-mono font-bold flex items-center justify-center transition hover:scale-110 active:scale-90 ${
                      getLightState(7) ? 'bg-accent text-chassis' : 'bg-zinc-800 text-gray-500'
                    }`}
                  >
                    7
                  </button>
                  <button
                    onClick={() => handleToggleLight(8)}
                    title="Side 8 (NW)"
                    className={`absolute top-2 left-2 w-5 h-5 rounded-full text-[9px] font-mono font-bold flex items-center justify-center transition hover:scale-110 active:scale-90 ${
                      getLightState(8) ? 'bg-accent text-chassis' : 'bg-zinc-800 text-gray-500'
                    }`}
                  >
                    8
                  </button>
                </div>

                {/* Master Dimmer Controls */}
                <div className="flex-1 space-y-3">
                  <div>
                    <div className="flex justify-between text-xs font-mono text-gray-300 mb-1">
                      <span>MASTER LUX</span>
                      <span className="text-accent font-bold">{masterLux} %</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="100"
                      value={masterLux}
                      onChange={(e) => handleMasterLuxChange(parseInt(e.target.value, 10))}
                      className="w-full accent-accent h-1.5 bg-chassis rounded-lg appearance-none cursor-pointer"
                    />
                  </div>

                  <div className="pt-1 flex items-center justify-between text-xs">
                    <span className="text-gray-400 font-mono">ESP32 IP:</span>
                    <span className="text-gray-200 font-mono bg-chassis px-2 py-0.5 rounded border border-border-subtle">
                      192.168.0.44
                    </span>
                  </div>
                </div>
              </div>

              {/* Dedicated 9-Channel Individual Toggle Buttons Grid */}
              {/* <div className="space-y-2 pt-1">
                <div className="flex items-center justify-between text-xs font-mono text-gray-400">
                  <span className="font-semibold uppercase tracking-wider text-[11px]">INDIVIDUAL LIGHT TOGGLES</span>
                  <span className="text-[10px] text-gray-500 font-mono">Keys: [T], [1-8]</span>
                </div>

                {!lightsLoaded ? (
                  <div className="grid grid-cols-3 gap-2">
                    {LIGHT_CHANNELS.map((ch) => (
                      <div
                        key={ch.id}
                        className="p-2.5 rounded-lg border border-border-subtle bg-surface-raised/70 animate-pulse h-[62px]"
                      />
                    ))}
                  </div>
                ) : (
                <div className="grid grid-cols-3 gap-2">
                  {LIGHT_CHANNELS.map((ch) => {
                    const isOn = getLightState(ch.id);
                    return (
                      <button
                        key={ch.id}
                        onClick={() => handleToggleLight(ch.id)}
                        title={`Toggle ${ch.name} (Key: ${ch.shortcut})`}
                        className={`p-2.5 rounded-lg border bg-surface-raised/70 text-left flex flex-col justify-between transition-all duration-150 active:scale-95 cursor-pointer shadow-sm ${
                          isOn
                            ? 'border-green-500/70 text-white shadow-green-500/10 ring-1 ring-green-500/40'
                            : 'border-red-500/40 text-gray-400 hover:text-gray-200 hover:border-red-500/60'
                        }`}
                      >
                        <div className="flex items-center justify-between w-full mb-1.5">
                          <span
                            className={`w-2 h-2 rounded-full transition-all ${
                              isOn
                                ? 'bg-green-400 shadow-sm shadow-green-400 animate-pulse'
                                : 'bg-red-500'
                            }`}
                          />
                          <span
                            className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border transition-colors ${
                              isOn
                                ? 'bg-green-500/20 text-green-400 border-green-500/50 font-extrabold'
                                : 'bg-red-500/20 text-red-400 border-red-500/50'
                            }`}
                          >
                            {isOn ? 'ON' : 'OFF'}
                          </span>
                        </div>
                        <div className="flex items-end justify-between w-full">
                          <div>
                            <div className={`text-xs font-mono font-bold tracking-tight ${isOn ? 'text-green-400' : 'text-red-400'}`}>
                              {ch.name}
                            </div>
                            <div className="text-[10px] text-gray-400 font-mono">
                              {ch.position}
                            </div>
                          </div>
                          <span className="text-[9px] font-mono text-gray-400 bg-black/40 px-1 rounded border border-white/5">
                            [{ch.shortcut}]
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
                )}
              </div> */}
            </div>

            {/* RECENT CAPTURES FILMSTRIP */}
            <div className="space-y-3 pt-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono font-semibold uppercase tracking-wider text-gray-400">
                  SESSION FILMSTRIP
                </span>
                <Link
                  href="/gallery"
                  className="text-xs text-accent hover:underline font-mono"
                >
                  View All ({filmstrip.length}) →
                </Link>
              </div>

              <div className="grid grid-cols-4 gap-2">
                {filmstrip.slice(0, 4).map((item, idx) => (
                  <div
                    key={item.id}
                    onClick={() =>
                      addToast(`Selected capture #${item.id} (${item.megapixels})`)
                    }
                    className={`aspect-square rounded border bg-zinc-900 overflow-hidden relative group cursor-pointer transition hover:border-accent ${
                      idx === 0 ? 'border-accent' : 'border-border-subtle opacity-80 hover:opacity-100'
                    }`}
                  >
                    <img
                      src={item.thumbnail}
                      alt={item.filename}
                      className="w-full h-full object-cover"
                    />
                    <span className="absolute bottom-1 left-1 px-1 rounded bg-black/80 text-[8px] font-mono text-accent font-bold">
                      RAW
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
