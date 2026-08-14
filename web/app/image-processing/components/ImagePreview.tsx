'use client';

import { useState } from 'react';
import { Loader2, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';
import { getFullUrl } from '@/lib/api';

interface ImagePreviewProps {
  imageUrl: string | null;
  isLoading?: boolean;
  label?: string;
  exposureOffset?: number | null;
}

export default function ImagePreview({ imageUrl, isLoading, label, exposureOffset }: ImagePreviewProps) {
  const [zoom, setZoom] = useState(1);

  const handleZoomIn = () => setZoom((z) => Math.min(z + 0.25, 4));
  const handleZoomOut = () => setZoom((z) => Math.max(z - 0.25, 0.25));
  const handleFit = () => setZoom(1);

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800 shrink-0">
        <span className="text-xs text-slate-400">{label || 'Preview'}</span>
        <div className="flex items-center gap-1">
          <button
            onClick={handleZoomOut}
            className="p-1 text-slate-400 hover:text-slate-200 rounded hover:bg-slate-800"
            title="Zoom Out"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <span className="text-xs text-slate-500 w-10 text-center font-mono">
            {Math.round(zoom * 100)}%
          </span>
          <button
            onClick={handleZoomIn}
            className="p-1 text-slate-400 hover:text-slate-200 rounded hover:bg-slate-800"
            title="Zoom In"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleFit}
            className="p-1 text-slate-400 hover:text-slate-200 rounded hover:bg-slate-800"
            title="Fit"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Image area */}
      <div className="flex-1 overflow-auto bg-slate-950 flex items-center justify-center">
        {isLoading ? (
          <div className="flex flex-col items-center gap-2 text-slate-500">
            <Loader2 className="w-6 h-6 animate-spin text-teal-400" />
            <span className="text-xs">Rendering preview...</span>
          </div>
        ) : imageUrl ? (
          <img
            src={getFullUrl(imageUrl)}
            alt="Pipeline preview"
            style={{
              transform: `scale(${zoom})`,
              transformOrigin: 'center',
              filter: exposureOffset != null ? `brightness(${Math.pow(2, exposureOffset)})` : undefined,
            }}
            className="max-w-full max-h-full object-contain transition-transform"
          />
        ) : (
          <div className="text-slate-600 text-sm">
            No preview available — adjust parameters and click Preview
          </div>
        )}
      </div>
    </div>
  );
}
