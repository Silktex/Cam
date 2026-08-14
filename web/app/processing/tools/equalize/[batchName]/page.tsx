'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { BarChart3 } from 'lucide-react';
import ToolLayout, { ActionButton } from '@/app/processing/tools/components/ToolLayout';
import ParameterCard, { SliderControl, SelectControl } from '@/app/processing/tools/components/ParameterCard';
import BeforeAfterSlider from '@/app/processing/tools/components/BeforeAfterSlider';
import HistogramChart from '@/app/processing/tools/components/HistogramChart';
import { equalizePreview, equalizeApply, getToolImage, getFullUrl } from '@/lib/api';

interface HistogramData {
  r: number[];
  g: number[];
  b: number[];
  luminance?: number[];
}

export default function EqualizePage() {
  const params = useParams();
  const batchName = params.batchName as string;

  // Loading state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Image data
  const [imageInfo, setImageInfo] = useState<{
    images: string[];
    preview_url: string;
    image_count: number;
  } | null>(null);

  // Parameters
  const [method, setMethod] = useState('clahe');
  const [clipLimit, setClipLimit] = useState(2.0);
  const [referenceImage, setReferenceImage] = useState('');

  // Preview state
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [previewData, setPreviewData] = useState<{
    before_url: string;
    after_url: string;
    before_histogram: HistogramData;
    after_histogram: HistogramData;
  } | null>(null);

  // Result toast
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  // Load batch image info
  useEffect(() => {
    const load = async () => {
      try {
        const res = await getToolImage(batchName, 'equalize');
        setImageInfo(res.data);
        if (res.data.images?.length > 0) {
          setReferenceImage(res.data.images[0]);
        }
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
      const opts: Record<string, unknown> = {};
      if (method === 'clahe') {
        opts.clip_limit = clipLimit;
      } else {
        opts.reference_image = referenceImage;
      }
      const res = await equalizePreview(batchName, method, opts as { reference_image?: string; clip_limit?: number });
      if (res.data.success) {
        const cacheBust = `?t=${Date.now()}`;
        setPreviewData({
          before_url: getFullUrl(res.data.before_url) + cacheBust,
          after_url: getFullUrl(res.data.after_url) + cacheBust,
          before_histogram: res.data.before_histogram,
          after_histogram: res.data.after_histogram,
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
      const opts: Record<string, unknown> = {};
      if (method === 'clahe') {
        opts.clip_limit = clipLimit;
      } else {
        opts.reference_image = referenceImage;
      }
      const res = await equalizeApply(batchName, method, opts as { reference_image?: string; clip_limit?: number });
      if (res.data.success) {
        setResult({
          success: true,
          message: `Equalized ${res.data.processed}/${res.data.total} images`,
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
    clahe: 'Contrast Limited Adaptive Histogram Equalization. Enhances local contrast while preventing noise amplification.',
    histogram_match: 'Matches the histogram of all images to the reference image. Good for ensuring consistent tonal distribution.',
    exposure_match: 'Adjusts exposure levels to match the reference. Best for correcting brightness differences between captures.',
  };

  const methodOptions = [
    { value: 'clahe', label: 'CLAHE (Adaptive)' },
    { value: 'histogram_match', label: 'Histogram Match' },
    { value: 'exposure_match', label: 'Exposure Match' },
  ];

  const referenceOptions = (imageInfo?.images || []).map((name) => ({
    value: name,
    label: name.replace(/\.(tiff|tif|png|jpg|jpeg)$/i, ''),
  }));

  const sidebar = (
    <>
      <ParameterCard title="Method" description="Choose equalization algorithm">
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

      {method === 'clahe' && (
        <ParameterCard title="CLAHE Settings" description="Contrast Limited Adaptive Histogram Equalization">
          <SliderControl
            label="Clip Limit"
            value={clipLimit}
            min={0.5}
            max={10}
            step={0.5}
            onChange={setClipLimit}
            tooltip="Higher values increase local contrast. 2.0 is a good default."
          />
        </ParameterCard>
      )}

      {(method === 'histogram_match' || method === 'exposure_match') && (
        <ParameterCard title="Reference" description="Match brightness/histogram to this image">
          <SelectControl
            label="Reference Image"
            value={referenceImage}
            options={referenceOptions}
            onChange={setReferenceImage}
          />
        </ParameterCard>
      )}

      {/* Histogram display */}
      {previewData && (
        <>
          <ParameterCard title="Before Histogram">
            <HistogramChart
              data={previewData.before_histogram}
              showChannels={['r', 'g', 'b', 'luminance']}
            />
          </ParameterCard>
          <ParameterCard title="After Histogram">
            <HistogramChart
              data={previewData.after_histogram}
              showChannels={['r', 'g', 'b', 'luminance']}
            />
          </ParameterCard>
        </>
      )}

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
      toolName="Equalize"
      toolIcon={<BarChart3 className="w-4 h-4 text-teal-400" />}
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
            label={{ before: 'Original', after: `Equalized (${method})` }}
          />
        ) : imageInfo ? (
          <div className="text-center space-y-4">
            {/* Show source image thumbnail */}
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
