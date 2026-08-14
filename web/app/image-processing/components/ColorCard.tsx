'use client';

import { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Palette, Sun, Loader2, Check } from 'lucide-react';
import {
  listColorCheckerProfiles,
  applyProfileToTrack,
} from '@/lib/api';
import { SliderControl } from '@/app/processing/tools/components/ParameterCard';
import PhaseCard from './PhaseCard';

interface Profile {
  name: string;
  created_at: string;
  source_image?: string;
}

interface ColorCardProps {
  batchName: string;
  status: string;
  params: Record<string, any>;
  onParamsChange: (params: Record<string, any>) => void;
  onPreview: () => void;
  onExposureChange?: (offset: number) => void;
  onRevert?: () => void;
}

export default function ColorCard({
  batchName,
  status,
  params,
  onParamsChange,
  onPreview,
  onExposureChange,
  onRevert,
}: ColorCardProps) {
  const queryClient = useQueryClient();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<string>('');
  const [profilesLoading, setProfilesLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load profiles on mount
  useEffect(() => {
    setProfilesLoading(true);
    listColorCheckerProfiles()
      .then((res) => {
        const list = res.data.profiles || res.data || [];
        setProfiles(list);
        // Pre-select currently applied profile or first available
        if (params.profile_name) {
          setSelectedProfile(params.profile_name);
        } else if (list.length > 0) {
          setSelectedProfile(list[0].name);
        }
      })
      .catch(() => setError('Failed to load profiles'))
      .finally(() => setProfilesLoading(false));
  }, []);

  const handleApplyCalibration = async () => {
    if (!selectedProfile) return;
    setApplying(true);
    setError(null);
    try {
      await applyProfileToTrack(batchName, selectedProfile);
      // Invalidate track so UI reflects the new matrix_3x3 + profile_name
      queryClient.invalidateQueries({ queryKey: ['process-track', batchName] });
      onPreview();
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Calibration failed');
    } finally {
      setApplying(false);
    }
  };

  return (
    <PhaseCard phaseNumber={2} title="Color" status={status} defaultOpen={status !== 'completed'} onRevert={onRevert}>
      {/* Calibration — inline profile selector */}
      <div className="space-y-2">
        <div className="flex items-center gap-1.5 mb-1">
          <Palette className="w-3.5 h-3.5 text-teal-400" />
          <span className="text-xs text-slate-400">ColorChecker Profile</span>
        </div>

        {profilesLoading ? (
          <div className="flex items-center justify-center py-2">
            <Loader2 className="w-3.5 h-3.5 text-teal-400 animate-spin" />
          </div>
        ) : profiles.length === 0 ? (
          <p className="text-[11px] text-slate-500">
            No profiles found. Create one from the ColorChecker page first.
          </p>
        ) : (
          <>
            <select
              value={selectedProfile}
              onChange={(e) => setSelectedProfile(e.target.value)}
              className="w-full px-2 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded-lg text-white"
            >
              {profiles.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                </option>
              ))}
            </select>

            <button
              onClick={handleApplyCalibration}
              disabled={applying || !selectedProfile}
              className="w-full flex items-center justify-center gap-1.5 py-2 bg-teal-600 hover:bg-teal-500
                disabled:bg-slate-700 disabled:opacity-50 text-xs text-white rounded-lg transition-colors"
            >
              {applying ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Check className="w-3.5 h-3.5" />
              )}
              Apply Calibration
            </button>
          </>
        )}

        {params.profile_name && (
          <div className="text-[11px] text-slate-500">
            Current: {params.profile_name}
          </div>
        )}

        {error && (
          <div className="px-2 py-1.5 bg-red-900/30 text-red-400 text-[11px] rounded-lg">
            {error}
          </div>
        )}
      </div>

      {/* Exposure slider */}
      <div className="mt-2">
        <div className="flex items-center gap-1.5 mb-2">
          <Sun className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-xs text-slate-400">Exposure Offset</span>
        </div>
        <SliderControl
          label="EV Offset"
          value={params.exposure_offset || 0}
          min={-3}
          max={3}
          step={0.1}
          unit=" EV"
          onChange={(v) => {
            onParamsChange({ exposure_offset: v });
            onExposureChange?.(v);
            onPreview();
          }}
        />
      </div>
    </PhaseCard>
  );
}
