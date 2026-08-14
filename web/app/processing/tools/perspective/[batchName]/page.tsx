'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Crosshair, Wand2, Eye, Check, Loader2 } from 'lucide-react';
import ToolLayout, { ActionButton } from '../../components/ToolLayout';
import ParameterCard from '../../components/ParameterCard';
import DraggableCorners from '../../components/DraggableCorners';
import BeforeAfterSlider from '../../components/BeforeAfterSlider';
import {
  perspectiveDetectLines,
  perspectivePreview,
  perspectiveApply,
  getToolImage,
  getFullUrl,
  CropPoint,
} from '@/lib/api';

export default function PerspectivePage() {
  const params = useParams();
  const router = useRouter();
  const batchName = params.batchName as string;
  const containerRef = useRef<HTMLDivElement>(null);

  // Image state
  const [imageUrl, setImageUrl] = useState('');
  const [imageWidth, setImageWidth] = useState(0);
  const [imageHeight, setImageHeight] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Container dimensions
  const [containerWidth, setContainerWidth] = useState(800);
  const [containerHeight, setContainerHeight] = useState(600);

  // Corner points (TL, TR, BR, BL in image coordinates)
  const [points, setPoints] = useState<CropPoint[]>([]);

  // Preview state
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [detecting, setDetecting] = useState(false);
  const [previewData, setPreviewData] = useState<{
    previewUrl: string;
    originalUrl: string;
    width: number;
    height: number;
  } | null>(null);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  // Load top image
  useEffect(() => {
    (async () => {
      try {
        const res = await getToolImage(batchName, 'perspective');
        const data = res.data;
        setImageUrl(getFullUrl(data.preview_url));
        setImageWidth(data.width);
        setImageHeight(data.height);

        // Initialize points at 10% inset
        const margin = 0.1;
        setPoints([
          { x: Math.round(data.width * margin), y: Math.round(data.height * margin) },
          { x: Math.round(data.width * (1 - margin)), y: Math.round(data.height * margin) },
          { x: Math.round(data.width * (1 - margin)), y: Math.round(data.height * (1 - margin)) },
          { x: Math.round(data.width * margin), y: Math.round(data.height * (1 - margin)) },
        ]);
      } catch (err: any) {
        setError(err.response?.data?.detail || 'Failed to load image');
      } finally {
        setLoading(false);
      }
    })();
  }, [batchName]);

  // Measure container
  useEffect(() => {
    const measure = () => {
      if (containerRef.current) {
        setContainerWidth(containerRef.current.clientWidth);
        setContainerHeight(containerRef.current.clientHeight);
      }
    };
    measure();
    const observer = new ResizeObserver(measure);
    if (containerRef.current) observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [loading]);

  // Auto-detect lines
  const handleDetectLines = useCallback(async () => {
    setDetecting(true);
    try {
      const res = await perspectiveDetectLines(batchName);
      if (res.data.success && res.data.suggested_corners) {
        setPoints(res.data.suggested_corners);
        setPreviewData(null);
      }
    } catch (err: any) {
      setResult({ success: false, message: err.response?.data?.detail || 'Detection failed' });
    } finally {
      setDetecting(false);
    }
  }, [batchName]);

  // Preview
  const handlePreview = useCallback(async () => {
    if (points.length !== 4) return;
    setPreviewing(true);
    setPreviewData(null);
    try {
      const res = await perspectivePreview(batchName, points);
      if (res.data.success) {
        setPreviewData({
          previewUrl: getFullUrl(res.data.preview_url),
          originalUrl: getFullUrl(res.data.original_url),
          width: res.data.width,
          height: res.data.height,
        });
      } else {
        setResult({ success: false, message: res.data.error || 'Preview failed' });
      }
    } catch (err: any) {
      setResult({ success: false, message: err.response?.data?.detail || 'Preview failed' });
    } finally {
      setPreviewing(false);
    }
  }, [batchName, points]);

  // Apply
  const handleApply = useCallback(async () => {
    if (points.length !== 4) return;
    setApplying(true);
    try {
      const res = await perspectiveApply(batchName, points);
      if (res.data.success) {
        setResult({
          success: true,
          message: `Corrected ${res.data.processed}/${res.data.total} images`,
        });
        setTimeout(() => router.push('/processing'), 1500);
      } else {
        setResult({ success: false, message: res.data.error || 'Apply failed' });
      }
    } catch (err: any) {
      setResult({ success: false, message: err.response?.data?.detail || 'Apply failed' });
    } finally {
      setApplying(false);
    }
  }, [batchName, points, router]);

  const sidebar = (
    <>
      {/* Auto-detect */}
      <ParameterCard title="Line Detection" description="Use Hough transform to find dominant lines">
        <button
          onClick={handleDetectLines}
          disabled={detecting}
          className="w-full flex items-center justify-center gap-2 py-2 bg-violet-600 hover:bg-violet-500
            disabled:opacity-50 text-white text-sm rounded-xl transition-colors"
        >
          {detecting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
          Auto-detect Lines
        </button>
      </ParameterCard>

      {/* Corner coordinates (readonly) */}
      <ParameterCard title="Corner Points" description="Drag corners on the canvas to adjust">
        <div className="space-y-2">
          {['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left'].map((label, i) => (
            <div key={label} className="flex items-center gap-2">
              <span className="text-xs text-slate-500 w-20 shrink-0">{label}</span>
              <input
                readOnly
                value={points[i] ? `${points[i].x}, ${points[i].y}` : '—'}
                className="flex-1 bg-slate-700/50 border border-slate-600/50 rounded-lg px-2 py-1
                  text-xs font-mono text-slate-300 cursor-default"
              />
            </div>
          ))}
        </div>
      </ParameterCard>

      {/* Preview / Apply */}
      <ParameterCard title="Actions">
        <div className="space-y-2">
          <button
            onClick={handlePreview}
            disabled={previewing || points.length !== 4}
            className="w-full flex items-center justify-center gap-2 py-2 bg-blue-600 hover:bg-blue-500
              disabled:opacity-50 text-white text-sm rounded-xl transition-colors"
          >
            {previewing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Eye className="w-4 h-4" />}
            Preview
          </button>
        </div>
      </ParameterCard>

      {/* Result toast */}
      {result && (
        <div
          className={`p-3 rounded-xl text-sm ${
            result.success
              ? 'bg-green-500/10 text-green-400 border border-green-500/20'
              : 'bg-red-500/10 text-red-400 border border-red-500/20'
          }`}
        >
          {result.message}
        </div>
      )}
    </>
  );

  const actionBar = (
    <>
      <ActionButton onClick={() => router.push('/processing')} variant="secondary">
        Cancel
      </ActionButton>
      <ActionButton
        onClick={handleApply}
        disabled={points.length !== 4}
        loading={applying}
      >
        <span className="flex items-center gap-2">
          <Check className="w-4 h-4" />
          Apply to All Images
        </span>
      </ActionButton>
    </>
  );

  return (
    <ToolLayout
      batchName={batchName}
      toolName="Perspective Correction"
      toolIcon={<Crosshair className="w-4 h-4 text-teal-400" />}
      sidebar={sidebar}
      actionBar={actionBar}
      loading={loading}
      error={error}
    >
      <div ref={containerRef} className="w-full h-full min-h-[400px]">
        {previewData ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm text-slate-400">Before / After comparison</span>
              <button
                onClick={() => setPreviewData(null)}
                className="text-xs text-teal-400 hover:text-teal-300"
              >
                Back to editor
              </button>
            </div>
            <BeforeAfterSlider
              beforeUrl={previewData.originalUrl}
              afterUrl={previewData.previewUrl}
              width={previewData.width}
              height={previewData.height}
              label={{ before: 'Original', after: 'Corrected' }}
            />
          </div>
        ) : imageUrl && points.length === 4 ? (
          <DraggableCorners
            imageUrl={imageUrl}
            imageWidth={imageWidth}
            imageHeight={imageHeight}
            points={points}
            onPointsChange={setPoints}
            containerWidth={containerWidth}
            containerHeight={containerHeight}
          />
        ) : null}
      </div>
    </ToolLayout>
  );
}
