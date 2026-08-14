'use client';

import { useCallback, useEffect, useState } from 'react';
import { Aperture, Loader2, Play, Settings2 } from 'lucide-react';
import {
  getExposureConfig,
  getExposureStatus,
  runExposurePreflight,
  type ExposureConfig,
  type ExposureStatus,
  type PreflightResponse,
} from '@/lib/api';

const statusColor: Record<string, string> = {
  PASS: 'text-teal-400',
  FAIL: 'text-red-400',
  FAIL_DYNAMIC_RANGE: 'text-red-400',
  FAIL_CLIPPING: 'text-red-400',
  FAIL_NON_CONVERGENCE: 'text-red-400',
  WARNING: 'text-yellow-400',
  RETAKE: 'text-orange-400',
};

export default function ExposureStatus() {
  const [config, setConfig] = useState<ExposureConfig | null>(null);
  const [status, setStatus] = useState<ExposureStatus | null>(null);
  const [preflight, setPreflight] = useState<PreflightResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [cfg, st] = await Promise.all([getExposureConfig(), getExposureStatus()]);
      setConfig(cfg.data);
      setStatus(st.data);
    } catch {
      // backend unreachable; leave values untouched
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const onRunPreflight = useCallback(async () => {
    setRunning(true);
    setError(null);
    setPreflight(null);
    try {
      const res = await runExposurePreflight();
      setPreflight(res.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Preflight failed');
    } finally {
      setRunning(false);
    }
  }, []);

  const percent = (v: number) => `${(v * 100).toFixed(1)}%`;

  return (
    <div className="bg-slate-800/80 border border-slate-700 rounded-2xl p-6">
      <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
        <Aperture className="w-5 h-5 text-teal-400" />
        Auto Exposure
        {config && !config.enabled && (
          <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-400">
            disabled
          </span>
        )}
      </h2>

      {status && status.connected && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 text-sm">
          <div className="bg-slate-700/50 rounded-xl p-3">
            <p className="text-slate-400 text-xs">ISO</p>
            <p className="font-semibold">{status.iso ?? '—'}</p>
          </div>
          <div className="bg-slate-700/50 rounded-xl p-3">
            <p className="text-slate-400 text-xs">Aperture</p>
            <p className="font-semibold">{status.aperture ? `f/${status.aperture}` : '—'}</p>
          </div>
          <div className="bg-slate-700/50 rounded-xl p-3">
            <p className="text-slate-400 text-xs">Shutter</p>
            <p className="font-semibold">{status.shutter_label ?? '—'}</p>
          </div>
          <div className="bg-slate-700/50 rounded-xl p-3">
            <p className="text-slate-400 text-xs">Mode</p>
            <p className="font-semibold">{status.camera_mode ?? '—'}</p>
          </div>
        </div>
      )}

      <button
        onClick={onRunPreflight}
        disabled={running || (config !== null && !config.enabled)}
        className="w-full py-2.5 bg-teal-500 text-slate-900 rounded-xl font-semibold
          hover:bg-teal-400 transition-all flex items-center justify-center gap-2
          disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
        {running ? 'Running preflight...' : 'Run Exposure Preflight'}
      </button>

      {error && <p className="text-sm text-red-400 mt-3">{error}</p>}

      {preflight && (
        <div className="mt-4 space-y-3">
          <div className={`text-sm font-medium ${statusColor[preflight.status] ?? 'text-slate-300'}`}>
            Preflight: {preflight.status}
            {preflight.selected_shutter_label && (
              <span className="text-slate-300"> — shutter {preflight.selected_shutter_label}</span>
            )}
          </div>

          {preflight.limiting_light && (
            <p className="text-xs text-slate-400">
              Limiting light: <span className="text-teal-400">{preflight.limiting_light}</span>
              {preflight.limiting_channel && ` (channel ${preflight.limiting_channel})`}
              {preflight.predicted_peak != null && ` • peak ${percent(preflight.predicted_peak)}`}
              {preflight.headroom_ev != null && ` • headroom ${preflight.headroom_ev.toFixed(2)} EV`}
            </p>
          )}

          {preflight.lights.length > 0 && (
            <div className="grid grid-cols-3 gap-2">
              {preflight.lights.map((l) => (
                <div key={l.name} className="bg-slate-700/50 rounded-lg p-2 text-xs">
                  <p className="font-semibold text-slate-300">{l.name}</p>
                  <p className={statusColor[l.status] ?? 'text-slate-400'}>{l.status}</p>
                  {l.measured_normalized != null && (
                    <p className="text-slate-400">{percent(l.measured_normalized)}</p>
                  )}
                </div>
              ))}
            </div>
          )}

          {preflight.errors.length > 0 && (
            <ul className="text-xs text-red-400 list-disc list-inside">
              {preflight.errors.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          )}
        </div>
      )}

      {config && (
        <div className="mt-4 pt-3 border-t border-slate-700 flex items-center gap-2 text-xs text-slate-400">
          <Settings2 className="w-3.5 h-3.5" />
          Target P{config.target_percentile} = {percent(config.target_normalized)} • ISO {config.iso} • f/{config.aperture}
        </div>
      )}
    </div>
  );
}
