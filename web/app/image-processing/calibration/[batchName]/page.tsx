'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, Check, Loader2, RefreshCw } from 'lucide-react';
import {
  listColorCheckerProfiles,
  applyProfileToTrack,
  getFullUrl,
  getCalibrationPreview,
} from '@/lib/api';

interface Profile {
  name: string;
  created_at: string;
  source_image?: string;
}

export default function ImageProcessingCalibrationPage() {
  const params = useParams();
  const router = useRouter();
  const batchName = params.batchName as string;

  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // Load profiles
  useEffect(() => {
    setLoading(true);
    listColorCheckerProfiles()
      .then((res) => {
        const list = res.data.profiles || res.data || [];
        setProfiles(list);
        if (list.length > 0) setSelectedProfile(list[0].name);
      })
      .catch(() => setError('Failed to load profiles'))
      .finally(() => setLoading(false));
  }, []);

  // Load preview
  useEffect(() => {
    if (!batchName) return;
    getCalibrationPreview(batchName)
      .then((res) => {
        if (res.data.preview_url) {
          setPreviewUrl(res.data.preview_url);
        }
      })
      .catch(() => {});
  }, [batchName]);

  const handleApply = async () => {
    if (!selectedProfile) return;
    setApplying(true);
    setError(null);
    try {
      // Compute matrix_3x3 from profile swatches, extract checker_wb,
      // and save everything to the process track's color phase
      await applyProfileToTrack(batchName, selectedProfile);

      router.push('/image-processing');
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Calibration failed');
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800 bg-slate-900/80">
        <div className="flex items-center gap-3">
          <Link
            href="/image-processing"
            className="flex items-center gap-1 px-2 py-1 text-slate-400 hover:text-white
              rounded-lg hover:bg-slate-800 transition-colors text-sm"
          >
            <ArrowLeft className="w-4 h-4" />
            Back
          </Link>
          <div className="w-px h-5 bg-slate-700" />
          <span className="text-sm font-medium text-white">Calibration — {batchName}</span>
        </div>
        <button
          onClick={handleApply}
          disabled={applying || !selectedProfile}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-teal-600 hover:bg-teal-500
            disabled:bg-slate-700 text-sm text-white rounded-lg transition-colors"
        >
          {applying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
          Apply Calibration
        </button>
      </div>

      <div className="flex-1 flex">
        {/* Preview area */}
        <div className="flex-1 flex items-center justify-center bg-slate-950 p-8">
          {previewUrl ? (
            <img
              src={getFullUrl(previewUrl)}
              alt="Calibration preview"
              className="max-w-full max-h-full object-contain rounded-xl"
            />
          ) : (
            <div className="text-slate-600 text-sm">
              Select a profile and apply to see the calibrated preview
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="w-72 border-l border-slate-800 bg-slate-900/40 p-4 space-y-4 overflow-y-auto">
          <div className="space-y-2">
            <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">
              ColorChecker Profile
            </h3>

            {loading ? (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="w-4 h-4 text-teal-400 animate-spin" />
              </div>
            ) : profiles.length === 0 ? (
              <p className="text-xs text-slate-500">
                No profiles found. Create one from the ColorChecker page first.
              </p>
            ) : (
              <div className="space-y-1.5">
                {profiles.map((profile) => (
                  <button
                    key={profile.name}
                    onClick={() => setSelectedProfile(profile.name)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-colors ${
                      selectedProfile === profile.name
                        ? 'bg-teal-600/20 text-teal-400 border border-teal-600/30'
                        : 'bg-slate-800 text-slate-300 hover:bg-slate-700 border border-transparent'
                    }`}
                  >
                    <div className="font-medium">{profile.name}</div>
                    {profile.source_image && (
                      <div className="text-slate-500 mt-0.5 truncate">
                        {profile.source_image}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {error && (
            <div className="px-3 py-2 bg-red-900/30 text-red-400 text-xs rounded-lg">
              {error}
            </div>
          )}

          <div className="pt-4 border-t border-slate-800">
            <Link
              href="/processing"
              className="flex items-center gap-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700
                rounded-lg text-xs text-slate-400 transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Manage Profiles (Processing Hub)
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
