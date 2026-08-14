'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  RefreshCw, Crop, Palette, Layers, ChevronRight,
  CheckCircle2, Clock, Loader2, Camera, Image as ImageIcon,
  Settings, FolderOpen, AlertCircle, X, Check, Wand2, Move
} from 'lucide-react';
import {
  getBatches, getBatchesSummary, getBatch, syncAllBatches,
  updateBatchCrop, updateBatchCalibration, updateBatchPBR,
  updatePBRSelection, getMediaUrl, getFullUrl,
  getTopImageForCrop, autoDetectCrop, previewManualCrop, applyCrop,
  calibrateBatch, getColorCheckerProfiles,
  generatePBR, getPostCaptureJobs,
  Batch, BatchSummary, BatchImage, CropPoint
} from '@/lib/api';
import CropEditor from './components/CropEditor';
import dynamic from 'next/dynamic';

const DashboardHeader = dynamic(() => import('../all/components/DashboardHeader'), {
  ssr: false,
});

type Phase = 'crop' | 'calibration' | 'pbr';
type Status = 'pending' | 'in_progress' | 'completed';

const phaseConfig = {
  crop: { label: 'Cropping', icon: Crop, color: 'teal' },
  calibration: { label: 'Color Calibration', icon: Palette, color: 'violet' },
  pbr: { label: 'PBR Generation', icon: Layers, color: 'amber' },
};

const statusConfig: Record<Status, { label: string; icon: any; color: string; animate?: boolean }> = {
  pending: { label: 'Pending', icon: Clock, color: 'slate' },
  in_progress: { label: 'In Progress', icon: Loader2, color: 'blue', animate: true },
  completed: { label: 'Completed', icon: CheckCircle2, color: 'green' },
};

