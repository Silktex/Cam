'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams } from 'next/navigation';
import { Shield, CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import ToolLayout, { ActionButton } from '../../components/ToolLayout';
import ParameterCard, { SliderControl, SelectControl, ToggleControl } from '../../components/ParameterCard';
import HistogramChart from '../../components/HistogramChart';
import { pbrValidateCheck, pbrValidateStats, getFullUrl } from '@/lib/api';

interface MapInfo {
  filename: string;
  thumbnail_url: string;
  histogram: { r: number[]; g: number[]; b: number[]; luminance?: number[] };
  min?: number;
  max?: number;
  mean?: number;
  r_min?: number; r_max?: number; r_mean?: number;
  g_min?: number; g_max?: number; g_mean?: number;
  b_min?: number; b_max?: number; b_mean?: number;
}

interface ValidationResult {
  map_type: string;
  passed: boolean;
  overlay_url: string;
  stats: Record<string, number | string | number[]>;
  histogram: { r: number[]; g: number[]; b: number[]; luminance?: number[] };
}

export default function ValidatePage() {
  const params = useParams();
  const batchName = params.batchName as string;
  const autoValidateRef = useRef(false);

  // State
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [maps, setMaps] = useState<Record<string, MapInfo>>({});
  const [validating, setValidating] = useState(false);
  const [validationResults, setValidationResults] = useState<ValidationResult[]>([]);

  // Parameters
  const [mode, setMode] = useState('albedo');
  const [darkThreshold, setDarkThreshold] = useState(30);
  const [metalRangeMin, setMetalRangeMin] = useState(180);
  const [showOverlay, setShowOverlay] = useState(false);

  // Run validation
  const handleValidate = useCallback(async () => {
    setValidating(true);
    try {
      const res = await pbrValidateCheck(batchName, {
        mode,
        albedo_dark_threshold: darkThreshold,
        metal_range: [metalRangeMin, 255],
      });
      if (res.data?.success !== false) {
        const results = Array.isArray(res.data) ? res.data : [res.data];
        setValidationResults(results);
        setShowOverlay(true);
      }
    } catch {
      // ignore
    } finally {
      setValidating(false);
    }
  }, [batchName, mode, darkThreshold, metalRangeMin]);

  // Load PBR stats
  useEffect(() => {
    const load = async () => {
      try {
        const res = await pbrValidateStats(batchName);
        if (res.data?.success && res.data?.maps) {
          setMaps(res.data.maps);
        } else {
          setError(res.data?.error || 'No PBR maps found');
        }
      } catch {
        setError('Failed to load PBR maps');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [batchName]);

  // Auto-run validation once stats are loaded
  useEffect(() => {
    if (!loading && Object.keys(maps).length > 0 && !autoValidateRef.current) {
      autoValidateRef.current = true;
      handleValidate();
    }
  }, [loading, maps, handleValidate]);

  const mapTypes = ['albedo', 'normal', 'roughness', 'height'] as const;
  const availableMaps = mapTypes.filter((t) => maps[t]);

  const sidebar = (
    <>
      <ParameterCard title="Validation Mode">
        <SelectControl
          label="Check Type"
          value={mode}
          options={[
            { value: 'albedo', label: 'Albedo Range' },
            { value: 'metallic', label: 'Metallic Range' },
          ]}
          onChange={setMode}
        />
      </ParameterCard>

      <ParameterCard title="Thresholds" description="Set acceptable value ranges">
        <SliderControl
          label="Dark Threshold"
          value={darkThreshold}
          min={0}
          max={100}
          step={1}
          onChange={setDarkThreshold}
          tooltip="Pixels below this value are flagged as too dark"
        />
        <SliderControl
          label="Metal Range Min"
          value={metalRangeMin}
          min={100}
          max={255}
          step={1}
          onChange={setMetalRangeMin}
          tooltip="Minimum value to be considered metallic"
        />
      </ParameterCard>

      {/* Validation results */}
      {validationResults.length > 0 && (
        <ParameterCard title="Results">
          {validationResults.map((result, i) => (
            <div key={i} className="space-y-2">
              <div className="flex items-center gap-2">
                {result.passed ? (
                  <CheckCircle2 className="w-4 h-4 text-green-400" />
                ) : (
                  <XCircle className="w-4 h-4 text-red-400" />
                )}
                <span className={`text-sm font-medium ${result.passed ? 'text-green-400' : 'text-red-400'}`}>
                  {result.map_type}: {result.passed ? 'PASS' : 'FAIL'}
                </span>
              </div>
              {result.stats && (
                <div className="text-xs text-slate-400 space-y-0.5">
                  {Object.entries(result.stats).map(([key, val]) => (
                    <div key={key} className="flex justify-between">
                      <span>{key.replace(/_/g, ' ')}</span>
                      <span className="text-slate-300 font-mono">
                        {typeof val === 'number' ? val.toFixed?.(1) ?? val : String(val)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {result.histogram && (
                <HistogramChart data={result.histogram} showChannels={['luminance']} />
              )}
            </div>
          ))}
        </ParameterCard>
      )}

      {/* Per-map stats */}
      {availableMaps.map((mapType) => {
        const info = maps[mapType];
        if (!info) return null;
        return (
          <ParameterCard key={mapType} title={`${mapType.charAt(0).toUpperCase() + mapType.slice(1)} Stats`}>
            <div className="text-xs text-slate-400 space-y-0.5">
              <div className="flex justify-between">
                <span>File</span>
                <span className="text-slate-300 font-mono text-[10px]">{info.filename}</span>
              </div>
              {info.min !== undefined && (
                <>
                  <div className="flex justify-between">
                    <span>Min / Max</span>
                    <span className="text-slate-300 font-mono">{info.min} / {info.max}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Mean</span>
                    <span className="text-slate-300 font-mono">{info.mean}</span>
                  </div>
                </>
              )}
              {info.r_min !== undefined && (
                <>
                  <div className="flex justify-between">
                    <span>R</span>
                    <span className="text-slate-300 font-mono">{info.r_min}–{info.r_max} (μ{info.r_mean})</span>
                  </div>
                  <div className="flex justify-between">
                    <span>G</span>
                    <span className="text-slate-300 font-mono">{info.g_min}–{info.g_max} (μ{info.g_mean})</span>
                  </div>
                  <div className="flex justify-between">
                    <span>B</span>
                    <span className="text-slate-300 font-mono">{info.b_min}–{info.b_max} (μ{info.b_mean})</span>
                  </div>
                </>
              )}
            </div>
            {info.histogram && <HistogramChart data={info.histogram} />}
          </ParameterCard>
        );
      })}
    </>
  );

  const actionBar = (
    <ActionButton onClick={handleValidate} loading={validating}>
      Validate
    </ActionButton>
  );

  return (
    <ToolLayout
      batchName={batchName}
      toolName="PBR Validate"
      toolIcon={<Shield className="w-4 h-4 text-cyan-400" />}
      sidebar={sidebar}
      actionBar={actionBar}
      loading={loading}
      error={error}
    >
      {/* Overlay toggle - prominent placement above image grid */}
      <div className="mb-3 flex items-center gap-3">
        <ToggleControl
          label="Show Overlay"
          value={showOverlay}
          onChange={setShowOverlay}
        />
        {validating && (
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <Loader2 className="w-3 h-3 animate-spin" />
            Validating...
          </div>
        )}
      </div>

      {/* 2x2 grid of PBR maps */}
      <div className="grid grid-cols-2 gap-4 flex-1">
        {availableMaps.map((mapType) => {
          const info = maps[mapType];
          if (!info) return null;

          // Find matching validation overlay
          const overlay = validationResults.find((r) => r.map_type === mapType);
          const showOverlayUrl = showOverlay && overlay?.overlay_url;

          return (
            <div key={mapType} className="relative rounded-xl overflow-hidden border border-slate-700/50 bg-slate-900">
              {/* Label */}
              <div className="absolute top-2 left-2 z-10 flex items-center gap-2">
                <span className="px-2 py-0.5 bg-slate-900/80 rounded text-xs font-medium text-slate-200 capitalize">
                  {mapType}
                </span>
                {overlay && (
                  <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                    overlay.passed ? 'bg-green-900/80 text-green-300' : 'bg-red-900/80 text-red-300'
                  }`}>
                    {overlay.passed ? 'PASS' : 'FAIL'}
                  </span>
                )}
              </div>

              {/* Image */}
              <img
                src={showOverlayUrl ? getFullUrl(overlay!.overlay_url) : getFullUrl(info.thumbnail_url)}
                alt={mapType}
                className="w-full h-full object-contain"
              />
            </div>
          );
        })}

        {/* Empty slots */}
        {availableMaps.length === 0 && (
          <div className="col-span-2 flex items-center justify-center text-slate-500">
            No PBR maps found
          </div>
        )}
      </div>
    </ToolLayout>
  );
}
