'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { Sun } from 'lucide-react';
import ToolLayout, { ActionButton } from '@/app/processing/tools/components/ToolLayout';
import ParameterCard, { SliderControl, SelectControl } from '@/app/processing/tools/components/ParameterCard';
import BeforeAfterSlider from '@/app/processing/tools/components/BeforeAfterSlider';
import { delightPreview, delightApply, getToolImage, getFullUrl } from '@/lib/api';

export default function DelightPage() {
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
  const [method, setMethod] = useState('gaussian');
  const [strength, setStrength] = useState(80);
  const [blurRadius, setBlurRadius] = useState(200);

  // Preview state
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [previewData, setPreviewData] = useState<{
    before_url: string;
    after_url: string;
  } | null>(null);

  // Result toast
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  // Load batch image info
  useEffect(() => {
    const load = async () => {
      try {
        const res = await getToolImage(batchName, 'delight');
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
    try {
      const res = await delightPreview(batchName, {
        blur_radius: blurRadius,
        strength: strength / 100,
        method,
      });
      if (res.data.success) {
        const cacheBust = `?t=${Date.now()}`;
        setPreviewData({
          before_url: getFullUrl(res.data.before_url) + cacheBust,
          after_url: getFullUrl(res.data.after_url) + cacheBust,
        });
      } else {
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
      const res = await delightApply(batchName, {
        blur_radius: blurRadius,
        strength: strength / 100,
        method,
      });
      if (res.data.success) {
        setResult({
          success: true,
          message: `Delighted ${res.data.processed}/${res.data.total} images`,
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

  const methodDescriptions: Record<string, string> = {
    gaussian: 'Estimates lighting with a large Gaussian blur and divides it out. Fast and effective for smooth gradients.',
    frequency_separation: 'Separates low-frequency lighting from high-frequency detail. Better preserves fine texture at the cost of speed.',
  };

  const methodOptions = [
    { value: 'gaussian', label: 'Gaussian (Fast)' },
    { value: 'frequency_separation', label: 'Frequency Separation' },
  ];

  const sidebar = (
    <>
      <ParameterCard title="Method" description="Lighting removal algorithm">
        <SelectControl
          label="Algorithm"
          value={method}
          options={methodOptions}
          onChange={setMethod}
        />
        <p className="text-[11px] text-slate-500 leading-relaxed -mt-1">
          {methodDescriptions[method]}
        </p>
      </ParameterCard>

      <ParameterCard title="Parameters" description="Adjust strength and blur radius">
        <SliderControl
          label="Strength"
          value={strength}
          min={0}
          max={100}
          step={1}
          unit="%"
          onChange={setStrength}
          tooltip="How much lighting to remove. 100% = full removal."
        />
        <SliderControl
          label="Blur Radius"
          value={blurRadius}
          min={51}
          max={501}
          step={2}
          unit="px"
          onChange={setBlurRadius}
          tooltip="Size of the blur kernel for lighting estimation. Larger = captures broader gradients."
        />
      </ParameterCard>

      {/* Image count info */}
      {imageInfo && (
        <div className="text-xs text-slate-500 px-1">
          {imageInfo.image_count} images in batch
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
      <ActionButton onClick={handleApply} loading={applying}>
        Apply to All
      </ActionButton>
    </>
  );

  return (
    <ToolLayout
      batchName={batchName}
      toolName="Delight"
      toolIcon={<Sun className="w-4 h-4 text-teal-400" />}
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
            label={{ before: 'Original', after: `Delighted (${method})` }}
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
