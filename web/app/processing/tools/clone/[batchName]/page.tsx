'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { Stamp, Loader2 } from 'lucide-react';
import dynamic from 'next/dynamic';
import ToolLayout, { ActionButton } from '../../components/ToolLayout';
import ParameterCard, { SliderControl, ToggleControl, SelectControl } from '../../components/ParameterCard';
import { getToolImage, cloneInpaint, cloneApply, cloneStamp, getFullUrl } from '@/lib/api';

const BrushCanvas = dynamic(() => import('../../components/BrushCanvas'), { ssr: false });

interface StampOperation {
  type: 'stamp';
  source_pos: { x: number; y: number };
  target_pos: { x: number; y: number };
  radius: number;
  fade: number;
  blur_mask: number;
  mirror: boolean;
}

export default function ClonePage() {
  const params = useParams();
  const batchName = params.batchName as string;
  const containerRef = useRef<HTMLDivElement>(null);

  // Image state
  const [imageUrl, setImageUrl] = useState<string>('');
  const [imageWidth, setImageWidth] = useState(0);
  const [imageHeight, setImageHeight] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Processing state
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [applyResult, setApplyResult] = useState<string | null>(null);

  // Mode: inpaint or stamp
  const [isInpaintMode, setIsInpaintMode] = useState(true);

  // Inpaint params
  const [brushRadius, setBrushRadius] = useState(15);
  const [inpaintMethod, setInpaintMethod] = useState('telea');
  const [maskData, setMaskData] = useState<string>('');

  // Stamp params
  const [fade, setFade] = useState(0.8);
  const [blurMask, setBlurMask] = useState(0.3);
  const [stampRadius, setStampRadius] = useState(25);
  const [sourcePoint, setSourcePoint] = useState<{ x: number; y: number } | null>(null);
  const [operations, setOperations] = useState<StampOperation[]>([]);

  // Container
  const [containerSize, setContainerSize] = useState({ w: 600, h: 600 });

  // Load image
  useEffect(() => {
    const load = async () => {
      try {
        const res = await getToolImage(batchName, 'clone');
        const imgUrl = res.data?.image_url || res.data?.url || res.data?.preview_url;
        if (!imgUrl) {
          setError('No source image found');
          return;
        }
        const url = getFullUrl(imgUrl);
        setImageUrl(url);

        // Load image to get actual dimensions
        const img = new Image();
        img.src = url;
        await new Promise<void>((resolve, reject) => {
          img.onload = () => resolve();
          img.onerror = () => reject(new Error('Failed to load image'));
        });
        setImageWidth(res.data.width || img.naturalWidth);
        setImageHeight(res.data.height || img.naturalHeight);
      } catch {
        setError('Failed to load batch image');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [batchName]);

  // Measure container
  useEffect(() => {
    const measure = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setContainerSize({ w: rect.width - 16, h: rect.height - 16 });
      }
    };
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [loading]);

  // Handle mask change from BrushCanvas
  const handleMaskChange = useCallback((dataUrl: string) => {
    setMaskData(dataUrl);
  }, []);

  // Stamp click handler
  const handleStampClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (isInpaintMode || !containerRef.current) return;

    const rect = containerRef.current.getBoundingClientRect();
    const scaleX = imageWidth / containerSize.w;
    const scaleY = imageHeight / containerSize.h;
    const displayScale = Math.max(scaleX, scaleY);

    const x = (e.clientX - rect.left) * displayScale;
    const y = (e.clientY - rect.top) * displayScale;
    const point = { x: Math.round(x), y: Math.round(y) };

    if (!sourcePoint) {
      setSourcePoint(point);
    } else {
      const op: StampOperation = {
        type: 'stamp',
        source_pos: sourcePoint,
        target_pos: point,
        radius: stampRadius,
        fade,
        blur_mask: blurMask,
        mirror: false,
      };
      setOperations((prev) => [...prev, op]);
      setSourcePoint(null);
    }
  }, [isInpaintMode, sourcePoint, stampRadius, fade, blurMask, imageWidth, imageHeight, containerSize]);

  // Preview
  const handlePreview = useCallback(async () => {
    setPreviewing(true);
    setPreviewUrl(null);
    try {
      if (isInpaintMode && maskData) {
        const res = await cloneInpaint(batchName, maskData, {
          method: inpaintMethod,
          radius: 3,
        });
        if (res.data?.preview_url) {
          setPreviewUrl(getFullUrl(res.data.preview_url) + `?t=${Date.now()}`);
        }
      } else if (!isInpaintMode && operations.length > 0) {
        const lastOp = operations[operations.length - 1];
        const res = await cloneStamp(batchName, {
          source_pos: lastOp.source_pos,
          target_pos: lastOp.target_pos,
          radius: lastOp.radius,
          fade: lastOp.fade,
          blur_mask: lastOp.blur_mask,
        });
        if (res.data?.preview_url) {
          setPreviewUrl(getFullUrl(res.data.preview_url) + `?t=${Date.now()}`);
        }
      }
    } catch {
      // ignore
    } finally {
      setPreviewing(false);
    }
  }, [batchName, isInpaintMode, maskData, inpaintMethod, operations]);

  // Apply
  const handleApply = useCallback(async () => {
    setApplying(true);
    setApplyResult(null);
    try {
      const ops = isInpaintMode
        ? [{ type: 'inpaint', mask_data: maskData, method: inpaintMethod, radius: 3 }]
        : operations;
      const res = await cloneApply(batchName, ops);
      if (res.data?.success) {
        setApplyResult('Applied successfully');
      } else {
        setApplyResult('Apply failed');
      }
    } catch {
      setApplyResult('Apply failed');
    } finally {
      setApplying(false);
    }
  }, [batchName, isInpaintMode, maskData, inpaintMethod, operations]);

  const sidebar = (
    <>
      {/* Mode toggle */}
      <ParameterCard title="Mode">
        <div className="flex gap-2">
          <button
            onClick={() => setIsInpaintMode(true)}
            className={`flex-1 py-2 rounded-lg text-sm transition-colors ${
              isInpaintMode
                ? 'bg-teal-600 text-white'
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            Inpaint
          </button>
          <button
            onClick={() => setIsInpaintMode(false)}
            className={`flex-1 py-2 rounded-lg text-sm transition-colors ${
              !isInpaintMode
                ? 'bg-teal-600 text-white'
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            Clone Stamp
          </button>
        </div>
      </ParameterCard>

      {/* Inpaint params */}
      {isInpaintMode && (
        <ParameterCard title="Inpaint Settings" description="Paint over areas to remove">
          <SliderControl
            label="Brush Radius"
            value={brushRadius}
            min={5}
            max={50}
            step={1}
            unit="px"
            onChange={setBrushRadius}
          />
          <SelectControl
            label="Method"
            value={inpaintMethod}
            options={[
              { value: 'telea', label: 'Telea (Fast Marching)' },
              { value: 'navier-stokes', label: 'Navier-Stokes' },
            ]}
            onChange={setInpaintMethod}
          />
          <p className="text-[11px] text-slate-500 leading-relaxed -mt-1">
            {inpaintMethod === 'telea'
              ? 'Fast marching method that fills inward from known boundaries. Fast and good for small defects.'
              : 'Fluid dynamics approach using Navier-Stokes equations. Better for larger areas and curved features.'}
          </p>
        </ParameterCard>
      )}

      {/* Clone stamp params */}
      {!isInpaintMode && (
        <ParameterCard title="Clone Stamp" description="Click source, then click target">
          <SliderControl
            label="Brush Radius"
            value={stampRadius}
            min={5}
            max={50}
            step={1}
            unit="px"
            onChange={setStampRadius}
          />
          <SliderControl
            label="Fade"
            value={fade}
            min={0}
            max={1}
            step={0.05}
            onChange={setFade}
          />
          <SliderControl
            label="Edge Blur"
            value={blurMask}
            min={0}
            max={1}
            step={0.05}
            onChange={setBlurMask}
          />
          {sourcePoint && (
            <div className="text-xs text-teal-400">
              Source: ({sourcePoint.x}, {sourcePoint.y}) — click target
            </div>
          )}
          {operations.length > 0 && (
            <div className="text-xs text-slate-400">
              {operations.length} stamp operation{operations.length !== 1 ? 's' : ''} queued
            </div>
          )}
          <button
            onClick={() => { setOperations([]); setSourcePoint(null); }}
            className="w-full py-1.5 bg-slate-700 text-slate-300 rounded-lg text-xs hover:bg-slate-600"
          >
            Clear Operations
          </button>
        </ParameterCard>
      )}

      {/* Preview result */}
      {previewUrl && (
        <ParameterCard title="Preview">
          <img
            src={previewUrl}
            alt="Preview"
            className="w-full rounded-lg border border-slate-700/50"
          />
        </ParameterCard>
      )}

      {applyResult && (
        <div className={`text-sm px-3 py-2 rounded-lg ${
          applyResult.includes('success') ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
        }`}>
          {applyResult}
        </div>
      )}
    </>
  );

  const canPreview = isInpaintMode ? !!maskData : operations.length > 0;
  const canApply = isInpaintMode ? !!maskData : operations.length > 0;

  const actionBar = (
    <>
      <ActionButton onClick={handlePreview} loading={previewing} disabled={!canPreview} variant="secondary">
        Preview
      </ActionButton>
      <ActionButton onClick={handleApply} loading={applying} disabled={!canApply}>
        Apply
      </ActionButton>
    </>
  );

  return (
    <ToolLayout
      batchName={batchName}
      toolName="Clone / Inpaint"
      toolIcon={<Stamp className="w-4 h-4 text-rose-400" />}
      sidebar={sidebar}
      actionBar={actionBar}
      loading={loading}
      error={error}
    >
      <div
        ref={containerRef}
        className="w-full h-full min-h-[400px]"
        onClick={!isInpaintMode ? handleStampClick : undefined}
      >
        {imageUrl && isInpaintMode && containerSize.w > 0 && (
          <BrushCanvas
            imageUrl={imageUrl}
            imageWidth={imageWidth}
            imageHeight={imageHeight}
            brushRadius={brushRadius}
            containerWidth={containerSize.w}
            containerHeight={containerSize.h}
            onMaskChange={handleMaskChange}
          />
        )}
        {imageUrl && !isInpaintMode && (
          <div className="relative w-full h-full">
            <img
              src={previewUrl || imageUrl}
              alt="Clone source"
              className="w-full h-full object-contain rounded-xl"
            />
            {sourcePoint && (
              <div
                className="absolute w-6 h-6 border-2 border-teal-400 rounded-full -translate-x-1/2 -translate-y-1/2 pointer-events-none animate-pulse"
                style={{
                  left: `${(sourcePoint.x / imageWidth) * 100}%`,
                  top: `${(sourcePoint.y / imageHeight) * 100}%`,
                }}
              />
            )}
          </div>
        )}
        {!imageUrl && !loading && (
          <div className="flex items-center justify-center h-full text-slate-500">
            No image available
          </div>
        )}
      </div>
    </ToolLayout>
  );
}
