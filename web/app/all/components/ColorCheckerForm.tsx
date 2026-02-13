'use client';

import { useState, useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getCameraStatus,
  captureColorChecker,
  detectColorCheckerSwatches,
  flipColorChecker,
  rotateColorChecker,
  saveColorCheckerProfile,
  listColorCheckerProfiles,
  getReferenceSwatches,
  getDetectedSwatches,
  getFullUrl,
  type CameraStatus,
} from '@/lib/api';
import {
  Palette,
  Camera,
  Loader2,
  CheckCircle,
  XCircle,
  FlipHorizontal,
  FlipVertical,
  RotateCcw,
  Save,
  RefreshCw,
  Eye,
} from 'lucide-react';

interface ColorCheckerState {
  imagePath: string | null;
  imageUrl: string | null;
  detectionId: string | null;
  overlayUrl: string | null;
  swatchCount: number;
  flipH: boolean;
  flipV: boolean;
  rotation: number;
  profileName: string;
  status: 'idle' | 'capturing' | 'detecting' | 'detected' | 'saving' | 'error';
  error: string | null;
}

interface Swatch {
  name: string;
  index: number;
  r: number;
  g: number;
  b: number;
  hex: string;
}

export default function ColorCheckerForm() {
  const queryClient = useQueryClient();

  const [state, setState] = useState<ColorCheckerState>({
    imagePath: null,
    imageUrl: null,
    detectionId: null,
    overlayUrl: null,
    swatchCount: 0,
    flipH: false,
    flipV: false,
    rotation: 0,
    profileName: '',
    status: 'idle',
    error: null,
  });

  const [overlayKey, setOverlayKey] = useState(0);
  const [showComparison, setShowComparison] = useState(false);
  const [detectedSwatches, setDetectedSwatches] = useState<Swatch[]>([]);

  const { data: cameraStatus } = useQuery({
    queryKey: ['camera', 'status'],
    queryFn: () => getCameraStatus().then((res) => res.data as CameraStatus),
    refetchInterval: 10000,
  });

  const isConnected = cameraStatus?.connected ?? false;

  const { data: referenceData } = useQuery({
    queryKey: ['colorchecker', 'reference'],
    queryFn: () => getReferenceSwatches().then((res) => res.data),
    enabled: showComparison,
  });

  const { data: profilesData, refetch: refetchProfiles } = useQuery({
    queryKey: ['colorchecker', 'profiles'],
    queryFn: () => listColorCheckerProfiles().then((res) => res.data),
  });

  const captureMutation = useMutation({
    mutationFn: () => captureColorChecker(),
    onMutate: () => {
      setState((s) => ({ ...s, status: 'capturing', error: null }));
    },
    onSuccess: (res) => {
      const data = res.data;
      setState((s) => ({
        ...s,
        imagePath: data.image_path,
        imageUrl: data.image_url,
        status: 'idle',
        detectionId: null,
        overlayUrl: null,
      }));
    },
    onError: (error: any) => {
      setState((s) => ({
        ...s,
        status: 'error',
        error:
          error.response?.data?.detail || error.message || 'Capture failed',
      }));
    },
  });

  const detectMutation = useMutation({
    mutationFn: (imagePath: string) => detectColorCheckerSwatches(imagePath),
    onMutate: () => {
      setState((s) => ({ ...s, status: 'detecting', error: null }));
    },
    onSuccess: (res) => {
      const data = res.data;
      setState((s) => ({
        ...s,
        detectionId: data.detection_id,
        overlayUrl: data.overlay_url,
        swatchCount: data.swatches_detected,
        flipH: data.flip_h,
        flipV: data.flip_v,
        rotation: data.rotation,
        status: 'detected',
      }));
      setOverlayKey((k) => k + 1);
    },
    onError: (error: any) => {
      setState((s) => ({
        ...s,
        status: 'error',
        error:
          error.response?.data?.detail || error.message || 'Detection failed',
      }));
    },
  });

  const flipMutation = useMutation({
    mutationFn: ({
      detectionId,
      axis,
    }: {
      detectionId: string;
      axis: string;
    }) => flipColorChecker(detectionId, axis),
    onSuccess: (res) => {
      const data = res.data;
      setState((s) => ({
        ...s,
        flipH: data.flip_h,
        flipV: data.flip_v,
        rotation: data.rotation,
      }));
      setOverlayKey((k) => k + 1);
    },
  });

  const rotateMutation = useMutation({
    mutationFn: ({
      detectionId,
      degrees,
    }: {
      detectionId: string;
      degrees: number;
    }) => rotateColorChecker(detectionId, degrees),
    onSuccess: (res) => {
      const data = res.data;
      setState((s) => ({
        ...s,
        flipH: data.flip_h,
        flipV: data.flip_v,
        rotation: data.rotation,
      }));
      setOverlayKey((k) => k + 1);
    },
  });

  const saveMutation = useMutation({
    mutationFn: ({
      detectionId,
      name,
    }: {
      detectionId: string;
      name: string;
    }) => saveColorCheckerProfile(detectionId, name),
    onMutate: () => {
      setState((s) => ({ ...s, status: 'saving' }));
    },
    onSuccess: () => {
      setState((s) => ({ ...s, status: 'detected', profileName: '' }));
      refetchProfiles();
      queryClient.invalidateQueries({ queryKey: ['colorchecker', 'profiles'] });
    },
    onError: (error: any) => {
      setState((s) => ({
        ...s,
        status: 'error',
        error:
          error.response?.data?.detail || error.message || 'Save failed',
      }));
    },
  });

  useEffect(() => {
    if (showComparison && state.detectionId) {
      getDetectedSwatches(state.detectionId)
        .then((res) => setDetectedSwatches(res.data.swatches))
        .catch(() => {});
    }
  }, [showComparison, state.detectionId, overlayKey]);

  const handleCapture = () => {
    if (!isConnected) return;
    captureMutation.mutate();
  };

  const handleDetect = () => {
    if (!state.imagePath) return;
    detectMutation.mutate(state.imagePath);
  };

  const handleFlip = (axis: 'horizontal' | 'vertical') => {
    if (!state.detectionId) return;
    flipMutation.mutate({ detectionId: state.detectionId, axis });
  };

  const handleRotate = () => {
    if (!state.detectionId) return;
    rotateMutation.mutate({ detectionId: state.detectionId, degrees: 90 });
  };

  const handleSave = () => {
    if (!state.detectionId || !state.profileName.trim()) return;
    saveMutation.mutate({
      detectionId: state.detectionId,
      name: state.profileName.trim(),
    });
  };

  const isProcessing =
    state.status === 'capturing' ||
    state.status === 'detecting' ||
    state.status === 'saving' ||
    flipMutation.isPending ||
    rotateMutation.isPending;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 relative">
      {/* Processing overlay */}
      {isProcessing && (
        <div className="absolute inset-0 bg-slate-900/80 backdrop-blur-sm rounded-2xl flex items-center justify-center z-10">
          <div className="flex flex-col items-center gap-2">
            <Loader2 className="w-8 h-8 animate-spin text-teal-400" />
            <span className="text-sm font-medium text-white">
              {state.status === 'capturing'
                ? 'Capturing...'
                : state.status === 'detecting'
                  ? 'Detecting swatches...'
                  : state.status === 'saving'
                    ? 'Saving profile...'
                    : 'Processing...'}
            </span>
          </div>
        </div>
      )}

      <div className="flex items-center gap-2 mb-4">
        <Palette className="w-5 h-5 text-teal-400" />
        <h2 className="text-base font-semibold text-white">Color Checker</h2>
        <span className="ml-auto text-xs text-slate-500">
          {state.status === 'detected'
            ? `${state.swatchCount} swatches`
            : 'Calibrate colors'}
        </span>
      </div>

      <div className="space-y-3">
        {/* Image Preview */}
        <div className="relative aspect-video bg-slate-950 rounded-xl overflow-hidden border border-slate-800">
          {state.overlayUrl ? (
            <img
              key={overlayKey}
              src={getFullUrl(state.overlayUrl)}
              alt="Color Checker with detected swatches"
              className="w-full h-full object-contain"
            />
          ) : state.imageUrl ? (
            <img
              src={getFullUrl(state.imageUrl)}
              alt="Captured Color Checker"
              className="w-full h-full object-contain"
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center text-slate-500">
              <div className="text-center">
                <Camera className="w-10 h-10 mx-auto mb-2 opacity-50" />
                <p className="text-xs">Capture a Color Checker image</p>
              </div>
            </div>
          )}
        </div>

        {/* Status */}
        {state.status === 'detected' && (
          <div className="flex items-center gap-2 text-xs">
            <CheckCircle className="w-3.5 h-3.5 text-teal-400" />
            <span className="text-teal-300">
              Detected {state.swatchCount} swatches
              {state.flipH && ' (H-Flipped)'}
              {state.flipV && ' (V-Flipped)'}
              {state.rotation > 0 && ` (Rotated ${state.rotation}°)`}
            </span>
          </div>
        )}

        {state.error && (
          <div className="flex items-center gap-2 text-xs p-2 bg-red-500/10 border border-red-500/30 rounded-lg">
            <XCircle className="w-3.5 h-3.5 text-red-400" />
            <span className="text-red-300">{state.error}</span>
          </div>
        )}

        {/* Capture Button */}
        <button
          onClick={handleCapture}
          disabled={!isConnected || isProcessing}
          className={`w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
            !isConnected || isProcessing
              ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
              : 'bg-teal-600 text-white hover:bg-teal-500'
          }`}
        >
          <Camera className="w-4 h-4" />
          Capture Color Checker
        </button>

        {/* Detect Button */}
        {state.imagePath && !state.detectionId && (
          <button
            onClick={handleDetect}
            disabled={isProcessing}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-teal-600 text-white rounded-lg text-sm font-medium hover:bg-teal-500 transition-colors"
          >
            <Eye className="w-4 h-4" />
            Detect Swatches
          </button>
        )}

        {/* Adjustment Controls */}
        {state.detectionId && (
          <div className="space-y-3">
            <div className="text-xs font-medium text-slate-400 uppercase tracking-wide">
              Adjustments
            </div>
            <div className="grid grid-cols-3 gap-2">
              <button
                onClick={() => handleFlip('horizontal')}
                disabled={isProcessing}
                className={`flex items-center justify-center gap-1 px-2 py-1.5 rounded-lg text-xs transition-colors ${
                  state.flipH
                    ? 'bg-teal-500/20 text-teal-400 border border-teal-500/30'
                    : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                }`}
              >
                <FlipHorizontal className="w-3.5 h-3.5" />
                Flip H
              </button>
              <button
                onClick={() => handleFlip('vertical')}
                disabled={isProcessing}
                className={`flex items-center justify-center gap-1 px-2 py-1.5 rounded-lg text-xs transition-colors ${
                  state.flipV
                    ? 'bg-teal-500/20 text-teal-400 border border-teal-500/30'
                    : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                }`}
              >
                <FlipVertical className="w-3.5 h-3.5" />
                Flip V
              </button>
              <button
                onClick={handleRotate}
                disabled={isProcessing}
                className="flex items-center justify-center gap-1 px-2 py-1.5 bg-slate-800 text-slate-300 rounded-lg text-xs hover:bg-slate-700 transition-colors"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Rotate
              </button>
            </div>

            {/* Save Profile */}
            <div className="pt-2 border-t border-slate-800">
              <label className="block text-xs text-slate-400 mb-1">
                Profile Name
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={state.profileName}
                  onChange={(e) =>
                    setState((s) => ({ ...s, profileName: e.target.value }))
                  }
                  placeholder="my_calibration"
                  className="flex-1 px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none"
                />
                <button
                  onClick={handleSave}
                  disabled={!state.profileName.trim() || isProcessing}
                  className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    !state.profileName.trim() || isProcessing
                      ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                      : 'bg-teal-600 text-white hover:bg-teal-500'
                  }`}
                >
                  <Save className="w-3.5 h-3.5" />
                  Save
                </button>
              </div>
            </div>

            {/* Comparison toggle */}
            <button
              onClick={() => setShowComparison(!showComparison)}
              className="w-full flex items-center justify-center gap-2 px-3 py-1.5 bg-slate-800 text-slate-300 rounded-lg text-xs hover:bg-slate-700 transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              {showComparison ? 'Hide' : 'Show'} Reference Comparison
            </button>
          </div>
        )}

        {/* Reference Comparison */}
        {showComparison && state.detectionId && referenceData && (
          <div className="space-y-2 pt-2 border-t border-slate-800">
            <div className="text-xs font-medium text-slate-400 uppercase tracking-wide">
              Color Comparison
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-[10px] text-slate-500 mb-1">
                  Detected (Camera)
                </div>
                <div className="grid grid-cols-6 gap-0.5">
                  {detectedSwatches.slice(0, 24).map((swatch) => (
                    <div
                      key={swatch.index}
                      className="aspect-square rounded-sm"
                      style={{ backgroundColor: swatch.hex }}
                      title={`${swatch.name}: ${swatch.hex}`}
                    />
                  ))}
                </div>
              </div>
              <div>
                <div className="text-[10px] text-slate-500 mb-1">
                  Reference (Standard)
                </div>
                <div className="grid grid-cols-6 gap-0.5">
                  {referenceData.swatches?.slice(0, 24).map((swatch: Swatch) => (
                    <div
                      key={swatch.index}
                      className="aspect-square rounded-sm"
                      style={{ backgroundColor: swatch.hex }}
                      title={`${swatch.name}: ${swatch.hex}`}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Saved Profiles */}
        {profilesData?.profiles?.length > 0 && (
          <div className="pt-2 border-t border-slate-800">
            <div className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-1.5">
              Saved Profiles ({profilesData.profiles.length})
            </div>
            <div className="space-y-1 max-h-24 overflow-y-auto">
              {profilesData.profiles.map(
                (profile: {
                  name: string;
                  created_at: string;
                  source_image: string;
                }) => (
                  <div
                    key={profile.name}
                    className="flex items-center justify-between px-2 py-1 bg-slate-800/50 rounded text-xs"
                  >
                    <span className="font-medium text-slate-300">
                      {profile.name}
                    </span>
                    <span className="text-slate-500">
                      {new Date(profile.created_at).toLocaleDateString()}
                    </span>
                  </div>
                )
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
