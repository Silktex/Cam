'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft, Loader2, Check, X, AlertCircle, Save,
  FlipHorizontal, FlipVertical, RotateCcw, RefreshCw,
  Palette, Eye, Camera, FolderOpen, ChevronDown
} from 'lucide-react';
import {
  getFullUrl,
  detectColorCheckerSwatches,
  flipColorChecker,
  rotateColorChecker,
  saveColorCheckerProfile,
  listColorCheckerProfiles,
  getDetectedSwatches,
  getReferenceSwatches,
  calibrateBatch,
  getBatch,
  getBatchImages,
} from '@/lib/api';

interface Swatch {
  name: string;
  index: number;
  r: number;
  g: number;
  b: number;
  hex: string;
}

interface DetectionState {
  detectionId: string | null;
  overlayUrl: string | null;
  swatchCount: number;
  flipH: boolean;
  flipV: boolean;
  rotation: number;
}

export default function CalibrationPage() {
  const params = useParams();
  const router = useRouter();
  const batchName = params.batchName as string;

  // Loading states
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Batch data
  const [batchData, setBatchData] = useState<any>(null);
  const [batchImages, setBatchImages] = useState<any[]>([]);
  const [colorCheckerImage, setColorCheckerImage] = useState<string | null>(null);
  const [showImagePicker, setShowImagePicker] = useState(false);

  // Detection state
  const [detection, setDetection] = useState<DetectionState>({
    detectionId: null,
    overlayUrl: null,
    swatchCount: 0,
    flipH: false,
    flipV: false,
    rotation: 0,
  });
  const [overlayKey, setOverlayKey] = useState(0);

  // Swatches for comparison
  const [detectedSwatches, setDetectedSwatches] = useState<Swatch[]>([]);
  const [referenceSwatches, setReferenceSwatches] = useState<Swatch[]>([]);
  const [showComparison, setShowComparison] = useState(false);

  // Profiles
  const [profiles, setProfiles] = useState<any[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<string>('');
  const [newProfileName, setNewProfileName] = useState('');

  // Processing state
  const [processing, setProcessing] = useState<string | null>(null);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  // Load batch and profiles
  useEffect(() => {
    const loadData = async () => {
      try {
        // Load batch data
        const batchRes = await getBatch(batchName);
        setBatchData(batchRes.data);

        // Load batch images
        const imagesRes = await getBatchImages(batchName);
        setBatchImages(imagesRes.data.images || []);

        // Load profiles
        const profilesRes = await listColorCheckerProfiles();
        setProfiles(profilesRes.data.profiles || []);

        // Load reference swatches
        const refRes = await getReferenceSwatches();
        setReferenceSwatches(refRes.data.swatches || []);

      } catch (err: any) {
        setLoadError(err.response?.data?.detail || 'Failed to load batch');
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [batchName]);

  // Fetch detected swatches when detection changes
  useEffect(() => {
    if (detection.detectionId) {
      getDetectedSwatches(detection.detectionId)
        .then((res) => setDetectedSwatches(res.data.swatches || []))
        .catch((err) => console.error('Failed to get detected swatches:', err));
    }
  }, [detection.detectionId, overlayKey]);

  // Handle file input for colorchecker image
  const handleImagePathChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const path = e.target.value;
    setColorCheckerImage(path);
    // Reset detection when image changes
    setDetection({
      detectionId: null,
      overlayUrl: null,
      swatchCount: 0,
      flipH: false,
      flipV: false,
      rotation: 0,
    });
  };

  // Detect colorchecker
  const handleDetect = async () => {
    if (!colorCheckerImage) return;
    setProcessing('detecting');
    try {
      const res = await detectColorCheckerSwatches(colorCheckerImage);
      const data = res.data;
      setDetection({
        detectionId: data.detection_id,
        overlayUrl: data.overlay_url,
        swatchCount: data.swatches_detected,
        flipH: data.flip_h,
        flipV: data.flip_v,
        rotation: data.rotation,
      });
      setOverlayKey((k) => k + 1);
      setShowComparison(true);
    } catch (err: any) {
      setResult({
        success: false,
        message: err.response?.data?.detail || 'Detection failed',
      });
    } finally {
      setProcessing(null);
    }
  };

  // Flip detection
  const handleFlip = async (axis: 'horizontal' | 'vertical') => {
    if (!detection.detectionId) return;
    setProcessing('flipping');
    try {
      const res = await flipColorChecker(detection.detectionId, axis);
      const data = res.data;
      setDetection((d) => ({
        ...d,
        flipH: data.flip_h,
        flipV: data.flip_v,
        rotation: data.rotation,
      }));
      setOverlayKey((k) => k + 1);
    } catch (err: any) {
      setResult({
        success: false,
        message: err.response?.data?.detail || 'Flip failed',
      });
    } finally {
      setProcessing(null);
    }
  };

  // Rotate detection
  const handleRotate = async () => {
    if (!detection.detectionId) return;
    setProcessing('rotating');
    try {
      const res = await rotateColorChecker(detection.detectionId, 90);
      const data = res.data;
      setDetection((d) => ({
        ...d,
        flipH: data.flip_h,
        flipV: data.flip_v,
        rotation: data.rotation,
      }));
      setOverlayKey((k) => k + 1);
    } catch (err: any) {
      setResult({
        success: false,
        message: err.response?.data?.detail || 'Rotation failed',
      });
    } finally {
      setProcessing(null);
    }
  };

  // Save profile
  const handleSaveProfile = async () => {
    if (!detection.detectionId || !newProfileName.trim()) return;
    setProcessing('saving');
    try {
      await saveColorCheckerProfile(detection.detectionId, newProfileName.trim());
      setResult({ success: true, message: `Profile "${newProfileName}" saved` });
      setNewProfileName('');
      // Refresh profiles
      const profilesRes = await listColorCheckerProfiles();
      setProfiles(profilesRes.data.profiles || []);
      setSelectedProfile(newProfileName.trim());
    } catch (err: any) {
      setResult({
        success: false,
        message: err.response?.data?.detail || 'Save failed',
      });
    } finally {
      setProcessing(null);
    }
  };

  // Apply calibration
  const handleApplyCalibration = async () => {
    const profileToUse = selectedProfile || (detection.detectionId ? newProfileName : '');
    if (!profileToUse && !detection.detectionId) {
      setResult({ success: false, message: 'Select a profile or detect ColorChecker first' });
      return;
    }

    setProcessing('calibrating');
    try {
      // If we have a new detection but no saved profile, save it first
      if (detection.detectionId && !selectedProfile) {
        const profileName = newProfileName.trim() || `${batchName}_profile`;
        await saveColorCheckerProfile(detection.detectionId, profileName);
        setSelectedProfile(profileName);
      }

      const res = await calibrateBatch(batchName, selectedProfile || newProfileName.trim() || `${batchName}_profile`);
      if (res.data.success) {
        setResult({
          success: true,
          message: `Calibrated ${res.data.processed_count || 'all'} images`,
        });
        setTimeout(() => router.push('/processing'), 2000);
      } else {
        setResult({ success: false, message: res.data.error || 'Calibration failed' });
      }
    } catch (err: any) {
      setResult({
        success: false,
        message: err.response?.data?.detail || 'Calibration failed',
      });
    } finally {
      setProcessing(null);
    }
  };

  const isProcessing = processing !== null;

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-teal-500" />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <p className="text-white mb-4">{loadError}</p>
          <Link href="/processing" className="text-teal-400 hover:text-teal-300">
            Back to Processing
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 flex">
      {/* Main content area */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <header className="bg-slate-800 border-b border-slate-700 px-4 py-3 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-4">
            <Link
              href="/processing"
              className="p-2 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors"
            >
              <ArrowLeft className="w-5 h-5 text-slate-300" />
            </Link>
            <div>
              <h1 className="text-lg font-semibold text-white">Color Calibration: {batchName}</h1>
              <p className="text-sm text-slate-400">
                {batchData?.image_count || 0} images
              </p>
            </div>
          </div>
        </header>

        {/* Preview area */}
        <div className="flex-1 overflow-auto flex items-center justify-center p-4">
          <div className="w-full max-w-4xl">
            {/* Overlay preview */}
            <div className="bg-slate-800 rounded-xl overflow-hidden border border-slate-700 mb-4">
              <div className="aspect-video bg-slate-900 flex items-center justify-center">
                {detection.overlayUrl ? (
                  <img
                    key={overlayKey}
                    src={getFullUrl(detection.overlayUrl)}
                    alt="ColorChecker Detection"
                    className="max-w-full max-h-full object-contain"
                  />
                ) : colorCheckerImage ? (
                  <div className="text-center text-slate-400">
                    <Eye className="w-12 h-12 mx-auto mb-2 opacity-50" />
                    <p>Click "Detect" to find ColorChecker</p>
                  </div>
                ) : (
                  <div className="text-center text-slate-400">
                    <Palette className="w-12 h-12 mx-auto mb-2 opacity-50" />
                    <p>Enter ColorChecker image path below</p>
                  </div>
                )}
              </div>
            </div>

            {/* Color comparison */}
            {showComparison && detection.detectionId && (
              <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
                <h3 className="text-sm font-medium text-slate-300 mb-3">Color Comparison</h3>
                <div className="grid grid-cols-2 gap-6">
                  {/* Detected Colors */}
                  <div>
                    <div className="text-xs text-slate-500 mb-2">Detected (Camera)</div>
                    <div className="grid grid-cols-6 gap-1">
                      {detectedSwatches.slice(0, 24).map((swatch) => (
                        <div
                          key={swatch.index}
                          className="aspect-square rounded border border-slate-600"
                          style={{ backgroundColor: swatch.hex }}
                          title={`${swatch.name}: ${swatch.hex}`}
                        />
                      ))}
                    </div>
                  </div>

                  {/* Reference Colors */}
                  <div>
                    <div className="text-xs text-slate-500 mb-2">Reference (Standard)</div>
                    <div className="grid grid-cols-6 gap-1">
                      {referenceSwatches.slice(0, 24).map((swatch) => (
                        <div
                          key={swatch.index}
                          className="aspect-square rounded border border-slate-600"
                          style={{ backgroundColor: swatch.hex }}
                          title={`${swatch.name}: ${swatch.hex}`}
                        />
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Right sidebar */}
      <div className="w-80 bg-slate-800 border-l border-slate-700 flex flex-col shrink-0">
        {/* Image Input */}
        <div className="p-4 border-b border-slate-700">
          <div className="text-sm font-medium text-slate-300 mb-3">ColorChecker Image</div>

          {/* Image Picker Dropdown */}
          <div className="relative mb-2">
            <button
              onClick={() => setShowImagePicker(!showImagePicker)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white text-sm text-left flex items-center justify-between"
            >
              <span className={colorCheckerImage ? 'text-white' : 'text-slate-500'}>
                {colorCheckerImage ? colorCheckerImage.split('/').pop() : 'Select image from batch...'}
              </span>
              <ChevronDown className={`w-4 h-4 transition-transform ${showImagePicker ? 'rotate-180' : ''}`} />
            </button>

            {showImagePicker && batchImages.length > 0 && (
              <div className="absolute z-10 w-full mt-1 bg-slate-700 border border-slate-600 rounded-lg shadow-lg max-h-48 overflow-auto">
                {batchImages.map((img: any) => {
                  const tiffPath = `${batchData?.folder_path}/tiff/${img.filename.replace(/\.[^.]+$/, '.tiff')}`;
                  return (
                    <button
                      key={img.id}
                      onClick={() => {
                        setColorCheckerImage(tiffPath);
                        setShowImagePicker(false);
                        setDetection({
                          detectionId: null,
                          overlayUrl: null,
                          swatchCount: 0,
                          flipH: false,
                          flipV: false,
                          rotation: 0,
                        });
                      }}
                      className="w-full px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-600 transition-colors"
                    >
                      <div className="font-medium">{img.filename}</div>
                      <div className="text-xs text-slate-500">{img.position}</div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Manual path input */}
          <input
            type="text"
            value={colorCheckerImage || ''}
            onChange={handleImagePathChange}
            placeholder="Or enter full path manually..."
            className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white text-sm placeholder-slate-500 focus:ring-2 focus:ring-teal-500 focus:border-teal-500"
          />
          <p className="text-xs text-slate-500 mt-2">
            Select image with ColorChecker from the batch
          </p>
        </div>

        {/* Detection Controls */}
        <div className="p-4 border-b border-slate-700">
          <div className="text-sm font-medium text-slate-300 mb-3">Detection</div>

          <button
            onClick={handleDetect}
            disabled={!colorCheckerImage || isProcessing}
            className={`w-full flex items-center justify-center gap-2 py-2.5 rounded-lg font-medium transition-colors mb-3 ${
              !colorCheckerImage || isProcessing
                ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                : 'bg-teal-600 text-white hover:bg-teal-500'
            }`}
          >
            {processing === 'detecting' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Eye className="w-4 h-4" />
            )}
            Detect ColorChecker
          </button>

          {/* Adjustment Controls */}
          {detection.detectionId && (
            <div className="space-y-2">
              <div className="text-xs text-slate-500 mb-2">Adjust Orientation</div>
              <div className="grid grid-cols-3 gap-2">
                <button
                  onClick={() => handleFlip('horizontal')}
                  disabled={isProcessing}
                  className={`flex items-center justify-center gap-1 py-2 rounded-lg text-sm transition-colors ${
                    detection.flipH
                      ? 'bg-violet-600 text-white'
                      : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                  }`}
                >
                  <FlipHorizontal className="w-4 h-4" />
                </button>
                <button
                  onClick={() => handleFlip('vertical')}
                  disabled={isProcessing}
                  className={`flex items-center justify-center gap-1 py-2 rounded-lg text-sm transition-colors ${
                    detection.flipV
                      ? 'bg-violet-600 text-white'
                      : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                  }`}
                >
                  <FlipVertical className="w-4 h-4" />
                </button>
                <button
                  onClick={handleRotate}
                  disabled={isProcessing}
                  className="flex items-center justify-center gap-1 py-2 bg-slate-700 text-slate-300 rounded-lg text-sm hover:bg-slate-600 transition-colors"
                >
                  <RotateCcw className="w-4 h-4" />
                </button>
              </div>

              {/* Status */}
              <div className="text-xs text-slate-500 mt-2">
                {detection.swatchCount} swatches
                {detection.flipH && ' | H-Flip'}
                {detection.flipV && ' | V-Flip'}
                {detection.rotation > 0 && ` | ${detection.rotation} deg`}
              </div>
            </div>
          )}
        </div>

        {/* Save Profile */}
        {detection.detectionId && (
          <div className="p-4 border-b border-slate-700">
            <div className="text-sm font-medium text-slate-300 mb-3">Save as Profile</div>
            <div className="flex gap-2">
              <input
                type="text"
                value={newProfileName}
                onChange={(e) => setNewProfileName(e.target.value)}
                placeholder="my_calibration"
                className="flex-1 px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white text-sm"
              />
              <button
                onClick={handleSaveProfile}
                disabled={!newProfileName.trim() || isProcessing}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  !newProfileName.trim() || isProcessing
                    ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                    : 'bg-green-600 text-white hover:bg-green-500'
                }`}
              >
                {processing === 'saving' ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Save className="w-4 h-4" />
                )}
              </button>
            </div>
          </div>
        )}

        {/* Existing Profiles */}
        <div className="p-4 border-b border-slate-700">
          <div className="text-sm font-medium text-slate-300 mb-3">
            Use Existing Profile
          </div>
          {profiles.length > 0 ? (
            <select
              value={selectedProfile}
              onChange={(e) => setSelectedProfile(e.target.value)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white text-sm"
            >
              <option value="">Select a profile...</option>
              {profiles.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                </option>
              ))}
            </select>
          ) : (
            <p className="text-sm text-slate-500">No saved profiles</p>
          )}
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Apply Calibration */}
        <div className="p-4 border-t border-slate-700 space-y-2">
          <button
            onClick={handleApplyCalibration}
            disabled={(!detection.detectionId && !selectedProfile) || isProcessing}
            className={`w-full flex items-center justify-center gap-2 py-3 rounded-lg font-medium transition-colors ${
              (!detection.detectionId && !selectedProfile) || isProcessing
                ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                : 'bg-green-600 text-white hover:bg-green-500'
            }`}
          >
            {processing === 'calibrating' ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Check className="w-5 h-5" />
            )}
            Apply Calibration to All Images
          </button>
          <button
            onClick={() => router.push('/processing')}
            className="w-full py-2.5 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>

      {/* Result toast */}
      {result && (
        <div
          className={`fixed bottom-6 left-1/2 -translate-x-1/2 px-6 py-4 rounded-xl shadow-lg flex items-center gap-3 ${
            result.success ? 'bg-green-600 text-white' : 'bg-red-600 text-white'
          }`}
        >
          {result.success ? (
            <Check className="w-5 h-5" />
          ) : (
            <AlertCircle className="w-5 h-5" />
          )}
          <span>{result.message}</span>
          <button onClick={() => setResult(null)} className="ml-2 hover:opacity-80">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}
