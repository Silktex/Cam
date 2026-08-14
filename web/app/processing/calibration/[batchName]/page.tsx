'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft, Loader2, Check, X, AlertCircle, Palette
} from 'lucide-react';
import {
  listColorCheckerProfiles,
  calibrateBatch,
  getBatch,
} from '@/lib/api';

export default function CalibrationPage() {
  const params = useParams();
  const router = useRouter();
  const batchName = params.batchName as string;

  // Loading states
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Batch data
  const [batchData, setBatchData] = useState<any>(null);

  // Profiles
  const [profiles, setProfiles] = useState<any[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<string>('');

  // Processing state
  const [processing, setProcessing] = useState<string | null>(null);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  // Load batch and profiles
  useEffect(() => {
    const loadData = async () => {
      try {
        const batchRes = await getBatch(batchName);
        setBatchData(batchRes.data);

        const profilesRes = await listColorCheckerProfiles();
        setProfiles(profilesRes.data.profiles || []);
      } catch (err: any) {
        setLoadError(err.response?.data?.detail || 'Failed to load batch');
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [batchName]);

  // Apply calibration
  const handleApplyCalibration = async () => {
    if (!selectedProfile) {
      setResult({ success: false, message: 'Select a calibration profile first' });
      return;
    }

    setProcessing('calibrating');
    try {
      const res = await calibrateBatch(batchName, selectedProfile);
      if (res.data.success) {
        setResult({
          success: true,
          message: `Calibrated ${res.data.processed || 'all'} images`,
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
            <div className="bg-slate-800 rounded-xl overflow-hidden border border-slate-700">
              <div className="aspect-video bg-slate-900 flex items-center justify-center">
                <div className="text-center text-slate-400">
                  <Palette className="w-12 h-12 mx-auto mb-2 opacity-50" />
                  <p>Select a calibration profile and apply</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right sidebar */}
      <div className="w-80 bg-slate-800 border-l border-slate-700 flex flex-col shrink-0">
        {/* Calibration Profile */}
        <div className="p-4 border-b border-slate-700">
          <div className="text-sm font-medium text-slate-300 mb-3">
            Calibration Profile
          </div>
          {profiles.length > 0 ? (
            <>
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
              <p className="text-xs text-slate-500 mt-2">
                Profiles created from the Color Checker tab
              </p>
            </>
          ) : (
            <p className="text-sm text-slate-500">
              No saved profiles. Create one from the Color tab first.
            </p>
          )}
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Apply Calibration */}
        <div className="p-4 border-t border-slate-700 space-y-2">
          <button
            onClick={handleApplyCalibration}
            disabled={!selectedProfile || isProcessing}
            className={`w-full flex items-center justify-center gap-2 py-3 rounded-lg font-medium transition-colors ${
              !selectedProfile || isProcessing
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