export default function ProcessingPage() {
  const router = useRouter();
  const [batches, setBatches] = useState<Batch[]>([]);
  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Detail view
  const [selectedBatch, setSelectedBatch] = useState<Batch | null>(null);
  const [batchImages, setBatchImages] = useState<BatchImage[]>([]);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Filters
  const [filterPhase, setFilterPhase] = useState<Phase | 'all'>('all');
  const [filterStatus, setFilterStatus] = useState<Status | 'all'>('all');

  // Processing modals
  const [showCropModal, setShowCropModal] = useState(false);
  const [showCalibrationModal, setShowCalibrationModal] = useState(false);
  const [showPBRModal, setShowPBRModal] = useState(false);

  // Processing state
  const [processing, setProcessing] = useState<string | null>(null);
  const [processResult, setProcessResult] = useState<{ success: boolean; message: string } | null>(null);

  // Interactive Crop State
  const [cropStep, setCropStep] = useState<'select' | 'preview' | 'applying'>('select');
  const [topImage, setTopImage] = useState<{
    thumbnail_url: string;
    width: number;
    height: number;
    filename: string;
  } | null>(null);
  const [cropBbox, setCropBbox] = useState<number[]>([0, 0, 0, 0]);
  const [cropPreview, setCropPreview] = useState<string | null>(null);
  const [cropMethod, setCropMethod] = useState<'manual' | 'auto'>('manual');
  const [isDrawing, setIsDrawing] = useState(false);
  const [drawStart, setDrawStart] = useState({ x: 0, y: 0 });
  const imageRef = useRef<HTMLImageElement>(null);

  // Calibration settings
  const [profiles, setProfiles] = useState<{ name: string; path: string }[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<string>('');

  // PBR settings
  const [pbrMode, setPbrMode] = useState<'grayscale' | 'colored' | 'both'>('grayscale');

  // Post-capture background jobs
  const [postCaptureJobs, setPostCaptureJobs] = useState<Record<string, any>>({});

  const fetchData = useCallback(async () => {
    try {
      const [batchRes, summaryRes] = await Promise.all([
        getBatches(),
        getBatchesSummary(),
      ]);
      setBatches(batchRes.data.batches);
      setSummary(summaryRes.data);
      setError(null);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchPostCaptureJobs = useCallback(async () => {
    try {
      const res = await getPostCaptureJobs();
      setPostCaptureJobs(res.data || {});
    } catch {
      // ignore — endpoint may not exist yet
    }
  }, []);

  useEffect(() => {
    fetchData();
    fetchPostCaptureJobs();
  }, [fetchData, fetchPostCaptureJobs]);

  // Poll post-capture jobs while any are active
  useEffect(() => {
    const hasActive = Object.values(postCaptureJobs).some(
      (j: any) => j.status === 'pending' || j.status === 'processing'
    );
    if (!hasActive) return;
    const interval = setInterval(fetchPostCaptureJobs, 3000);
    return () => clearInterval(interval);
  }, [postCaptureJobs, fetchPostCaptureJobs]);

  // Global navigation shortcuts
  useEffect(() => {
    const handleNavKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      switch (e.key) {
        case 'd':
          router.push('/');
          break;
        case 'g':
          router.push('/gallery');
          break;
        case 'p':
          // already on processing
          break;
      }
    };

    window.addEventListener('keydown', handleNavKey);
    return () => window.removeEventListener('keydown', handleNavKey);
  }, [router]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await syncAllBatches();
      await fetchData();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Sync failed');
    } finally {
      setSyncing(false);
    }
  };

  const openBatchDetail = async (batch: Batch) => {
    setSelectedBatch(batch);
    setLoadingDetail(true);
    try {
      const res = await getBatch(batch.name);
      setBatchImages(res.data.images);
    } catch (err: any) {
      console.error('Failed to load batch detail:', err);
    } finally {
      setLoadingDetail(false);
    }
  };

  const closeBatchDetail = () => {
    setSelectedBatch(null);
    setBatchImages([]);
  };

  const handlePBRSelectionToggle = async (image: BatchImage) => {
    if (!selectedBatch) return;
    const newSelected = !image.pbr_selected;
    try {
      await updatePBRSelection(selectedBatch.name, image.filename, newSelected);
      setBatchImages(prev =>
        prev.map(img =>
          img.id === image.id ? { ...img, pbr_selected: newSelected ? 1 : 0 } : img
        )
      );
    } catch (err) {
      console.error('Failed to update PBR selection:', err);
    }
  };

  // Load calibration profiles
  const loadProfiles = async () => {
    try {
      const res = await getColorCheckerProfiles();
      setProfiles(res.data.profiles || []);
    } catch (err) {
      console.error('Failed to load profiles:', err);
    }
  };

  // ─── Interactive Crop Handlers ───

  const openCropModal = async () => {
    if (!selectedBatch) return;
    setShowCropModal(true);
    setCropStep('select');
    setCropPreview(null);
    setCropBbox([0, 0, 0, 0]);
    setProcessing('loading');

    try {
      const res = await getTopImageForCrop(selectedBatch.name);
      setTopImage(res.data);
      // Initialize bbox to center 60% of image
      const w = res.data.width;
      const h = res.data.height;
      setCropBbox([
        Math.round(w * 0.2),
        Math.round(h * 0.2),
        Math.round(w * 0.8),
        Math.round(h * 0.8),
      ]);
    } catch (err: any) {
      setProcessResult({
        success: false,
        message: err.response?.data?.detail || 'Failed to load image',
      });
      setShowCropModal(false);
    } finally {
      setProcessing(null);
    }
  };

  const handleAutoDetect = async () => {
    if (!selectedBatch) return;
    setProcessing('auto-detect');

    try {
      const res = await autoDetectCrop(selectedBatch.name);
      if (res.data.success) {
        setCropBbox(res.data.bbox);
        setCropPreview(res.data.preview_url);
        setCropMethod('auto');
        setCropStep('preview');
      } else {
        setProcessResult({
          success: false,
          message: res.data.error || 'Auto-detect failed. Try manual crop.',
        });
      }
    } catch (err: any) {
      setProcessResult({
        success: false,
        message: err.response?.data?.detail || 'Auto-detect failed',
      });
    } finally {
      setProcessing(null);
    }
  };

  const handlePreviewManualCrop = async () => {
    if (!selectedBatch || cropBbox[2] - cropBbox[0] < 10 || cropBbox[3] - cropBbox[1] < 10) {
      setProcessResult({
        success: false,
        message: 'Please draw a crop region first',
      });
      return;
    }
    setProcessing('preview');

    try {
      const res = await previewManualCrop(selectedBatch.name, cropBbox);
      if (res.data.success) {
        setCropBbox(res.data.bbox);
        setCropPreview(res.data.preview_url);
        setCropMethod('manual');
        setCropStep('preview');
      } else {
        setProcessResult({
          success: false,
          message: res.data.error || 'Preview failed',
        });
      }
    } catch (err: any) {
      setProcessResult({
        success: false,
        message: err.response?.data?.detail || 'Preview failed',
      });
    } finally {
      setProcessing(null);
    }
  };

  const handleAcceptCrop = async () => {
    if (!selectedBatch) return;
    setCropStep('applying');
    setProcessing('crop');

    try {
      const res = await applyCrop(selectedBatch.name, cropMethod, { bbox: cropBbox });
      if (res.data.success) {
        setProcessResult({
          success: true,
          message: `Cropped ${res.data.processed}/${res.data.total} images (${res.data.crop_type})`,
        });
        // Refresh data
        await fetchData();
        if (selectedBatch) {
          await openBatchDetail(selectedBatch);
        }
        setShowCropModal(false);
      } else {
        setProcessResult({
          success: false,
          message: 'Crop failed',
        });
        setCropStep('preview');
      }
    } catch (err: any) {
      setProcessResult({
        success: false,
        message: err.response?.data?.detail || 'Crop failed',
      });
      setCropStep('preview');
    } finally {
      setProcessing(null);
    }
  };

  const handleRejectCrop = () => {
    setCropStep('select');
    setCropPreview(null);
  };

  // Mouse handlers for drawing crop box
  const getImageCoords = (e: React.MouseEvent) => {
    if (!imageRef.current || !topImage) return { x: 0, y: 0 };
    const rect = imageRef.current.getBoundingClientRect();
    const scaleX = topImage.width / rect.width;
    const scaleY = topImage.height / rect.height;
    return {
      x: Math.round((e.clientX - rect.left) * scaleX),
      y: Math.round((e.clientY - rect.top) * scaleY),
    };
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    const coords = getImageCoords(e);
    setDrawStart(coords);
    setIsDrawing(true);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDrawing) return;
    const coords = getImageCoords(e);
    setCropBbox([
      Math.min(drawStart.x, coords.x),
      Math.min(drawStart.y, coords.y),
      Math.max(drawStart.x, coords.x),
      Math.max(drawStart.y, coords.y),
    ]);
  };

  const handleMouseUp = () => {
    setIsDrawing(false);
  };

  // Calculate crop box display position
  const getCropBoxStyle = () => {
    if (!imageRef.current || !topImage) return {};
    const rect = imageRef.current.getBoundingClientRect();
    const scaleX = rect.width / topImage.width;
    const scaleY = rect.height / topImage.height;
    return {
      left: cropBbox[0] * scaleX,
      top: cropBbox[1] * scaleY,
      width: (cropBbox[2] - cropBbox[0]) * scaleX,
      height: (cropBbox[3] - cropBbox[1]) * scaleY,
    };
  };

  // ─── Other Processing Handlers ───

  const handleStartCalibration = async () => {
    if (!selectedBatch) return;
    setProcessing('calibration');
    setProcessResult(null);

    try {
      const res = await calibrateBatch(selectedBatch.name, selectedProfile || undefined);
      const data = res.data;

      setProcessResult({
        success: data.success,
        message: `Calibrated ${data.processed}/${data.total} images`,
      });

      await fetchData();
      if (selectedBatch) {
        await openBatchDetail(selectedBatch);
      }
    } catch (err: any) {
      setProcessResult({
        success: false,
        message: err.response?.data?.detail || 'Calibration failed',
      });
    } finally {
      setProcessing(null);
      setShowCalibrationModal(false);
    }
  };

  const handleStartPBR = async () => {
    if (!selectedBatch) return;
    setProcessing('pbr');
    setProcessResult(null);

    try {
      const selectedImages = batchImages
        .filter(img => img.pbr_selected)
        .map(img => img.filename);

      const res = await generatePBR(
        selectedBatch.name,
        pbrMode,
        selectedImages.length > 0 ? selectedImages : undefined
      );
      const data = res.data;

      setProcessResult({
        success: data.success,
        message: data.success
          ? `Generated ${pbrMode} PBR maps (${data.images_processed} images)`
          : data.error,
      });

      await fetchData();
      if (selectedBatch) {
        await openBatchDetail(selectedBatch);
      }
    } catch (err: any) {
      setProcessResult({
        success: false,
        message: err.response?.data?.detail || 'PBR generation failed',
      });
    } finally {
      setProcessing(null);
      setShowPBRModal(false);
    }
  };

  const getStatusBadge = (status: Status) => {
    const config = statusConfig[status];
    const Icon = config.icon;
    return (
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium
        ${status === 'pending' ? 'bg-slate-100 text-slate-600' : ''}
        ${status === 'in_progress' ? 'bg-blue-100 text-blue-700' : ''}
        ${status === 'completed' ? 'bg-green-100 text-green-700' : ''}
      `}>
        <Icon className={`w-3 h-3 ${config.animate ? 'animate-spin' : ''}`} />
        {config.label}
      </span>
    );
  };

  const filteredBatches = batches.filter(batch => {
    if (filterPhase !== 'all' && filterStatus !== 'all') {
      const statusKey = `${filterPhase}_status` as keyof Batch;
      return batch[statusKey] === filterStatus;
    }
    if (filterPhase !== 'all') {
      return true;
    }
    if (filterStatus !== 'all') {
      return (
        batch.crop_status === filterStatus ||
        batch.calibration_status === filterStatus ||
        batch.pbr_status === filterStatus
      );
    }
    return true;
  });

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950">
        <DashboardHeader />
        <div className="flex items-center justify-center py-24">
          <Loader2 className="w-8 h-8 animate-spin text-teal-400" />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* Shared Nav */}
      <div className="sticky top-0 z-10">
        <DashboardHeader />
      </div>

      {/* Processing sub-header */}
      <div className="border-b border-slate-800 bg-slate-900/60">
        <div className="max-w-7xl mx-auto px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">Processing Pipeline</h2>
              <p className="text-sm text-slate-400">
                {summary?.total_batches || 0} batches
              </p>
            </div>
            <button
              onClick={handleSync}
              disabled={syncing}
              className="flex items-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-xl hover:bg-teal-700 disabled:opacity-50 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
              {syncing ? 'Syncing...' : 'Sync'}
            </button>
          </div>
        </div>
      </div>

      <main className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        {error && (
          <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-2xl flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-red-400" />
            <span className="text-red-400">{error}</span>
          </div>
        )}

        {/* Summary Cards */}
        {summary && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
            {(Object.keys(phaseConfig) as Phase[]).map((phase) => {
              const config = phaseConfig[phase];
              const Icon = config.icon;
              const stats = summary[phase];
              const total = stats.pending + stats.in_progress + stats.completed;
              const progress = total > 0 ? (stats.completed / total) * 100 : 0;

              return (
                <div
                  key={phase}
                  className="bg-slate-900 border border-slate-800 rounded-2xl p-5 cursor-pointer hover:border-teal-500/50 transition-colors"
                  onClick={() => {
                    setFilterPhase(phase);
                    setFilterStatus('all');
                  }}
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <div className={`p-2 rounded-xl bg-${config.color}-500/20`}>
                        <Icon className={`w-5 h-5 text-${config.color}-400`} />
                      </div>
                      <span className="font-medium text-slate-200">{config.label}</span>
                    </div>
                    <span className="text-sm text-slate-400">
                      {stats.completed}/{total}
                    </span>
                  </div>

                  <div className="h-2 bg-slate-800 rounded-full overflow-hidden mb-3">
                    <div
                      className="h-full bg-teal-500 transition-all"
                      style={{ width: `${progress}%` }}
                    />
                  </div>

                  <div className="flex gap-3 text-xs">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setFilterPhase(phase);
                        setFilterStatus('pending');
                      }}
                      className="text-slate-400 hover:text-slate-200"
                    >
                      {stats.pending} pending
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setFilterPhase(phase);
                        setFilterStatus('in_progress');
                      }}
                      className="text-blue-400 hover:text-blue-300"
                    >
                      {stats.in_progress} active
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setFilterPhase(phase);
                        setFilterStatus('completed');
                      }}
                      className="text-green-400 hover:text-green-300"
                    >
                      {stats.completed} done
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Post-capture background jobs */}
        {Object.keys(postCaptureJobs).length > 0 && (
          <div className="mb-6 bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
              <Palette className="w-4 h-4 text-violet-400" />
              <span className="text-sm font-medium text-slate-200">Calibrate &amp; Crop Jobs</span>
            </div>
            <div className="divide-y divide-slate-800">
              {Object.entries(postCaptureJobs).map(([batch, job]: [string, any]) => (
                <div key={batch} className="px-4 py-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <FolderOpen className="w-4 h-4 text-slate-500" />
                    <span className="text-sm font-medium text-slate-200">{batch}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    {job.status === 'processing' && (
                      <span className="text-xs text-slate-400">
                        {job.current_step === 'calibrating_top'
                          ? 'Calibrating top image...'
                          : job.current_step === 'detecting_boundary'
                            ? 'Detecting fabric boundary...'
                            : job.current_step === 'cropping_top'
                              ? 'Cropping top image...'
                              : job.current_step === 'saving_calibration'
                                ? 'Saving calibration params...'
                                : job.current_step}
                      </span>
                    )}
                    {job.status === 'completed' && (
                      <span className="text-xs text-slate-400">
                        Top calibrated + cropped, rest on-demand
                      </span>
                    )}
                    {job.status === 'failed' && (
                      <span className="text-xs text-red-400 max-w-[200px] truncate" title={job.error}>
                        {job.error}
                      </span>
                    )}
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                      job.status === 'completed'
                        ? 'bg-green-100 text-green-700'
                        : job.status === 'failed'
                          ? 'bg-red-100 text-red-700'
                          : job.status === 'processing'
                            ? 'bg-blue-100 text-blue-700'
                            : 'bg-slate-100 text-slate-600'
                    }`}>
                      {(job.status === 'pending' || job.status === 'processing') && (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      )}
                      {job.status === 'completed' && (
                        <CheckCircle2 className="w-3 h-3" />
                      )}
                      {job.status === 'failed' && (
                        <AlertCircle className="w-3 h-3" />
                      )}
                      {job.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="flex items-center gap-4 mb-6">
          <span className="text-sm text-slate-400">Filter:</span>
          <div className="flex gap-2">
            <button
              onClick={() => { setFilterPhase('all'); setFilterStatus('all'); }}
              className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
                filterPhase === 'all' && filterStatus === 'all'
                  ? 'bg-teal-600/20 text-teal-400'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
              }`}
            >
              All
            </button>
            {(Object.keys(phaseConfig) as Phase[]).map((phase) => (
              <button
                key={phase}
                onClick={() => { setFilterPhase(phase); setFilterStatus('all'); }}
                className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
                  filterPhase === phase
                    ? 'bg-teal-600/20 text-teal-400'
                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                }`}
              >
                {phaseConfig[phase].label}
              </button>
            ))}
          </div>
          {filterStatus !== 'all' && (
            <span className="text-sm text-slate-500">
              → {statusConfig[filterStatus].label}
            </span>
          )}
        </div>

        {/* Batch List */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
          <table className="w-full">
            <thead className="bg-slate-800/50 border-b border-slate-700">
              <tr>
                <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Batch</th>
                <th className="text-center px-4 py-3 text-sm font-medium text-slate-400">Images</th>
                <th className="text-center px-4 py-3 text-sm font-medium text-slate-400">
                  <Crop className="w-4 h-4 inline mr-1" />
                  Crop
                </th>
                <th className="text-center px-4 py-3 text-sm font-medium text-slate-400">
                  <Palette className="w-4 h-4 inline mr-1" />
                  Calibration
                </th>
                <th className="text-center px-4 py-3 text-sm font-medium text-slate-400">
                  <Layers className="w-4 h-4 inline mr-1" />
                  PBR
                </th>
                <th className="text-right px-4 py-3 text-sm font-medium text-slate-400">Synced</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {filteredBatches.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-slate-500">
                    No batches found
                  </td>
                </tr>
              ) : (
                filteredBatches.map((batch) => (
                  <tr
                    key={batch.id}
                    className="hover:bg-slate-800/50 cursor-pointer transition-colors"
                    onClick={() => openBatchDetail(batch)}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <FolderOpen className="w-4 h-4 text-slate-500" />
                        <span className="font-medium text-slate-200">{batch.name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-center text-sm text-slate-400">
                      {batch.image_count}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {getStatusBadge(batch.crop_status)}
                      {batch.crop_type && (
                        <span className="ml-1 text-xs text-slate-500">({batch.crop_type})</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {getStatusBadge(batch.calibration_status)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {getStatusBadge(batch.pbr_status)}
                      {batch.pbr_mode && (
                        <span className="ml-1 text-xs text-slate-500">({batch.pbr_mode})</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-500">
                      {formatDate(batch.synced_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <ChevronRight className="w-4 h-4 text-slate-500" />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </main>

      {/* Process Result Toast */}
      {processResult && (
        <div className={`fixed bottom-4 right-4 z-[70] px-6 py-4 rounded-2xl shadow-lg flex items-center gap-3 ${
          processResult.success ? 'bg-green-600 text-white' : 'bg-red-600 text-white'
        }`}>
          {processResult.success ? (
            <CheckCircle2 className="w-5 h-5" />
          ) : (
            <AlertCircle className="w-5 h-5" />
          )}
          <span>{processResult.message}</span>
          <button onClick={() => setProcessResult(null)} className="ml-2 hover:opacity-80">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Interactive Crop Modal with 4-point selection and rotation */}
      {showCropModal && selectedBatch && topImage && (
        <div className="fixed inset-0 z-[60] bg-black/80 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-5xl h-[90vh] overflow-hidden flex flex-col">
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700 shrink-0">
              <div>
                <h2 className="text-lg font-semibold text-white">
                  Crop Images - {selectedBatch.name}
                </h2>
                <p className="text-sm text-slate-400">
                  Click 4 corners (1→2→3→4) or drag points. Use rotation slider for precise angle.
                </p>
              </div>
              <button
                onClick={() => setShowCropModal(false)}
                className="p-2 rounded-lg hover:bg-slate-800 transition-colors"
                disabled={processing === 'crop'}
              >
                <X className="w-5 h-5 text-slate-400" />
              </button>
            </div>

            {/* Crop Editor */}
            <div className="flex-1 overflow-hidden">
              <CropEditor
                imageUrl={getFullUrl(topImage.thumbnail_url)}
                originalWidth={topImage.width}
                originalHeight={topImage.height}
                isProcessing={processing === 'crop'}
                onCancel={() => setShowCropModal(false)}
                onAutoDetect={async (cropSize: number) => {
                  try {
                    const res = await autoDetectCrop(selectedBatch.name, cropSize);
                    if (res.data.success && res.data.bbox) {
                      // Convert bbox to 4 points
                      const [x1, y1, x2, y2] = res.data.bbox;
                      return {
                        success: true,
                        points: [
                          { x: x1, y: y1 },
                          { x: x2, y: y1 },
                          { x: x2, y: y2 },
                          { x: x1, y: y2 },
                        ],
                      };
                    }
                    return { success: false, error: res.data.error || 'Auto-detect failed' };
                  } catch (err: any) {
                    return { success: false, error: err.message || 'Auto-detect failed' };
                  }
                }}
                onApply={async (data) => {
                  setProcessing('crop');
                  try {
                    const res = await applyCrop(selectedBatch.name, data.method, {
                      points: data.points,
                      rotation: data.rotation,
                    });
                    if (res.data.success) {
                      setProcessResult({
                        success: true,
                        message: `Cropped ${res.data.processed}/${res.data.total} images (${data.method}${data.rotation !== 0 ? `, rotated ${data.rotation.toFixed(1)}°` : ''})`,
                      });
                      await fetchData();
                      if (selectedBatch) {
                        await openBatchDetail(selectedBatch);
                      }
                      setShowCropModal(false);
                    } else {
                      setProcessResult({
                        success: false,
                        message: 'Crop failed',
                      });
                    }
                  } catch (err: any) {
                    setProcessResult({
                      success: false,
                      message: err.response?.data?.detail || 'Crop failed',
                    });
                  } finally {
                    setProcessing(null);
                  }
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Calibration Modal */}
      {showCalibrationModal && selectedBatch && (
        <div className="fixed inset-0 z-[60] bg-black/60 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md p-6">
            <h3 className="text-lg font-semibold text-white mb-4">
              Color Calibration - {selectedBatch.name}
            </h3>

            <div className="mb-4">
              <label className="block text-sm font-medium text-slate-300 mb-2">
                ColorChecker Profile
              </label>
              {profiles.length > 0 ? (
                <select
                  value={selectedProfile}
                  onChange={(e) => setSelectedProfile(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200"
                >
                  <option value="">Select a profile...</option>
                  {profiles.map((p) => (
                    <option key={p.name} value={p.name}>{p.name}</option>
                  ))}
                </select>
              ) : (
                <p className="text-sm text-slate-400 p-3 bg-slate-800 rounded-lg">
                  No ColorChecker profiles found. Create one by detecting a ColorChecker in an image first.
                </p>
              )}
            </div>

            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setShowCalibrationModal(false)}
                className="px-4 py-2 bg-slate-800 text-slate-300 rounded-xl hover:bg-slate-700"
              >
                Cancel
              </button>
              <button
                onClick={handleStartCalibration}
                disabled={processing !== null || !selectedProfile}
                className="px-4 py-2 bg-violet-600 text-white rounded-xl hover:bg-violet-700 disabled:opacity-50"
              >
                {processing === 'calibration' ? (
                  <><Loader2 className="w-4 h-4 inline mr-2 animate-spin" />Processing...</>
                ) : (
                  'Run Calibration'
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* PBR Modal */}
      {showPBRModal && selectedBatch && (
        <div className="fixed inset-0 z-[60] bg-black/60 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md p-6">
            <h3 className="text-lg font-semibold text-white mb-4">
              PBR Generation - {selectedBatch.name}
            </h3>

            <div className="mb-4">
              <label className="block text-sm font-medium text-slate-300 mb-2">Mode</label>
              <div className="space-y-2">
                {(['grayscale', 'colored', 'both'] as const).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setPbrMode(mode)}
                    className={`w-full px-4 py-3 rounded-xl text-left transition-colors ${
                      pbrMode === mode
                        ? 'bg-amber-500/20 text-amber-400 border-2 border-amber-500'
                        : 'bg-slate-800 text-slate-300 border-2 border-transparent hover:bg-slate-700'
                    }`}
                  >
                    <span className="font-medium capitalize">{mode}</span>
                    <p className="text-xs mt-1 opacity-70">
                      {mode === 'grayscale' && 'Faster processing, works well for most materials'}
                      {mode === 'colored' && 'Preserves color information in albedo map'}
                      {mode === 'both' && 'Generate both grayscale and colored PBR maps'}
                    </p>
                  </button>
                ))}
              </div>
            </div>

            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setShowPBRModal(false)}
                className="px-4 py-2 bg-slate-800 text-slate-300 rounded-xl hover:bg-slate-700"
              >
                Cancel
              </button>
              <button
                onClick={handleStartPBR}
                disabled={processing !== null}
                className="px-4 py-2 bg-amber-600 text-white rounded-xl hover:bg-amber-700 disabled:opacity-50"
              >
                {processing === 'pbr' ? (
                  <><Loader2 className="w-4 h-4 inline mr-2 animate-spin" />Generating...</>
                ) : (
                  'Generate PBR'
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Batch Detail Modal */}
      {selectedBatch && !showCropModal && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
              <div>
                <h2 className="text-lg font-semibold text-white">{selectedBatch.name}</h2>
                <p className="text-sm text-slate-400">
                  {selectedBatch.image_count} images • Created {formatDate(selectedBatch.created_at)}
                </p>
              </div>
              <button
                onClick={closeBatchDetail}
                className="p-2 rounded-lg hover:bg-slate-800 transition-colors"
              >
                <X className="w-5 h-5 text-slate-400" />
              </button>
            </div>

            {/* Phase Status */}
            <div className="px-6 py-4 bg-slate-800/50 border-b border-slate-700">
              <div className="flex gap-6">
                <div className="flex items-center gap-2">
                  <Crop className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-slate-300">Crop:</span>
                  {getStatusBadge(selectedBatch.crop_status)}
                  {selectedBatch.crop_type && (
                    <span className="text-xs text-slate-500">({selectedBatch.crop_type})</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <Palette className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-slate-300">Calibration:</span>
                  {getStatusBadge(selectedBatch.calibration_status)}
                </div>
                <div className="flex items-center gap-2">
                  <Layers className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-slate-300">PBR:</span>
                  {getStatusBadge(selectedBatch.pbr_status)}
                  {selectedBatch.pbr_mode && (
                    <span className="text-xs text-slate-500">({selectedBatch.pbr_mode})</span>
                  )}
                </div>
              </div>
            </div>

            {/* Images Grid */}
            <div className="flex-1 overflow-auto p-6">
              {loadingDetail ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-6 h-6 animate-spin text-teal-400" />
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-4">
                  {batchImages.map((image) => (
                    <div
                      key={image.id}
                      className="border border-slate-700 rounded-xl overflow-hidden bg-slate-800/50"
                    >
                      {/* Thumbnail - show cropped_thumbnail after crop is completed */}
                      <div className="aspect-square bg-slate-800 relative">
                        <img
                          src={`${getMediaUrl(`${selectedBatch.name}/${selectedBatch.crop_status === 'completed' ? 'cropped_thumbnail' : 'thumbnail'}/${image.filename.replace(/\.[^.]+$/, '.jpg')}`)}?t=${selectedBatch.crop_completed_at || ''}`}
                          alt={image.filename}
                          className="w-full h-full object-cover"
                          onError={(e) => {
                            e.currentTarget.style.display = 'none';
                          }}
                        />
                        {/* Position badge */}
                        <span className="absolute top-2 left-2 px-2 py-0.5 bg-black/60 text-white text-xs rounded-full">
                          {image.position}
                        </span>
                        {/* PBR Selection toggle */}
                        <button
                          onClick={() => handlePBRSelectionToggle(image)}
                          className={`absolute top-2 right-2 p-1 rounded-full transition-colors ${
                            image.pbr_selected
                              ? 'bg-teal-500 text-white'
                              : 'bg-slate-700/80 text-slate-400 hover:bg-slate-600'
                          }`}
                          title={image.pbr_selected ? 'Selected for PBR' : 'Excluded from PBR'}
                        >
                          <Check className="w-4 h-4" />
                        </button>
                        {/* Status indicators */}
                        <div className="absolute bottom-2 left-2 flex gap-1">
                          {image.is_cropped ? (
                            <span className="p-1 bg-green-500 rounded-full" title="Cropped">
                              <Crop className="w-3 h-3 text-white" />
                            </span>
                          ) : null}
                          {image.is_calibrated ? (
                            <span className="p-1 bg-green-500 rounded-full" title="Calibrated">
                              <Palette className="w-3 h-3 text-white" />
                            </span>
                          ) : null}
                          {image.pbr_grayscale_done || image.pbr_colored_done ? (
                            <span className="p-1 bg-green-500 rounded-full" title="PBR Done">
                              <Layers className="w-3 h-3 text-white" />
                            </span>
                          ) : null}
                        </div>
                      </div>

                      {/* Image Info */}
                      <div className="p-3 text-xs">
                        <p className="font-medium text-slate-200 truncate" title={image.filename}>
                          {image.filename}
                        </p>
                        <div className="mt-1 text-slate-400 space-y-0.5">
                          <p>{image.camera}</p>
                          <p>{image.resolution_w} × {image.resolution_h}</p>
                          <p>ISO {image.iso} • {image.aperture} • {image.shutter}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Action Buttons */}
            <div className="px-6 py-4 border-t border-slate-700 bg-slate-800/50 flex justify-between">
              <div className="flex gap-2">
                <Link
                  href={`/processing/crop/${selectedBatch.name}`}
                  className="px-4 py-2 bg-teal-600 text-white rounded-xl hover:bg-teal-700 transition-colors inline-flex items-center"
                >
                  <Crop className="w-4 h-4 mr-2" />
                  Start Cropping
                </Link>
                <Link
                  href={`/processing/calibration/${selectedBatch.name}`}
                  className={`px-4 py-2 bg-violet-600 text-white rounded-xl hover:bg-violet-700 transition-colors inline-flex items-center ${
                    selectedBatch?.crop_status !== 'completed' ? 'opacity-50 pointer-events-none' : ''
                  }`}
                  title={selectedBatch?.crop_status !== 'completed' ? 'Complete cropping first' : ''}
                >
                  <Palette className="w-4 h-4 mr-2" />
                  Color Calibration
                </Link>
                <button
                  onClick={() => setShowPBRModal(true)}
                  disabled={processing !== null || selectedBatch?.crop_status !== 'completed'}
                  className="px-4 py-2 bg-amber-600 text-white rounded-xl hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  title={selectedBatch?.crop_status !== 'completed' ? 'Complete cropping first' : ''}
                >
                  <Layers className="w-4 h-4 inline mr-2" />
                  Generate PBR
                </button>
                <Link
                  href={`/processing/tools?batch=${encodeURIComponent(selectedBatch.name)}`}
                  className="px-4 py-2 bg-slate-600 text-white rounded-xl hover:bg-slate-500 transition-colors inline-flex items-center"
                >
                  <Wand2 className="w-4 h-4 mr-2" />
                  Material Tools
                </Link>
              </div>
              <button
                onClick={closeBatchDetail}
                className="px-4 py-2 bg-slate-700 text-slate-300 rounded-xl hover:bg-slate-600 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
