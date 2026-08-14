'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { Grid3x3, Box, Loader2 } from 'lucide-react';
import dynamic from 'next/dynamic';
import ToolLayout, { ActionButton } from '../../components/ToolLayout';
import ParameterCard, { SliderControl, ToggleControl, SelectControl } from '../../components/ParameterCard';
import { getToolImage, tileApply, getFullUrl } from '@/lib/api';

const TileGrid = dynamic(() => import('../../components/TileGrid'), { ssr: false });
const ThreePreview = dynamic(() => import('../../components/ThreePreview'), { ssr: false });

export default function TilingPage() {
  const params = useParams();
  const batchName = params.batchName as string;
  const containerRef = useRef<HTMLDivElement>(null);

  // Image state
  const [imageUrl, setImageUrl] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState<string | null>(null);

  // View mode
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d');

  // Tile params
  const [tileX, setTileX] = useState(3);
  const [tileY, setTileY] = useState(3);
  const [offsetX, setOffsetX] = useState(0);
  const [offsetY, setOffsetY] = useState(0);
  const [scale, setScale] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [overlap, setOverlap] = useState(0);
  const [halfDrop, setHalfDrop] = useState(false);
  const [showGridLines, setShowGridLines] = useState(true);

  // 3D params
  const [geometry, setGeometry] = useState('plane');
  const [roughness, setRoughness] = useState(0.8);
  const [metalness, setMetalness] = useState(0);

  // Output resolution
  const [outputRes, setOutputRes] = useState('2048');

  // Container size
  const [containerSize, setContainerSize] = useState({ w: 600, h: 600 });

  // Load image
  useEffect(() => {
    const load = async () => {
      try {
        const res = await getToolImage(batchName, 'tile');
        const imgUrl = res.data?.preview_url || res.data?.image_url || res.data?.url;
        if (imgUrl) {
          setImageUrl(getFullUrl(imgUrl));
        } else {
          setError('No source image found for tiling');
        }
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

  // Export
  const handleExport = useCallback(async () => {
    setExporting(true);
    setExportResult(null);
    try {
      const res = parseInt(outputRes);
      await tileApply(batchName, {
        tile_x: tileX,
        tile_y: tileY,
        offset_x: offsetX,
        offset_y: offsetY,
        scale,
        rotation,
        overlap,
        half_drop: halfDrop,
        output_resolution: [res, res],
      });
      setExportResult('Exported successfully');
    } catch {
      setExportResult('Export failed');
    } finally {
      setExporting(false);
    }
  }, [batchName, tileX, tileY, offsetX, offsetY, scale, rotation, overlap, halfDrop, outputRes]);

  const sidebar = (
    <>
      {/* View mode toggle */}
      <ParameterCard title="View Mode">
        <div className="flex gap-2">
          <button
            onClick={() => setViewMode('2d')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm transition-colors ${
              viewMode === '2d'
                ? 'bg-teal-600 text-white'
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            <Grid3x3 className="w-4 h-4" />
            2D Grid
          </button>
          <button
            onClick={() => setViewMode('3d')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm transition-colors ${
              viewMode === '3d'
                ? 'bg-teal-600 text-white'
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            <Box className="w-4 h-4" />
            3D Preview
          </button>
        </div>
      </ParameterCard>

      {/* Tile settings */}
      <ParameterCard title="Tile Grid" description="Control tile layout and repetition">
        <SliderControl label="Tiles X" value={tileX} min={1} max={8} step={1} onChange={setTileX} />
        <SliderControl label="Tiles Y" value={tileY} min={1} max={8} step={1} onChange={setTileY} />
        <SliderControl label="Offset X" value={offsetX} min={0} max={0.5} step={0.05} onChange={setOffsetX} />
        <SliderControl label="Offset Y" value={offsetY} min={0} max={0.5} step={0.05} onChange={setOffsetY} />
        <SliderControl label="Scale" value={scale} min={0.25} max={4} step={0.05} onChange={setScale} />
        <SliderControl label="Rotation" value={rotation} min={-180} max={180} step={1} unit="°" onChange={setRotation} />
        <SliderControl label="Overlap" value={overlap} min={0} max={0.5} step={0.01} onChange={setOverlap} />
        <ToggleControl label="Half Drop" value={halfDrop} onChange={setHalfDrop} />
        {viewMode === '2d' && (
          <ToggleControl label="Grid Lines" value={showGridLines} onChange={setShowGridLines} />
        )}
      </ParameterCard>

      {/* 3D settings */}
      {viewMode === '3d' && (
        <ParameterCard title="3D Settings">
          <SelectControl
            label="Geometry"
            value={geometry}
            options={[
              { value: 'plane', label: 'Plane' },
              { value: 'cylinder', label: 'Cylinder' },
            ]}
            onChange={setGeometry}
          />
          <SliderControl label="Roughness" value={roughness} min={0} max={1} step={0.05} onChange={setRoughness} />
          <SliderControl label="Metalness" value={metalness} min={0} max={1} step={0.05} onChange={setMetalness} />
        </ParameterCard>
      )}

      {/* Sidebar mini tile preview */}
      {imageUrl && viewMode === '2d' && (
        <ParameterCard title="Quick Preview">
          <div className="rounded-lg overflow-hidden border border-slate-700/50 bg-slate-900">
            <TileGrid
              imageUrl={imageUrl}
              tileX={tileX}
              tileY={tileY}
              offsetX={offsetX}
              offsetY={offsetY}
              scale={scale}
              rotation={rotation}
              overlap={overlap}
              halfDrop={halfDrop}
              containerWidth={240}
              containerHeight={240}
              showGridLines={showGridLines}
            />
          </div>
        </ParameterCard>
      )}

      {/* Output */}
      <ParameterCard title="Export Settings">
        <SelectControl
          label="Output Resolution"
          value={outputRes}
          options={[
            { value: '1024', label: '1024 × 1024' },
            { value: '2048', label: '2048 × 2048' },
            { value: '4096', label: '4096 × 4096' },
          ]}
          onChange={setOutputRes}
        />
      </ParameterCard>

      {exportResult && (
        <div className={`text-sm px-3 py-2 rounded-lg ${
          exportResult.includes('success') ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
        }`}>
          {exportResult}
        </div>
      )}
    </>
  );

  const actionBar = (
    <ActionButton onClick={handleExport} loading={exporting} disabled={!imageUrl}>
      Export Tiled Texture
    </ActionButton>
  );

  return (
    <ToolLayout
      batchName={batchName}
      toolName="Tiling"
      toolIcon={<Grid3x3 className="w-4 h-4 text-emerald-400" />}
      sidebar={sidebar}
      actionBar={actionBar}
      loading={loading}
      error={error}
    >
      <div ref={containerRef} className="w-full h-full min-h-[400px]">
        {imageUrl && viewMode === '2d' && containerSize.w > 0 && (
          <TileGrid
            imageUrl={imageUrl}
            tileX={tileX}
            tileY={tileY}
            offsetX={offsetX}
            offsetY={offsetY}
            scale={scale}
            rotation={rotation}
            overlap={overlap}
            halfDrop={halfDrop}
            containerWidth={containerSize.w}
            containerHeight={containerSize.h}
            showGridLines={showGridLines}
          />
        )}
        {imageUrl && viewMode === '3d' && (
          <ThreePreview
            textureUrl={imageUrl}
            geometry={geometry as 'plane' | 'cylinder'}
            roughness={roughness}
            metalness={metalness}
            tileRepeat={[tileX, tileY]}
          />
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
