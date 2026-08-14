'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Layers, BarChart3, Eye, Check, Loader2 } from 'lucide-react';
import ToolLayout, { ActionButton } from '../../components/ToolLayout';
import ParameterCard, { SliderControl, SelectControl, ToggleControl } from '../../components/ParameterCard';
import SeamHighlight from '../../components/SeamHighlight';
import BeforeAfterSlider from '../../components/BeforeAfterSlider';
import {
  seamlessAnalyze,
  seamlessPreview,
  seamlessApply,
  getToolImage,
  getFullUrl,
} from '@/lib/api';

interface SeamScores {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

const methodDescriptions: Record<string, string> = {
  overlay: 'Shifts the image by half and blends the overlapping regions. Good general-purpose method for most textures.',
  mirror: 'Folds edges inward creating a mirrored blend zone. Works well with organic patterns but can create symmetry artifacts.',
  poisson: 'Solves in the gradient domain for seamless boundaries. Best quality but slower — ideal for textures with strong features.',
};

export default function SeamlessPage() {
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

  // Parameters
  const [method, setMethod] = useState('overlay');
  const [blendWidth, setBlendWidth] = useState(128);
  const [spotsRemoval, setSpotsRemoval] = useState(false);
  const [colorEqualizer, setColorEqualizer] = useState(0);
  const [tileCount, setTileCount] = useState('3');

  // Show seam toggle
  const [showSeamLine, setShowSeamLine] = useState(false);

  // Seam scores (original / before)
  const [seamScores, setSeamScores] = useState<SeamScores | undefined>(undefined);
  const [overallScore, setOverallScore] = useState<number | undefined>(undefined);

  // After scores (from preview)
  const [afterScores, setAfterScores] = useState<SeamScores | undefined>(undefined);
  const [afterOverallScore, setAfterOverallScore] = useState<number | undefined>(undefined);

  // Processing state
  const [analyzing, setAnalyzing] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [previewData, setPreviewData] = useState<{
    seamlessUrl: string;
    tiledUrl: string;
    originalUrl: string;
    scores: SeamScores;
  } | null>(null);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  // Load top image
  useEffect(() => {
    (async () => {
      try {
        const res = await getToolImage(batchName, 'seamless');
        const data = res.data;
        const url = getFullUrl(data.preview_url);
        setImageUrl(url);

        // Load image to get actual dimensions
        const img = new Image();
        img.src = url;
        await new Promise<void>((resolve, reject) => {
          img.onload = () => resolve();
          img.onerror = () => reject(new Error('Failed to load image'));
        });
        setImageWidth(data.width || img.naturalWidth);
        setImageHeight(data.height || img.naturalHeight);
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

  // Analyze seams
  const handleAnalyze = useCallback(async () => {
    setAnalyzing(true);
    try {
      const res = await seamlessAnalyze(batchName, blendWidth);
      if (res.data.success) {
        setSeamScores(res.data.scores);
        setOverallScore(res.data.overall_score);
      }
    } catch (err: any) {
      setResult({ success: false, message: err.response?.data?.detail || 'Analysis failed' });
    } finally {
      setAnalyzing(false);
    }
  }, [batchName, blendWidth]);

  // Auto-analyze on load (once image is loaded)
  useEffect(() => {
    if (!loading && imageUrl && !seamScores && !analyzing) {
      handleAnalyze();
    }
  }, [loading, imageUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  // Preview
  const handlePreview = useCallback(async () => {
    setPreviewing(true);
    setPreviewData(null);
    try {
      const res = await seamlessPreview(batchName, {
        method,
        blend_width: blendWidth,
        spots_removal: spotsRemoval,
        color_equalizer: colorEqualizer,
        tile_count: parseInt(tileCount),
      });
      if (res.data.success) {
        const cacheBust = `?t=${Date.now()}`;
        setPreviewData({
          seamlessUrl: getFullUrl(res.data.preview_url) + cacheBust,
          tiledUrl: getFullUrl(res.data.tiled_url) + cacheBust,
          originalUrl: getFullUrl(res.data.original_url) + cacheBust,
          scores: res.data.seam_scores,
        });
        // Store after scores separately
        setAfterScores(res.data.seam_scores);
        setAfterOverallScore(res.data.overall_score);
      } else {
        setResult({ success: false, message: res.data.error || 'Preview failed' });
      }
    } catch (err: any) {
      setResult({ success: false, message: err.response?.data?.detail || 'Preview failed' });
    } finally {
      setPreviewing(false);
    }
  }, [batchName, method, blendWidth, spotsRemoval, colorEqualizer, tileCount]);

  // Apply
  const handleApply = useCallback(async () => {
    setApplying(true);
    try {
      const res = await seamlessApply(batchName, {
        method,
        blend_width: blendWidth,
        spots_removal: spotsRemoval,
        color_equalizer: colorEqualizer,
      });
      if (res.data.success) {
        setResult({
          success: true,
          message: `Made ${res.data.processed}/${res.data.total} images seamless`,
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
  }, [batchName, method, blendWidth, spotsRemoval, colorEqualizer, router]);

  const scoreColorClass = (score: number) => {
    if (score < 10) return 'text-green-400';
    if (score < 30) return 'text-yellow-400';
    return 'text-red-400';
  };

  const sidebar = (
    <>
      {/* Seam Analysis */}
      <ParameterCard title="Seam Analysis" description="Measure edge continuity before processing">
        <button
          onClick={handleAnalyze}
          disabled={analyzing}
          className="w-full flex items-center justify-center gap-2 py-2 bg-violet-600 hover:bg-violet-500
            disabled:opacity-50 text-white text-sm rounded-xl transition-colors"
        >
          {analyzing ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />}
          Analyze Seams
        </button>

        {/* Score display: before / after comparison */}
        {overallScore !== undefined && (
          <div className="mt-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400">Overall Score</span>
              <div className="flex items-center gap-2">
                <span className={`text-sm font-mono font-medium ${scoreColorClass(overallScore)}`}>
                  {overallScore.toFixed(1)}
                </span>
                {afterOverallScore !== undefined && (
                  <>
                    <span className="text-xs text-slate-500">→</span>
                    <span className={`text-sm font-mono font-medium ${scoreColorClass(afterOverallScore)}`}>
                      {afterOverallScore.toFixed(1)}
                    </span>
                  </>
                )}
              </div>
            </div>
            <span className="text-[10px] text-slate-500">(lower is better)</span>
          </div>
        )}
      </ParameterCard>

      {/* Method & parameters */}
      <ParameterCard title="Parameters" description="Configure seamless generation">
        <SelectControl
          label="Method"
          value={method}
          onChange={setMethod}
          options={[
            { value: 'overlay', label: 'Overlay (Shifted blend)' },
            { value: 'mirror', label: 'Mirror (Edge fold)' },
            { value: 'poisson', label: 'Poisson (Gradient domain)' },
          ]}
        />
        {/* Method description */}
        <p className="text-[11px] text-slate-500 leading-relaxed -mt-1">
          {methodDescriptions[method]}
        </p>
        <SliderControl
          label="Blend Width"
          value={blendWidth}
          min={32}
          max={512}
          step={16}
          unit="px"
          onChange={setBlendWidth}
          tooltip="Width of the blend zone at each edge"
        />
        <ToggleControl
          label="Spots Removal"
          value={spotsRemoval}
          onChange={setSpotsRemoval}
          tooltip="Apply median filter to seam zones to remove artifacts"
        />
        <SliderControl
          label="Color Equalizer"
          value={colorEqualizer}
          min={0}
          max={50}
          step={1}
          onChange={setColorEqualizer}
          tooltip="Equalize color across seam boundaries"
        />
        <SelectControl
          label="Tile Preview Count"
          value={tileCount}
          onChange={setTileCount}
          options={[
            { value: '2', label: '2 x 2' },
            { value: '3', label: '3 x 3' },
            { value: '4', label: '4 x 4' },
          ]}
        />
      </ParameterCard>

      {/* Display options */}
      <ParameterCard title="Display">
        <ToggleControl
          label="Show Seam Lines"
          value={showSeamLine}
          onChange={setShowSeamLine}
          tooltip="Highlight the center seam cross at 50% x/y"
        />
      </ParameterCard>

      {/* Preview button */}
      <ParameterCard title="Preview">
        <button
          onClick={handlePreview}
          disabled={previewing}
          className="w-full flex items-center justify-center gap-2 py-2 bg-blue-600 hover:bg-blue-500
            disabled:opacity-50 text-white text-sm rounded-xl transition-colors"
        >
          {previewing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Eye className="w-4 h-4" />}
          Generate Preview
        </button>
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
      <ActionButton onClick={handleApply} loading={applying}>
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
      toolName="Make Seamless"
      toolIcon={<Layers className="w-4 h-4 text-teal-400" />}
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
                onClick={() => { setPreviewData(null); setAfterScores(undefined); setAfterOverallScore(undefined); }}
                className="text-xs text-teal-400 hover:text-teal-300"
              >
                Back to editor
              </button>
            </div>
            {/* Before/After slider */}
            <BeforeAfterSlider
              beforeUrl={previewData.originalUrl}
              afterUrl={previewData.seamlessUrl}
              width={imageWidth || 1200}
              height={imageHeight || 800}
              label={{ before: 'Original', after: 'Seamless' }}
            />
            {/* Tiled preview */}
            <div>
              <span className="text-xs text-slate-500 mb-1 block">Tiled Preview ({tileCount}x{tileCount})</span>
              <img
                src={previewData.tiledUrl}
                alt="Tiled preview"
                className="max-w-full rounded-xl border border-slate-700/50"
              />
            </div>
          </div>
        ) : imageUrl ? (
          <SeamHighlight
            imageUrl={imageUrl}
            imageWidth={imageWidth}
            imageHeight={imageHeight}
            blendWidth={blendWidth}
            seamScores={seamScores}
            containerWidth={containerWidth}
            containerHeight={containerHeight}
            showSeamLine={showSeamLine}
          />
        ) : null}
      </div>
    </ToolLayout>
  );
}
