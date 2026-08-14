'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Save, Loader2 } from 'lucide-react';
import {
  getProcessTrack,
  createProcessTrack,
  updatePhaseParams,
  pipelinePreview,
  pipelineSave,
  type ProcessTrack,
} from '@/lib/api';

import ImagePreview from './ImagePreview';
import CropCanvas from './CropCanvas';
import useCropEditor from './useCropEditor';
import CropAlignCard from './CropAlignCard';
import ColorCard from './ColorCard';
import PBRCard from './PBRCard';
import MapRefineCard from './MapRefineCard';
import SeamlessTilingCard from './SeamlessTilingCard';
import ValidateExportCard from './ValidateExportCard';

const PHASE_NAMES = [
  'crop_align',
  'color',
  'pbr',
  'map_refine',
  'seamless_tiling',
  'validate_export',
] as const;

interface EditorLayoutProps {
  batchName: string;
  onBack: () => void;
}

// Per-phase debounce times (ms) — fast for interactive sliders, slower for heavy ops
const DEBOUNCE_MS: Record<string, number> = {
  crop_align: 150,
  color: 150,
  pbr: 500,
  map_refine: 300,
  seamless_tiling: 300,
  validate_export: 300,
};

export default function EditorLayout({ batchName, onBack }: EditorLayoutProps) {
  const queryClient = useQueryClient();
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [pendingExposure, setPendingExposure] = useState<number | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Active editor state
  const [activeEditor, setActiveEditor] = useState<'crop' | null>(null);

  // Load or create track
  const { data: track, isLoading: trackLoading } = useQuery({
    queryKey: ['process-track', batchName],
    queryFn: async () => {
      try {
        const res = await getProcessTrack(batchName);
        return res.data;
      } catch (e: any) {
        if (e.response?.status === 404) {
          const res = await createProcessTrack(batchName);
          return res.data.track;
        }
        throw e;
      }
    },
  });

  // Count completed phases
  const completedPhases = track
    ? PHASE_NAMES.filter(
        (p) => track.phases[p].status === 'completed' || track.phases[p].status === 'skipped'
      ).length
    : 0;

  // Save params mutation
  const saveParamsMut = useMutation({
    mutationFn: ({
      phase,
      data,
    }: {
      phase: string;
      data: { status?: string; params?: Record<string, any> };
    }) => updatePhaseParams(batchName, phase, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['process-track', batchName] });
    },
  });

  // Preview mutation — ignores aborted requests
  const previewMut = useMutation({
    mutationFn: (phase: string) => pipelinePreview(batchName, phase),
    onSuccess: (res) => {
      const url = res.data.albedo_url || res.data.preview_url;
      if (url) setPreviewUrl(`${url}?t=${Date.now()}`);
      setPendingExposure(null);
    },
    onError: (err: any) => {
      // Ignore aborted requests (superseded by a newer one)
      if (err?.code === 'ERR_CANCELED' || err?.name === 'AbortError' || err?.name === 'CanceledError') return;
    },
  });

  // Stable ref to mutate function for use in debounced callback
  const previewMutRef = useRef(previewMut.mutate);
  previewMutRef.current = previewMut.mutate;

  // Debounced preview — per-phase timing, stable callback that reads mutate from ref
  const debouncedPreview = useCallback(
    (phase: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      const delay = DEBOUNCE_MS[phase] ?? 300;
      debounceRef.current = setTimeout(() => {
        setPreviewLoading(true);
        previewMutRef.current(phase, {
          onSettled: () => setPreviewLoading(false),
        });
      }, delay);
    },
    []
  );

  // Crop editor hook — lives here so state persists across editor toggles
  const cropEditor = useCropEditor(
    batchName,
    () => setActiveEditor(null),
    () => debouncedPreview('crop_align'),
  );

  // Load initial preview for the active phase — fire immediately, no debounce
  useEffect(() => {
    if (track) {
      for (const phase of PHASE_NAMES) {
        if (track.phases[phase].status !== 'completed' && track.phases[phase].status !== 'skipped') {
          setPreviewLoading(true);
          previewMut.mutate(phase, {
            onSettled: () => setPreviewLoading(false),
          });
          break;
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track?.updated_at]);

  // Handler: update phase params
  const handlePhaseParamsChange = useCallback(
    (phase: string, params: Record<string, any>) => {
      saveParamsMut.mutate({ phase, data: { params } });
    },
    [saveParamsMut]
  );

  // Default params for each phase (mirrors _default_phases in process_track_service.py)
  const DEFAULT_PHASE_PARAMS: Record<string, Record<string, any>> = {
    crop_align: {
      crop_type: null, points: null, rotation: 0, crop_size: 2048,
      straighten: { enabled: false, mode: 'auto', strength: 1.0, direction: 'both' },
      perspective: { enabled: false, source_points: null, dest_points: null },
    },
    color: {
      profile_name: null, matrix_3x3: null, checker_wb: null, checker_raw_path: null,
      exposure_method: 'exposure_match', exposure_offset: 0.0,
    },
    pbr: { mode: 'grayscale', selected_images: null },
    map_refine: {
      flatten: { enabled: true, strength: 1.0, smoothing: 0 },
      delight: { enabled: true, method: 'gaussian', blur_radius: 200, strength: 1.0 },
      roughness: { scale_factor: 1.0 },
      clone: { operations: [] },
    },
    seamless_tiling: {
      seamless: { method: 'overlay', blend_width: 64, spots_removal: false, color_equalizer: 0 },
      tile_check: 4,
      tiling: { tile_x: 2, tile_y: 2, scale: 1.0, rotation: 0, overlap: 0, half_drop: false, output_resolution: [2048, 2048] },
    },
    validate_export: { albedo_dark_threshold: 30, metal_range: [180, 255] },
  };

  // Handler: revert phase to defaults
  const handleRevertPhase = useCallback(
    (phase: string) => {
      if (phase === 'crop_align' && activeEditor === 'crop') {
        setActiveEditor(null);
      }
      saveParamsMut.mutate(
        { phase, data: { status: 'pending', params: DEFAULT_PHASE_PARAMS[phase] } },
        { onSuccess: () => setPreviewUrl(null) }
      );
    },
    [saveParamsMut, activeEditor]
  );

  if (trackLoading || !track) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-teal-400 animate-spin" />
      </div>
    );
  }

  const phases = track.phases;

  // Phase prerequisites: PBR needs color done, map_refine needs PBR, etc.
  const pbrDisabled = phases.color.status !== 'completed' && phases.color.status !== 'skipped';
  const refineDisabled = phases.pbr.status !== 'completed';
  const seamlessDisabled = phases.pbr.status !== 'completed';
  const validateDisabled = phases.pbr.status !== 'completed';

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800 bg-slate-900/80 shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="flex items-center gap-1 px-2 py-1 text-slate-400 hover:text-white
              rounded-lg hover:bg-slate-800 transition-colors text-sm"
          >
            <ArrowLeft className="w-4 h-4" />
            Back
          </button>
          <div className="w-px h-5 bg-slate-700" />
          <span className="text-sm font-medium text-white">{batchName}</span>
          <span className="text-xs text-slate-500">
            Phase {completedPhases}/{PHASE_NAMES.length}
          </span>
        </div>
      </div>

      {/* Main editor: left preview + right controls */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Image Preview or Crop Canvas */}
        <div className="flex-1 min-w-0">
          {activeEditor === 'crop' ? (
            <CropCanvas
              state={cropEditor.state}
              actions={cropEditor.actions}
              refs={cropEditor.refs}
            />
          ) : (
            <ImagePreview
              imageUrl={previewUrl}
              isLoading={previewLoading}
              label={`${batchName} — pipeline preview`}
              exposureOffset={pendingExposure}
            />
          )}
        </div>

        {/* Right: Phase Controls */}
        <div className="w-80 border-l border-slate-800 overflow-y-auto bg-slate-900/40">
          <div className="p-3 space-y-2">
            <CropAlignCard
              batchName={batchName}
              status={phases.crop_align.status}
              params={phases.crop_align.params}
              onParamsChange={(p) => handlePhaseParamsChange('crop_align', p)}
              isActive={activeEditor === 'crop'}
              onActivate={() => setActiveEditor('crop')}
              onDeactivate={() => setActiveEditor(null)}
              cropState={activeEditor === 'crop' ? cropEditor.state : null}
              cropActions={activeEditor === 'crop' ? cropEditor.actions : null}
              onRevert={() => handleRevertPhase('crop_align')}
            />

            <ColorCard
              batchName={batchName}
              status={phases.color.status}
              params={phases.color.params}
              onParamsChange={(p) => handlePhaseParamsChange('color', p)}
              onPreview={() => debouncedPreview('color')}
              onExposureChange={(offset) => setPendingExposure(offset)}
              onRevert={() => handleRevertPhase('color')}
            />

            <PBRCard
              batchName={batchName}
              status={phases.pbr.status}
              params={phases.pbr.params}
              onParamsChange={(p) => handlePhaseParamsChange('pbr', p)}
              onPreviewReady={(url) => setPreviewUrl(url)}
              disabled={pbrDisabled}
              onRevert={() => handleRevertPhase('pbr')}
            />

            <MapRefineCard
              batchName={batchName}
              status={phases.map_refine.status}
              params={phases.map_refine.params}
              onParamsChange={(p) => handlePhaseParamsChange('map_refine', p)}
              onPreview={() => debouncedPreview('map_refine')}
              disabled={refineDisabled}
              onRevert={() => handleRevertPhase('map_refine')}
            />

            <SeamlessTilingCard
              batchName={batchName}
              status={phases.seamless_tiling.status}
              params={phases.seamless_tiling.params}
              onParamsChange={(p) => handlePhaseParamsChange('seamless_tiling', p)}
              onPreview={() => debouncedPreview('seamless_tiling')}
              disabled={seamlessDisabled}
              onRevert={() => handleRevertPhase('seamless_tiling')}
            />

            <ValidateExportCard
              batchName={batchName}
              status={phases.validate_export.status}
              params={phases.validate_export.params}
              onParamsChange={(p) => handlePhaseParamsChange('validate_export', p)}
              disabled={validateDisabled}
              onRevert={() => handleRevertPhase('validate_export')}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
