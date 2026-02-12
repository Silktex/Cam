'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import {
  ArrowLeft, RefreshCw, Crop, Palette, Layers, ChevronRight,
  CheckCircle2, Clock, Loader2, Camera, Image as ImageIcon,
  Settings, FolderOpen, AlertCircle, X, Check
} from 'lucide-react';
import {
  getBatches, getBatchesSummary, getBatch, syncAllBatches,
  updateBatchCrop, updateBatchCalibration, updateBatchPBR,
  updatePBRSelection, getMediaUrl,
  Batch, BatchSummary, BatchImage
} from '@/lib/api';

type Phase = 'crop' | 'calibration' | 'pbr';
type Status = 'pending' | 'in_progress' | 'completed';

const phaseConfig = {
  crop: { label: 'Cropping', icon: Crop, color: 'teal' },
  calibration: { label: 'Color Calibration', icon: Palette, color: 'violet' },
  pbr: { label: 'PBR Generation', icon: Layers, color: 'amber' },
};

const statusConfig = {
  pending: { label: 'Pending', icon: Clock, color: 'slate' },
  in_progress: { label: 'In Progress', icon: Loader2, color: 'blue', animate: true },
  completed: { label: 'Completed', icon: CheckCircle2, color: 'green' },
};

export default function ProcessingPage() {
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

  useEffect(() => {
    fetchData();
  }, [fetchData]);

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
      return true; // Show all for this phase
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
      <div className="min-h-screen bg-cloud flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-teal-600" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-cloud">
      {/* Header */}
      <header className="bg-white border-b border-slate-200/60 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link
                href="/"
                className="p-2 rounded-xl bg-slate-100 hover:bg-slate-200 transition-colors"
              >
                <ArrowLeft className="w-5 h-5 text-slate-600" />
              </Link>
              <div>
                <h1 className="text-xl font-semibold text-slate-800">Processing Pipeline</h1>
                <p className="text-sm text-slate-500">
                  {summary?.total_batches || 0} batches
                </p>
              </div>
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
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-2xl flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-red-500" />
            <span className="text-red-700">{error}</span>
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
                  className="bg-white border border-slate-200 rounded-2xl p-5 cursor-pointer hover:border-teal-300 transition-colors"
                  onClick={() => {
                    setFilterPhase(phase);
                    setFilterStatus('all');
                  }}
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <div className={`p-2 rounded-xl bg-${config.color}-100`}>
                        <Icon className={`w-5 h-5 text-${config.color}-600`} />
                      </div>
                      <span className="font-medium text-slate-800">{config.label}</span>
                    </div>
                    <span className="text-sm text-slate-500">
                      {stats.completed}/{total}
                    </span>
                  </div>

                  {/* Progress bar */}
                  <div className="h-2 bg-slate-100 rounded-full overflow-hidden mb-3">
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
                      className="text-slate-500 hover:text-slate-700"
                    >
                      {stats.pending} pending
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setFilterPhase(phase);
                        setFilterStatus('in_progress');
                      }}
                      className="text-blue-500 hover:text-blue-700"
                    >
                      {stats.in_progress} active
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setFilterPhase(phase);
                        setFilterStatus('completed');
                      }}
                      className="text-green-500 hover:text-green-700"
                    >
                      {stats.completed} done
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Filters */}
        <div className="flex items-center gap-4 mb-6">
          <span className="text-sm text-slate-500">Filter:</span>
          <div className="flex gap-2">
            <button
              onClick={() => { setFilterPhase('all'); setFilterStatus('all'); }}
              className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
                filterPhase === 'all' && filterStatus === 'all'
                  ? 'bg-teal-100 text-teal-700'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
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
                    ? 'bg-teal-100 text-teal-700'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {phaseConfig[phase].label}
              </button>
            ))}
          </div>
          {filterStatus !== 'all' && (
            <span className="text-sm text-slate-400">
              → {statusConfig[filterStatus].label}
            </span>
          )}
        </div>

        {/* Batch List */}
        <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="text-left px-4 py-3 text-sm font-medium text-slate-600">Batch</th>
                <th className="text-center px-4 py-3 text-sm font-medium text-slate-600">Images</th>
                <th className="text-center px-4 py-3 text-sm font-medium text-slate-600">
                  <Crop className="w-4 h-4 inline mr-1" />
                  Crop
                </th>
                <th className="text-center px-4 py-3 text-sm font-medium text-slate-600">
                  <Palette className="w-4 h-4 inline mr-1" />
                  Calibration
                </th>
                <th className="text-center px-4 py-3 text-sm font-medium text-slate-600">
                  <Layers className="w-4 h-4 inline mr-1" />
                  PBR
                </th>
                <th className="text-right px-4 py-3 text-sm font-medium text-slate-600">Synced</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
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
                    className="hover:bg-slate-50 cursor-pointer transition-colors"
                    onClick={() => openBatchDetail(batch)}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <FolderOpen className="w-4 h-4 text-slate-400" />
                        <span className="font-medium text-slate-800">{batch.name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-center text-sm text-slate-600">
                      {batch.image_count}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {getStatusBadge(batch.crop_status)}
                      {batch.crop_type && (
                        <span className="ml-1 text-xs text-slate-400">({batch.crop_type})</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {getStatusBadge(batch.calibration_status)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {getStatusBadge(batch.pbr_status)}
                      {batch.pbr_mode && (
                        <span className="ml-1 text-xs text-slate-400">({batch.pbr_mode})</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-500">
                      {formatDate(batch.synced_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <ChevronRight className="w-4 h-4 text-slate-400" />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </main>

      {/* Batch Detail Modal */}
      {selectedBatch && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
              <div>
                <h2 className="text-lg font-semibold text-slate-800">{selectedBatch.name}</h2>
                <p className="text-sm text-slate-500">
                  {selectedBatch.image_count} images • Created {formatDate(selectedBatch.created_at)}
                </p>
              </div>
              <button
                onClick={closeBatchDetail}
                className="p-2 rounded-lg hover:bg-slate-100 transition-colors"
              >
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>

            {/* Phase Status */}
            <div className="px-6 py-4 bg-slate-50 border-b border-slate-200">
              <div className="flex gap-6">
                <div className="flex items-center gap-2">
                  <Crop className="w-4 h-4 text-slate-500" />
                  <span className="text-sm text-slate-600">Crop:</span>
                  {getStatusBadge(selectedBatch.crop_status)}
                  {selectedBatch.crop_type && (
                    <span className="text-xs text-slate-400">({selectedBatch.crop_type})</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <Palette className="w-4 h-4 text-slate-500" />
                  <span className="text-sm text-slate-600">Calibration:</span>
                  {getStatusBadge(selectedBatch.calibration_status)}
                </div>
                <div className="flex items-center gap-2">
                  <Layers className="w-4 h-4 text-slate-500" />
                  <span className="text-sm text-slate-600">PBR:</span>
                  {getStatusBadge(selectedBatch.pbr_status)}
                  {selectedBatch.pbr_mode && (
                    <span className="text-xs text-slate-400">({selectedBatch.pbr_mode})</span>
                  )}
                </div>
              </div>
            </div>

            {/* Images Grid */}
            <div className="flex-1 overflow-auto p-6">
              {loadingDetail ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-6 h-6 animate-spin text-teal-600" />
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-4">
                  {batchImages.map((image) => (
                    <div
                      key={image.id}
                      className="border border-slate-200 rounded-xl overflow-hidden"
                    >
                      {/* Thumbnail */}
                      <div className="aspect-square bg-slate-100 relative">
                        <img
                          src={getMediaUrl(`${selectedBatch.name}/thumbnail/${image.filename.replace(/\.[^.]+$/, '.jpg')}`)}
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
                              : 'bg-white/80 text-slate-400 hover:bg-white'
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
                        <p className="font-medium text-slate-700 truncate" title={image.filename}>
                          {image.filename}
                        </p>
                        <div className="mt-1 text-slate-500 space-y-0.5">
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
            <div className="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-between">
              <div className="flex gap-2">
                <button
                  disabled
                  className="px-4 py-2 bg-slate-200 text-slate-500 rounded-xl cursor-not-allowed"
                  title="Coming soon"
                >
                  <Crop className="w-4 h-4 inline mr-2" />
                  Start Cropping
                </button>
                <button
                  disabled
                  className="px-4 py-2 bg-slate-200 text-slate-500 rounded-xl cursor-not-allowed"
                  title="Coming soon"
                >
                  <Palette className="w-4 h-4 inline mr-2" />
                  Run Calibration
                </button>
                <button
                  disabled
                  className="px-4 py-2 bg-slate-200 text-slate-500 rounded-xl cursor-not-allowed"
                  title="Coming soon"
                >
                  <Layers className="w-4 h-4 inline mr-2" />
                  Generate PBR
                </button>
              </div>
              <button
                onClick={closeBatchDetail}
                className="px-4 py-2 bg-slate-100 text-slate-600 rounded-xl hover:bg-slate-200 transition-colors"
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
