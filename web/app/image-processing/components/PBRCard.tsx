'use client';

import { useState } from 'react';
import { Box, Loader2 } from 'lucide-react';
import { SelectControl } from '@/app/processing/tools/components/ParameterCard';
import { pipelinePreview, updatePhaseParams } from '@/lib/api';
import PhaseCard from './PhaseCard';

interface PBRCardProps {
  batchName: string;
  status: string;
  params: Record<string, any>;
  onParamsChange: (params: Record<string, any>) => void;
  onPreviewReady: (url: string) => void;
  disabled?: boolean;
  onRevert?: () => void;
}

export default function PBRCard({
  batchName,
  status,
  params,
  onParamsChange,
  onPreviewReady,
  disabled = false,
  onRevert,
}: PBRCardProps) {
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      // Update status to in_progress
      await updatePhaseParams(batchName, 'pbr', { status: 'in_progress' });

      const res = await pipelinePreview(batchName, 'pbr');
      if (res.data.success) {
        // PBR preview returns albedo_url (from render_pbr_preview), or preview_url (from render_preview)
        const url = res.data.albedo_url || res.data.preview_url;
        if (url) onPreviewReady(`${url}?t=${Date.now()}`);
      }

      // Mark completed
      await updatePhaseParams(batchName, 'pbr', { status: 'completed' });
    } catch (e: any) {
      setError(e.response?.data?.detail || 'PBR generation failed');
    } finally {
      setGenerating(false);
    }
  };

  return (
    <PhaseCard
      phaseNumber={3}
      title="PBR Generation"
      status={status}
      disabled={disabled}
      defaultOpen={status !== 'completed'}
      onRevert={onRevert}
    >
      <SelectControl
        label="Mode"
        value={params.mode || 'grayscale'}
        options={[
          { value: 'grayscale', label: 'Grayscale' },
          { value: 'color', label: 'Color' },
          { value: 'both', label: 'Both' },
        ]}
        onChange={(v) => onParamsChange({ mode: v })}
      />

      <button
        onClick={handleGenerate}
        disabled={generating}
        className="w-full flex items-center justify-center gap-2 px-3 py-2.5 mt-2
          bg-teal-600 hover:bg-teal-500 disabled:bg-slate-700
          rounded-lg text-sm font-medium text-white transition-colors"
      >
        {generating ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Generating PBR Maps...
          </>
        ) : (
          <>
            <Box className="w-4 h-4" />
            Generate
          </>
        )}
      </button>

      {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
    </PhaseCard>
  );
}
