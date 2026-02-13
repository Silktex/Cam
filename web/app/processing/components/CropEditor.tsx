'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import {
  RotateCcw, RotateCw, Check, Wand2, Loader2,
  RefreshCcw, ZoomIn, ZoomOut, RectangleHorizontal, Square
} from 'lucide-react';

interface Point {
  x: number;
  y: number;
}

interface CropEditorProps {
  imageUrl: string;
  originalWidth: number;
  originalHeight: number;
  isProcessing: boolean;
  onCancel: () => void;
  onAutoDetect: () => Promise<{ success: boolean; points?: Point[]; error?: string }>;
  onApply: (data: { points: Point[]; method: 'manual' | 'auto'; rotation: number }) => Promise<void>;
}

export default function CropEditor({
  imageUrl,
  originalWidth,
  originalHeight,
  isProcessing,
  onCancel,
  onAutoDetect,
  onApply,
}: CropEditorProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  // Image state
  const [imageLoaded, setImageLoaded] = useState(false);
  const [displayScale, setDisplayScale] = useState(1);

  // Crop state
  const [points, setPoints] = useState<Point[]>([]);
  const [currentPointIndex, setCurrentPointIndex] = useState(0);
  const [rotation, setRotation] = useState(0);
  const [isDragging, setIsDragging] = useState<number | null>(null);
  const [isDraggingArea, setIsDraggingArea] = useState(false);
  const [dragStart, setDragStart] = useState<Point | null>(null);
  const [scale, setScale] = useState(1);
  const [method, setMethod] = useState<'manual' | 'auto'>('manual');
  const [squareSize, setSquareSize] = useState(2048);

  // Processing state
  const [detecting, setDetecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Point labels
  const pointLabels = ['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left'];

  // Load image
  useEffect(() => {
    setImageLoaded(false);

    const img = new Image();
    img.onload = () => {
      imageRef.current = img;

      // Calculate scale to fit in viewport
      if (containerRef.current) {
        const containerWidth = containerRef.current.clientWidth - 32;
        const containerHeight = containerRef.current.clientHeight - 32;
        const scaleX = containerWidth / img.width;
        const scaleY = containerHeight / img.height;
        const fitScale = Math.min(scaleX, scaleY, 1);
        setScale(fitScale);
        setDisplayScale(originalWidth / img.width);
      }

      // Initialize points at 15% inset
      const margin = 0.15;
      setPoints([
        { x: originalWidth * margin, y: originalHeight * margin },
        { x: originalWidth * (1 - margin), y: originalHeight * margin },
        { x: originalWidth * (1 - margin), y: originalHeight * (1 - margin) },
        { x: originalWidth * margin, y: originalHeight * (1 - margin) },
      ]);

      setImageLoaded(true);
    };

    img.onerror = () => {
      setError('Failed to load image');
    };

    img.src = imageUrl;
  }, [imageUrl, originalWidth, originalHeight]);

  // Draw canvas
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imageRef.current;
    if (!canvas || !img || !imageLoaded) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const displayWidth = img.width * scale;
    const displayHeight = img.height * scale;
    canvas.width = displayWidth;
    canvas.height = displayHeight;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw image with rotation
    ctx.save();
    ctx.translate(displayWidth / 2, displayHeight / 2);
    ctx.rotate((rotation * Math.PI) / 180);
    ctx.translate(-displayWidth / 2, -displayHeight / 2);
    ctx.drawImage(img, 0, 0, displayWidth, displayHeight);
    ctx.restore();

    // Convert original coords to display coords
    const toDisplay = (p: Point) => ({
      x: (p.x / displayScale) * scale,
      y: (p.y / displayScale) * scale,
    });

    if (points.length === 4) {
      const displayPoints = points.map(toDisplay);

      // Semi-transparent overlay outside crop
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, canvas.width, canvas.height);
      ctx.moveTo(displayPoints[0].x, displayPoints[0].y);
      for (let i = points.length - 1; i >= 0; i--) {
        ctx.lineTo(displayPoints[i].x, displayPoints[i].y);
      }
      ctx.closePath();
      ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
      ctx.fill('evenodd');
      ctx.restore();

      // Crop boundary
      ctx.beginPath();
      ctx.strokeStyle = '#14b8a6';
      ctx.lineWidth = 2;
      ctx.moveTo(displayPoints[0].x, displayPoints[0].y);
      displayPoints.forEach((p, i) => {
        if (i > 0) ctx.lineTo(p.x, p.y);
      });
      ctx.closePath();
      ctx.stroke();

      // Rule-of-thirds grid
      ctx.setLineDash([5, 5]);
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.3)';
      ctx.lineWidth = 1;

      for (let i = 1; i <= 2; i++) {
        const t = i / 3;
        const h1 = {
          x: displayPoints[0].x + (displayPoints[3].x - displayPoints[0].x) * t,
          y: displayPoints[0].y + (displayPoints[3].y - displayPoints[0].y) * t,
        };
        const h2 = {
          x: displayPoints[1].x + (displayPoints[2].x - displayPoints[1].x) * t,
          y: displayPoints[1].y + (displayPoints[2].y - displayPoints[1].y) * t,
        };
        ctx.beginPath();
        ctx.moveTo(h1.x, h1.y);
        ctx.lineTo(h2.x, h2.y);
        ctx.stroke();

        const v1 = {
          x: displayPoints[0].x + (displayPoints[1].x - displayPoints[0].x) * t,
          y: displayPoints[0].y + (displayPoints[1].y - displayPoints[0].y) * t,
        };
        const v2 = {
          x: displayPoints[3].x + (displayPoints[2].x - displayPoints[3].x) * t,
          y: displayPoints[3].y + (displayPoints[2].y - displayPoints[3].y) * t,
        };
        ctx.beginPath();
        ctx.moveTo(v1.x, v1.y);
        ctx.lineTo(v2.x, v2.y);
        ctx.stroke();
      }
      ctx.setLineDash([]);

      // Corner handles
      displayPoints.forEach((p, i) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 14, 0, Math.PI * 2);
        ctx.fillStyle = i === currentPointIndex ? '#14b8a6' : '#ffffff';
        ctx.fill();
        ctx.strokeStyle = '#0d7377';
        ctx.lineWidth = 3;
        ctx.stroke();

        ctx.fillStyle = i === currentPointIndex ? '#ffffff' : '#0d7377';
        ctx.font = 'bold 14px Inter, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText((i + 1).toString(), p.x, p.y);
      });
    }
  }, [points, rotation, scale, currentPointIndex, imageLoaded, displayScale]);

  useEffect(() => {
    drawCanvas();
  }, [drawCanvas]);

  // Mouse handlers
  const getOriginalCoords = (e: React.MouseEvent): Point => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.round(((e.clientX - rect.left) / scale) * displayScale),
      y: Math.round(((e.clientY - rect.top) / scale) * displayScale),
    };
  };

  const toDisplayCoords = (p: Point): Point => ({
    x: (p.x / displayScale) * scale,
    y: (p.y / displayScale) * scale,
  });

  const isPointInPolygon = (x: number, y: number, polygon: Point[]): boolean => {
    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const xi = polygon[i].x, yi = polygon[i].y;
      const xj = polygon[j].x, yj = polygon[j].y;
      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) {
        inside = !inside;
      }
    }
    return inside;
  };

  const handleCanvasClick = (e: React.MouseEvent) => {
    if (isDragging !== null || isDraggingArea) return;

    const canvas = canvasRef.current;
    if (canvas) {
      const rect = canvas.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const clickY = e.clientY - rect.top;

      for (let i = 0; i < points.length; i++) {
        const dp = toDisplayCoords(points[i]);
        const dx = dp.x - clickX;
        const dy = dp.y - clickY;
        if (Math.sqrt(dx * dx + dy * dy) < 20) {
          setCurrentPointIndex(i);
          return;
        }
      }
    }

    if (points.length === 4) {
      const coords = getOriginalCoords(e);
      if (!isPointInPolygon(coords.x, coords.y, points)) {
        const newPoints = [...points];
        newPoints[currentPointIndex] = coords;
        setPoints(newPoints);
        setCurrentPointIndex((currentPointIndex + 1) % 4);
        setMethod('manual');
      }
    }
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    const canvas = canvasRef.current;
    if (canvas) {
      const rect = canvas.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const clickY = e.clientY - rect.top;

      for (let i = 0; i < points.length; i++) {
        const dp = toDisplayCoords(points[i]);
        if (Math.sqrt(Math.pow(dp.x - clickX, 2) + Math.pow(dp.y - clickY, 2)) < 20) {
          setIsDragging(i);
          setCurrentPointIndex(i);
          return;
        }
      }

      const coords = getOriginalCoords(e);
      if (points.length === 4 && isPointInPolygon(coords.x, coords.y, points)) {
        setIsDraggingArea(true);
        setDragStart(coords);
      }
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    const coords = getOriginalCoords(e);

    if (isDragging !== null) {
      const newPoints = [...points];
      newPoints[isDragging] = {
        x: Math.max(0, Math.min(originalWidth, coords.x)),
        y: Math.max(0, Math.min(originalHeight, coords.y)),
      };
      setPoints(newPoints);
      setMethod('manual');
      return;
    }

    if (isDraggingArea && dragStart) {
      const dx = coords.x - dragStart.x;
      const dy = coords.y - dragStart.y;

      const newPoints = points.map(p => ({
        x: p.x + dx,
        y: p.y + dy,
      }));

      const minX = Math.min(...newPoints.map(p => p.x));
      const maxX = Math.max(...newPoints.map(p => p.x));
      const minY = Math.min(...newPoints.map(p => p.y));
      const maxY = Math.max(...newPoints.map(p => p.y));

      if (minX >= 0 && maxX <= originalWidth && minY >= 0 && maxY <= originalHeight) {
        setPoints(newPoints);
        setDragStart(coords);
        setMethod('manual');
      }
    }
  };

  const handleMouseUp = () => {
    setIsDragging(null);
    setIsDraggingArea(false);
    setDragStart(null);
  };

  // Cursor style
  const [cursorStyle, setCursorStyle] = useState('crosshair');

  const handleCanvasMouseMove = (e: React.MouseEvent) => {
    handleMouseMove(e);
    if (isDragging !== null) {
      setCursorStyle('grabbing');
    } else if (isDraggingArea) {
      setCursorStyle('move');
    } else {
      const canvas = canvasRef.current;
      if (canvas && points.length === 4) {
        const rect = canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        for (let i = 0; i < points.length; i++) {
          const dp = toDisplayCoords(points[i]);
          if (Math.sqrt(Math.pow(dp.x - mouseX, 2) + Math.pow(dp.y - mouseY, 2)) < 20) {
            setCursorStyle('grab');
            return;
          }
        }

        const coords = getOriginalCoords(e);
        if (isPointInPolygon(coords.x, coords.y, points)) {
          setCursorStyle('move');
        } else {
          setCursorStyle('crosshair');
        }
      }
    }
  };

  // Actions
  const handleAutoDetect = async () => {
    setDetecting(true);
    setError(null);
    try {
      const result = await onAutoDetect();
      if (result.success && result.points) {
        setPoints(result.points);
        setMethod('auto');
      } else {
        setError(result.error || 'Auto-detect failed');
      }
    } catch (err: any) {
      setError(err.message || 'Auto-detect failed');
    } finally {
      setDetecting(false);
    }
  };

  const handleReset = () => {
    const margin = 0.15;
    setPoints([
      { x: originalWidth * margin, y: originalHeight * margin },
      { x: originalWidth * (1 - margin), y: originalHeight * margin },
      { x: originalWidth * (1 - margin), y: originalHeight * (1 - margin) },
      { x: originalWidth * margin, y: originalHeight * (1 - margin) },
    ]);
    setRotation(0);
    setCurrentPointIndex(0);
    setMethod('manual');
    setError(null);
  };

  const handleRectangularize = () => {
    if (points.length !== 4) return;

    const centerX = points.reduce((sum, p) => sum + p.x, 0) / 4;
    const centerY = points.reduce((sum, p) => sum + p.y, 0) / 4;

    const topWidth = Math.sqrt(Math.pow(points[1].x - points[0].x, 2) + Math.pow(points[1].y - points[0].y, 2));
    const bottomWidth = Math.sqrt(Math.pow(points[2].x - points[3].x, 2) + Math.pow(points[2].y - points[3].y, 2));
    const leftHeight = Math.sqrt(Math.pow(points[3].x - points[0].x, 2) + Math.pow(points[3].y - points[0].y, 2));
    const rightHeight = Math.sqrt(Math.pow(points[2].x - points[1].x, 2) + Math.pow(points[2].y - points[1].y, 2));

    const avgWidth = (topWidth + bottomWidth) / 2;
    const avgHeight = (leftHeight + rightHeight) / 2;
    const halfW = avgWidth / 2;
    const halfH = avgHeight / 2;

    setPoints([
      { x: Math.round(centerX - halfW), y: Math.round(centerY - halfH) },
      { x: Math.round(centerX + halfW), y: Math.round(centerY - halfH) },
      { x: Math.round(centerX + halfW), y: Math.round(centerY + halfH) },
      { x: Math.round(centerX - halfW), y: Math.round(centerY + halfH) },
    ]);
    setMethod('manual');
  };

  const handleSquarify = () => {
    if (points.length !== 4) return;

    const centerX = points.reduce((sum, p) => sum + p.x, 0) / 4;
    const centerY = points.reduce((sum, p) => sum + p.y, 0) / 4;
    const half = squareSize / 2;

    // Clamp center so the square stays within image bounds
    const clampedCX = Math.max(half, Math.min(originalWidth - half, centerX));
    const clampedCY = Math.max(half, Math.min(originalHeight - half, centerY));

    setPoints([
      { x: Math.round(clampedCX - half), y: Math.round(clampedCY - half) },
      { x: Math.round(clampedCX + half), y: Math.round(clampedCY - half) },
      { x: Math.round(clampedCX + half), y: Math.round(clampedCY + half) },
      { x: Math.round(clampedCX - half), y: Math.round(clampedCY + half) },
    ]);
    setMethod('manual');
  };

  const handleApply = async () => {
    // Transform points by inverse rotation
    const transformedPoints = points.map(p => {
      if (rotation === 0) return { x: p.x, y: p.y };

      const centerX = originalWidth / 2;
      const centerY = originalHeight / 2;
      const rad = (-rotation * Math.PI) / 180;
      const cos = Math.cos(rad);
      const sin = Math.sin(rad);

      const dx = p.x - centerX;
      const dy = p.y - centerY;
      return {
        x: Math.round(cos * dx - sin * dy + centerX),
        y: Math.round(sin * dx + cos * dy + centerY),
      };
    });

    await onApply({ points: transformedPoints, method, rotation });
  };

  // Zoom
  const handleZoomIn = () => setScale(s => Math.min(s * 1.2, 3));
  const handleZoomOut = () => setScale(s => Math.max(s / 1.2, 0.1));

  // Dimensions
  const getCropDimensions = () => {
    if (points.length !== 4) return { width: 0, height: 0 };
    const topW = Math.sqrt(Math.pow(points[1].x - points[0].x, 2) + Math.pow(points[1].y - points[0].y, 2));
    const bottomW = Math.sqrt(Math.pow(points[2].x - points[3].x, 2) + Math.pow(points[2].y - points[3].y, 2));
    const leftH = Math.sqrt(Math.pow(points[3].x - points[0].x, 2) + Math.pow(points[3].y - points[0].y, 2));
    const rightH = Math.sqrt(Math.pow(points[2].x - points[1].x, 2) + Math.pow(points[2].y - points[1].y, 2));
    return { width: Math.round((topW + bottomW) / 2), height: Math.round((leftH + rightH) / 2) };
  };

  const dims = getCropDimensions();

  return (
    <div className="flex h-full bg-slate-100">
      {/* Canvas area */}
      <div ref={containerRef} className="flex-1 overflow-auto flex items-center justify-center p-4">
        {!imageLoaded ? (
          <div className="flex flex-col items-center gap-3 text-slate-400">
            <Loader2 className="w-8 h-8 animate-spin" />
            <p>Loading image...</p>
          </div>
        ) : (
          <canvas
            ref={canvasRef}
            className="rounded-lg shadow-xl"
            style={{ cursor: cursorStyle }}
            onClick={handleCanvasClick}
            onMouseDown={handleMouseDown}
            onMouseMove={handleCanvasMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          />
        )}
      </div>

      {/* Right sidebar */}
      <div className="w-72 bg-white border-l border-slate-200 flex flex-col shrink-0">
        {/* Info */}
        <div className="p-4 border-b border-slate-200">
          <div className="text-sm text-slate-500 mb-1">Crop Size</div>
          <div className="text-lg font-semibold text-slate-800">
            {dims.width} × {dims.height} <span className="text-sm font-normal text-slate-400">px</span>
          </div>
          <div className="text-xs text-slate-400 mt-1">
            Original: {originalWidth} × {originalHeight}
          </div>
        </div>

        {/* Zoom */}
        <div className="p-4 border-b border-slate-200">
          <div className="flex items-center gap-2">
            <button onClick={handleZoomOut} className="p-2 rounded-lg bg-slate-100 hover:bg-slate-200">
              <ZoomOut className="w-4 h-4 text-slate-600" />
            </button>
            <span className="flex-1 text-center text-sm text-slate-600">{Math.round(scale * 100)}%</span>
            <button onClick={handleZoomIn} className="p-2 rounded-lg bg-slate-100 hover:bg-slate-200">
              <ZoomIn className="w-4 h-4 text-slate-600" />
            </button>
          </div>
        </div>

        {/* Crop Points */}
        <div className="p-4 border-b border-slate-200">
          <div className="text-sm font-medium text-slate-700 mb-2">Crop Points</div>
          <div className="grid grid-cols-4 gap-2">
            {pointLabels.map((label, i) => (
              <button
                key={i}
                onClick={() => setCurrentPointIndex(i)}
                title={label}
                className={`aspect-square rounded-lg text-sm font-bold transition-all ${
                  currentPointIndex === i
                    ? 'bg-teal-600 text-white ring-2 ring-teal-400'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {i + 1}
              </button>
            ))}
          </div>
          <div className="text-xs text-slate-500 mt-2 text-center">
            {pointLabels[currentPointIndex]}
          </div>

          <div className="mt-3 pt-3 border-t border-slate-100">
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={handleRectangularize}
                className="flex items-center justify-center gap-1.5 py-2 bg-slate-100 text-slate-600 rounded-lg hover:bg-slate-200 transition-colors text-sm"
              >
                <RectangleHorizontal className="w-4 h-4" />
                Straighten
              </button>
              <div className="flex items-center gap-1.5">
                <input
                  type="number"
                  value={squareSize}
                  onChange={(e) => setSquareSize(Math.max(256, Math.min(8192, parseInt(e.target.value) || 2048)))}
                  className="w-16 px-2 py-2 text-sm bg-slate-50 border border-slate-200 rounded-lg text-slate-700 text-center"
                  title="Square size in pixels"
                />
                <button
                  onClick={handleSquarify}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2 bg-slate-100 text-slate-600 rounded-lg hover:bg-slate-200 transition-colors text-sm"
                >
                  <Square className="w-4 h-4" />
                  Square
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Rotation */}
        <div className="p-4 border-b border-slate-200">
          <div className="text-sm font-medium text-slate-700 mb-2">Rotation</div>
          <div className="flex items-center gap-2 mb-3">
            <button
              onClick={() => setRotation(r => r - 90)}
              className="p-2 rounded-lg bg-slate-100 hover:bg-slate-200"
            >
              <RotateCcw className="w-4 h-4 text-slate-600" />
            </button>
            <input
              type="range"
              min="-180"
              max="180"
              step="0.5"
              value={rotation}
              onChange={(e) => setRotation(parseFloat(e.target.value))}
              className="flex-1 h-2 rounded-lg cursor-pointer accent-teal-600"
            />
            <button
              onClick={() => setRotation(r => r + 90)}
              className="p-2 rounded-lg bg-slate-100 hover:bg-slate-200"
            >
              <RotateCw className="w-4 h-4 text-slate-600" />
            </button>
          </div>
          <input
            type="number"
            min="-180"
            max="180"
            step="0.1"
            value={rotation.toFixed(1)}
            onChange={(e) => setRotation(parseFloat(e.target.value) || 0)}
            className="w-full px-3 py-2 text-sm bg-slate-50 border border-slate-200 rounded-lg text-slate-700 text-center"
          />
        </div>

        {/* Actions */}
        <div className="p-4 border-b border-slate-200 space-y-2">
          <button
            onClick={handleAutoDetect}
            disabled={detecting || isProcessing}
            className="w-full flex items-center justify-center gap-2 py-2.5 bg-violet-600 text-white rounded-lg hover:bg-violet-500 disabled:opacity-50 transition-colors"
          >
            {detecting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Wand2 className="w-4 h-4" />
            )}
            Auto Detect
          </button>
          <button
            onClick={handleReset}
            className="w-full flex items-center justify-center gap-2 py-2.5 bg-slate-100 text-slate-600 rounded-lg hover:bg-slate-200 transition-colors"
          >
            <RefreshCcw className="w-4 h-4" />
            Reset
          </button>
        </div>

        {/* Method indicator */}
        <div className="p-4 border-b border-slate-200">
          <div className="text-xs text-slate-500 mb-1">Method</div>
          <div className={`inline-block px-3 py-1 rounded-full text-sm ${
            method === 'auto' ? 'bg-violet-100 text-violet-700' : 'bg-teal-100 text-teal-700'
          }`}>
            {method === 'auto' ? 'Auto-detected' : 'Manual'}
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="p-4 border-b border-slate-200">
            <div className="p-3 bg-red-50 text-red-700 rounded-lg text-sm">
              {error}
            </div>
          </div>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Bottom actions */}
        <div className="p-4 border-t border-slate-200 space-y-2">
          <button
            onClick={handleApply}
            disabled={isProcessing || points.length !== 4}
            className="w-full flex items-center justify-center gap-2 py-3 bg-green-600 text-white rounded-lg hover:bg-green-500 disabled:opacity-50 font-medium transition-colors"
          >
            {isProcessing ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Check className="w-5 h-5" />
            )}
            Apply to All Images
          </button>
          <button
            onClick={onCancel}
            disabled={isProcessing}
            className="w-full py-2.5 bg-slate-100 text-slate-600 rounded-lg hover:bg-slate-200 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
