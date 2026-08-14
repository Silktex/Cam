'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { Minimize2, AlertTriangle } from 'lucide-react';
import ToolLayout, { ActionButton } from '@/app/processing/tools/components/ToolLayout';
import ParameterCard, { SliderControl, SelectControl } from '@/app/processing/tools/components/ParameterCard';
import BeforeAfterSlider from '@/app/processing/tools/components/BeforeAfterSlider';
import { flattenPreview, flattenApply, getToolImage, getFullUrl } from '@/lib/api';

export default function FlattenPage() {
  const params = useParams();
  const batchName = params.batchName as string;

  // Loading state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Image data
  const [imageInfo, setImageInfo] = useState<{
    preview_url: string;
    image_count: number;
  } | null>(null);

  // Parameters
  const [strength, setStrength] = useState(80);
  const [smoothingRadius, setSmoothingRadius] = useState(51);
  const [pbrMode, setPbrMode] = useState('grayscale');

  // Preview state
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [previewData, setPreviewData] = useState<{
    before_url: string;
    after_url: string;
  } | null>(null);
  const [noPbrMaps, setNoPbrMaps] = useState(false);

  // Result toast
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  // Load batch image info
  useEffect(() => {
    const load = async () => {
      try {
        const res = await getToolImage(batchName, 'flatten');
        setImageInfo(res.data);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Failed to load batch';
        setError(msg);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [batchName]);

  const handlePreview = async () => {
    setPreviewing(true);
    setResult(null);
    setNoPbrMaps(false);
    try {
      const res = await flattenPreview(batchName, {
        strength: strength / 100,
        smoothing_radius: smoothingRadius,
        pbr_mode: pbrMode,
      });
      if (res.data.success) {
        setPreviewData({
          before_url: getFullUrl(res.data.before_url),
          after_url: getFullUrl(res.data.after_url),
        });
      } else {
        if (res.data.error?.includes('PBR')) {
          setNoPbrMaps(true);
        }
        setResult({ success: false, message: res.data.error || 'Preview failed' });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Preview failed';
      setResult({ success: false, message: msg });
    } finally {
      setPreviewing(false);
    }
  };

  const handleApply = async () => {
    setApplying(true);
    setResult(null);
    try {
      const res = await flattenApply(batchName, {
        strength: strength / 100,
        smoothing_radius: smoothingRadius,
        pbr_mode: pbrMode,
      });
      if (res.data.success) {
        setResult({
          success: true,
          message: `Flattened ${res.data.processed}/${res.data.total} images`,
        });
      } else {
        setResult({ success: false, message: res.data.error || 'Apply failed' });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Apply failed';
      setResult({ success: false, message: msg });
    } finally {
      setApplying(false);
    }
  };

  const pbrModeOptions = [
    { value: 'grayscale', label: 'Grayscale PBR' },
    { value: 'color', label: 'Color PBR' },
  ];

  const sidebar = (
    <>
      <ParameterCard title="PBR Source" description="Normal map source for flattening">
        <SelectControl
          label="PBR Mode"
          value={pbrMode}
          options={pbrModeOptions}
          onChange={setPbrMode}
        />
      </ParameterCard>

      <ParameterCard title="Parameters" description="Adjust flattening strength and scale">
        <SliderControl
          label="Strength"
          value={strength}
          min={0}
          max={100}
          step={1}
          unit="%"
          onChange={setStrength}
          tooltip="How much surface correction to apply. 100% = full flattening."
        />
        <SliderControl
          label="Smoothing Radius"
          value={smoothingRadius}
          min={0}
          max={501}
          step={2}
          unit="px"
          onChange={setSmoothingRadius}
          tooltip="Blur normals before correction. Higher = only remove broad wrinkles, preserving micro-texture."
        />
      </ParameterCard>

      {/* Image count info */}
      {imageInfo && (
        <div className="text-xs text-slate-500 px-1">
          {imageInfo.image_count} images in batch
        </div>
      )}

      {/* PBR warning */}
      {noPbrMaps && (
        <div className="flex items-start gap-2 p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl">
          <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
          <p className="text-xs text-amber-300">
            PBR normal maps required. Generate them from the Processing page first.
          </p>
        </div>
      )}
    </>
  );

  const actionBar = (
    <>
      {result && (
        <span className={`text-sm mr-auto ${result.success ? 'text-green-400' : 'text-red-400'}`}>
          {result.message}
        </span>
      )}
      <ActionButton onClick={handlePreview} loading={previewing} variant="secondary">
        Preview
      </ActionButton>
      <ActionButton onClick={handleApply} loading={applying} disabled={!previewData}>
        Apply to All
      </ActionButton>
    </>
  );

  return (
    <ToolLayout
      batchName={batchName}
      toolName="Flatten"
      toolIcon={<Minimize2 className="w-4 h-4 text-indigo-400" />}
      sidebar={sidebar}
      actionBar={actionBar}
      loading={loading}
      error={error}
    >
      <div className="h-full flex flex-col items-center justify-center gap-4">
        {previewData ? (
          <BeforeAfterSlider
            beforeUrl={previewData.before_url}
            afterUrl={previewData.after_url}
            width={1200}
            height={800}
            label={{ before: 'Original', after: 'Flattened' }}
          />
        ) : imageInfo ? (
          <div className="text-center space-y-4">
            <div className="rounded-2xl overflow-hidden border border-slate-700/50 inline-block">
              <img
                src={getFullUrl(imageInfo.preview_url)}
                alt="Source"
                className="max-h-[60vh] object-contain"
              />
            </div>
            <p className="text-sm text-slate-400">
              Adjust parameters and click Preview to see the result
            </p>
          </div>
        ) : (
          <p className="text-slate-500">No images available</p>
        )}
      </div>
    </ToolLayout>
  );
}
