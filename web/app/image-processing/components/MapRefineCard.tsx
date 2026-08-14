'use client';

import { Layers, Sun, Paintbrush } from 'lucide-react';
import {
  SliderControl,
  ToggleControl,
  SelectControl,
} from '@/app/processing/tools/components/ParameterCard';
import PhaseCard from './PhaseCard';

interface MapRefineCardProps {
  batchName: string;
  status: string;
  params: Record<string, any>;
  onParamsChange: (params: Record<string, any>) => void;
  onPreview: () => void;
  disabled?: boolean;
  onRevert?: () => void;
}

export default function MapRefineCard({
  batchName,
  status,
  params,
  onParamsChange,
  onPreview,
  disabled = false,
  onRevert,
}: MapRefineCardProps) {
  const flattenParams = params.flatten || {};
  const delightParams = params.delight || {};
  const roughnessParams = params.roughness || {};

  return (
    <PhaseCard
      phaseNumber={4}
      title="Map Refinement"
      status={status}
      disabled={disabled}
      defaultOpen={status !== 'completed'}
      onRevert={onRevert}
    >
      {/* Flatten */}
      <div className="space-y-2">
        <ToggleControl
          label="Flatten (uses normals)"
          value={flattenParams.enabled ?? true}
          onChange={(v) =>
            onParamsChange({ flatten: { ...flattenParams, enabled: v } })
          }
        />
        {flattenParams.enabled && (
          <SliderControl
            label="Flatten Strength"
            value={flattenParams.strength ?? 1.0}
            min={0}
            max={2}
            step={0.1}
            onChange={(v) => {
              onParamsChange({ flatten: { ...flattenParams, strength: v } });
              onPreview();
            }}
          />
        )}
      </div>

      {/* Delight */}
      <div className="space-y-2 pt-2 border-t border-slate-800/50">
        <ToggleControl
          label="Delight (remove lighting)"
          value={delightParams.enabled ?? true}
          onChange={(v) =>
            onParamsChange({ delight: { ...delightParams, enabled: v } })
          }
        />
        {delightParams.enabled && (
          <>
            <SelectControl
              label="Method"
              value={delightParams.method || 'gaussian'}
              options={[
                { value: 'gaussian', label: 'Gaussian' },
                { value: 'frequency_separation', label: 'Frequency Separation' },
              ]}
              onChange={(v) =>
                onParamsChange({ delight: { ...delightParams, method: v } })
              }
            />
            <SliderControl
              label="Strength"
              value={delightParams.strength ?? 1.0}
              min={0}
              max={2}
              step={0.1}
              onChange={(v) => {
                onParamsChange({ delight: { ...delightParams, strength: v } });
                onPreview();
              }}
            />
            <SliderControl
              label="Blur Radius"
              value={delightParams.blur_radius ?? 200}
              min={10}
              max={500}
              step={10}
              unit="px"
              onChange={(v) => {
                onParamsChange({ delight: { ...delightParams, blur_radius: v } });
                onPreview();
              }}
            />
          </>
        )}
      </div>

      {/* Roughness Scale */}
      <div className="space-y-2 pt-2 border-t border-slate-800/50">
        <SliderControl
          label="Roughness Scale"
          value={roughnessParams.scale_factor ?? 1.0}
          min={0.5}
          max={2}
          step={0.1}
          unit="x"
          onChange={(v) => {
            onParamsChange({ roughness: { ...roughnessParams, scale_factor: v } });
            onPreview();
          }}
        />
      </div>

      {/* Clone Stamp */}
      <div className="pt-2 border-t border-slate-800/50">
        <button
          className="w-full flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-slate-700
            rounded-lg text-xs text-slate-300 transition-colors"
        >
          <Paintbrush className="w-3.5 h-3.5 text-teal-400" />
          Clone Stamp
        </button>
      </div>
    </PhaseCard>
  );
}
