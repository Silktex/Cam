'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft, RotateCcw, RotateCw, Check, X, Wand2, Loader2,
  RefreshCcw, ZoomIn, ZoomOut, Maximize, AlertCircle,
  RectangleHorizontal, Square
} from 'lucide-react';
import {
  getTopImageForCrop, autoDetectCrop, applyCrop, getFullUrl
} from '@/lib/api';

interface Point {
  x: number;
  y: number;
}

export default function CropPage() {
  const params = useParams();
  const router = useRouter();
  const batchName = params.batchName as string;

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  // Image state
  const [imageData, setImageData] = useState<{
    width: number;
    height: number;
    preview_width: number;
    preview_height: number;
    preview_url: string;
    filename: string;
  } | null>(null);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Crop state
  const [points, setPoints] = useState<Point[]>([]);
  const [currentPointIndex, setCurrentPointIndex] = useState(0);
  const [rotation, setRotation] = useState(0);
  const [isDragging, setIsDragging] = useState<number | null>(null);
  const [isDraggingArea, setIsDraggingArea] = useState(false);
  const [dragStart, setDragStart] = useState<Point | null>(null);
  const [scale, setScale] = useState(1);
  const [method, setMethod] = useState<'manual' | 'auto'>('manual');

  // Processing state
  const [processing, setProcessing] = useState<string | null>(null);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  // Coordinate mapping: preview coords <-> original coords
  const scaleRatio = imageData ? imageData.width / imageData.preview_width : 1;

  // Point labels
  const pointLabels = ['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left'];

  // Load batch data
  useEffect(() => {
    const loadData = async () => {
      try {
        const res = await getTopImageForCrop(batchName);
        setImageData(res.data);
      } catch (err: any) {
        setLoadError(err.response?.data?.detail || 'Failed to load batch');
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [batchName]);

  // Load image
  useEffect(() => {
    if (!imageData) return;

    setImageLoaded(false);
    setLoadError(null);

    const img = new Image();
    img.onload = () => {
      imageRef.current = img;

      // Calculate scale to fit in viewport (leaving space for sidebar)
      if (containerRef.current) {
        const containerWidth = containerRef.current.clientWidth - 32;
        const containerHeight = containerRef.current.clientHeight - 32;
        const scaleX = containerWidth / img.width;
        const scaleY = containerHeight / img.height;
        setScale(Math.min(scaleX, scaleY, 1));
      }

      // Initialize points at 15% inset (in original image coordinates)
      const margin = 0.15;
      setPoints([
        { x: imageData.width * margin, y: imageData.height * margin },
        { x: imageData.width * (1 - margin), y: imageData.height * margin },
        { x: imageData.width * (1 - margin), y: imageData.height * (1 - margin) },
        { x: imageData.width * margin, y: imageData.height * (1 - margin) },
      ]);

      setImageLoaded(true);
    };

    img.onerror = () => {
      setLoadError('Failed to load preview image');
    };

    img.src = getFullUrl(imageData.preview_url);
  }, [imageData]);

  // Draw canvas
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imageRef.current;
    if (!canvas || !img || !imageLoaded || !imageData) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const displayWidth = img.width * scale;
    const displayHeight = img.height * scale;
    canvas.width = displayWidth;
    canvas.height = displayHeight;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw image with rotation preview (crop overlay stays fixed)
    ctx.save();
    ctx.translate(displayWidth / 2, displayHeight / 2);
    ctx.rotate((rotation * Math.PI) / 180);
    ctx.translate(-displayWidth / 2, -displayHeight / 2);
    ctx.drawImage(img, 0, 0, displayWidth, displayHeight);
    ctx.restore();

    // Convert original coords to display coords
    const toDisplay = (p: Point) => ({
      x: (p.x / scaleRatio) * scale,
      y: (p.y / scaleRatio) * scale,
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
  }, [points, rotation, scale, currentPointIndex, imageLoaded, imageData, scaleRatio]);

  useEffect(() => {
    drawCanvas();
  }, [drawCanvas]);

  // Mouse handlers
  const getOriginalCoords = (e: React.MouseEvent): Point => {
    const canvas = canvasRef.current;
    if (!canvas || !imageData) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.round(((e.clientX - rect.left) / scale) * scaleRatio),
      y: Math.round(((e.clientY - rect.top) / scale) * scaleRatio),
    };
  };

  // Convert original coords to display coords (simple scaling, no rotation)
  const toDisplayCoords = (p: Point): Point => ({
    x: (p.x / scaleRatio) * scale,
    y: (p.y / scaleRatio) * scale,
  });

  // Check if point is inside the crop polygon
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
    if (isDragging !== null || isDraggingArea || !imageData) return;

    const canvas = canvasRef.current;
    if (canvas) {
      const rect = canvas.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const clickY = e.clientY - rect.top;

      // Check if clicking on a corner point
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

    // If clicking outside corners and outside crop area, set new point
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
    if (!imageData) return;

    const canvas = canvasRef.current;
    if (canvas) {
      const rect = canvas.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const clickY = e.clientY - rect.top;

      // Check if clicking on a corner point first
      for (let i = 0; i < points.length; i++) {
        const dp = toDisplayCoords(points[i]);
        if (Math.sqrt(Math.pow(dp.x - clickX, 2) + Math.pow(dp.y - clickY, 2)) < 20) {
          setIsDragging(i);
          setCurrentPointIndex(i);
          return;
        }
      }

      // Check if clicking inside the crop area to drag the whole thing
      const coords = getOriginalCoords(e);
      if (points.length === 4 && isPointInPolygon(coords.x, coords.y, points)) {
        setIsDraggingArea(true);
        setDragStart(coords);
      }
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!imageData) return;

    const coords = getOriginalCoords(e);

    // Dragging a corner point
    if (isDragging !== null) {
      const newPoints = [...points];
      newPoints[isDragging] = {
        x: Math.max(0, Math.min(imageData.width, coords.x)),
        y: Math.max(0, Math.min(imageData.height, coords.y)),
      };
      setPoints(newPoints);
      setMethod('manual');
      return;
    }

    // Dragging the entire area
    if (isDraggingArea && dragStart) {
      const dx = coords.x - dragStart.x;
      const dy = coords.y - dragStart.y;

      // Calculate new positions
      const newPoints = points.map(p => ({
        x: p.x + dx,
        y: p.y + dy,
      }));

      // Check bounds - ensure all points stay within image
      const minX = Math.min(...newPoints.map(p => p.x));
      const maxX = Math.max(...newPoints.map(p => p.x));
      const minY = Math.min(...newPoints.map(p => p.y));
      const maxY = Math.max(...newPoints.map(p => p.y));

      if (minX >= 0 && maxX <= imageData.width && minY >= 0 && maxY <= imageData.height) {
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

  // Get cursor style based on mouse position
  const [cursorStyle, setCursorStyle] = useState('crosshair');

  const handleMouseMoveForCursor = (e: React.MouseEvent) => {
    if (!imageData || points.length !== 4) return;

    const canvas = canvasRef.current;
    if (canvas) {
      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      // Check if over a corner point
      for (let i = 0; i < points.length; i++) {
        const dp = toDisplayCoords(points[i]);
        if (Math.sqrt(Math.pow(dp.x - mouseX, 2) + Math.pow(dp.y - mouseY, 2)) < 20) {
          setCursorStyle('grab');
          return;
        }
      }

      // Check if inside crop area
      const coords = getOriginalCoords(e);
      if (isPointInPolygon(coords.x, coords.y, points)) {
        setCursorStyle('move');
      } else {
        setCursorStyle('crosshair');
      }
    }
  };

  const handleCanvasMouseMove = (e: React.MouseEvent) => {
    handleMouseMove(e);
    if (isDragging !== null) {
      setCursorStyle('grabbing');
    } else if (isDraggingArea) {
      setCursorStyle('move');
    } else {
      handleMouseMoveForCursor(e);
    }
  };

  // Actions
  const handleAutoDetect = async () => {
    setProcessing('auto');
    try {
      const res = await autoDetectCrop(batchName);
      if (res.data.success && res.data.bbox) {
        const [x1, y1, x2, y2] = res.data.bbox;
        setPoints([
          { x: x1, y: y1 },
          { x: x2, y: y1 },
          { x: x2, y: y2 },
          { x: x1, y: y2 },
        ]);
        setMethod('auto');
      } else {
        setResult({ success: false, message: res.data.error || 'Auto-detect failed' });
      }
    } catch (err: any) {
      setResult({ success: false, message: err.message || 'Auto-detect failed' });
    } finally {
      setProcessing(null);
    }
  };

  const handleReset = () => {
    if (!imageData) return;
    const margin = 0.15;
    setPoints([
      { x: imageData.width * margin, y: imageData.height * margin },
      { x: imageData.width * (1 - margin), y: imageData.height * margin },
      { x: imageData.width * (1 - margin), y: imageData.height * (1 - margin) },
      { x: imageData.width * margin, y: imageData.height * (1 - margin) },
    ]);
    setRotation(0);
    setCurrentPointIndex(0);
    setMethod('manual');
  };

  // Make angles 90° (rectangularize) - keeps center and average dimensions
  const handleRectangularize = () => {
    if (points.length !== 4) return;

    // Calculate center of current quadrilateral
    const centerX = points.reduce((sum, p) => sum + p.x, 0) / 4;
    const centerY = points.reduce((sum, p) => sum + p.y, 0) / 4;

    // Calculate average width and height from current shape
    const topWidth = Math.sqrt(Math.pow(points[1].x - points[0].x, 2) + Math.pow(points[1].y - points[0].y, 2));
    const bottomWidth = Math.sqrt(Math.pow(points[2].x - points[3].x, 2) + Math.pow(points[2].y - points[3].y, 2));
    const leftHeight = Math.sqrt(Math.pow(points[3].x - points[0].x, 2) + Math.pow(points[3].y - points[0].y, 2));
    const rightHeight = Math.sqrt(Math.pow(points[2].x - points[1].x, 2) + Math.pow(points[2].y - points[1].y, 2));

    const avgWidth = (topWidth + bottomWidth) / 2;
    const avgHeight = (leftHeight + rightHeight) / 2;

    // Create rectangle centered at the same position
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

  // Make square - uses average of width and height
  const handleSquarify = () => {
    if (points.length !== 4) return;

    // Calculate center
    const centerX = points.reduce((sum, p) => sum + p.x, 0) / 4;
    const centerY = points.reduce((sum, p) => sum + p.y, 0) / 4;

    // Calculate current dimensions
    const topWidth = Math.sqrt(Math.pow(points[1].x - points[0].x, 2) + Math.pow(points[1].y - points[0].y, 2));
    const bottomWidth = Math.sqrt(Math.pow(points[2].x - points[3].x, 2) + Math.pow(points[2].y - points[3].y, 2));
    const leftHeight = Math.sqrt(Math.pow(points[3].x - points[0].x, 2) + Math.pow(points[3].y - points[0].y, 2));
    const rightHeight = Math.sqrt(Math.pow(points[2].x - points[1].x, 2) + Math.pow(points[2].y - points[1].y, 2));

    const avgWidth = (topWidth + bottomWidth) / 2;
    const avgHeight = (leftHeight + rightHeight) / 2;

    // Use average of width and height for square size
    const size = (avgWidth + avgHeight) / 2;
    const half = size / 2;

    setPoints([
      { x: Math.round(centerX - half), y: Math.round(centerY - half) },
      { x: Math.round(centerX + half), y: Math.round(centerY - half) },
      { x: Math.round(centerX + half), y: Math.round(centerY + half) },
      { x: Math.round(centerX - half), y: Math.round(centerY + half) },
    ]);
    setMethod('manual');
  };

  const handleApply = async () => {
    if (!imageData) return;
    setProcessing('apply');
    try {
      // Transform points by inverse rotation to get coordinates in original image space
      // The UI shows rotated image with fixed overlay, so we need to "unrotate" the points
      const transformedPoints = points.map(p => {
        if (rotation === 0) return { x: p.x, y: p.y };

        const centerX = imageData.width / 2;
        const centerY = imageData.height / 2;
        const rad = (-rotation * Math.PI) / 180; // Inverse rotation
        const cos = Math.cos(rad);
        const sin = Math.sin(rad);

        const dx = p.x - centerX;
        const dy = p.y - centerY;
        return {
          x: Math.round(cos * dx - sin * dy + centerX),
          y: Math.round(sin * dx + cos * dy + centerY),
        };
      });

      const res = await applyCrop(batchName, method, {
        points: transformedPoints,
        rotation,
      });
      if (res.data.success) {
        setResult({
          success: true,
          message: `Cropped ${res.data.processed}/${res.data.total} images`,
        });
        setTimeout(() => router.push('/processing'), 1500);
      } else {
        setResult({ success: false, message: 'Crop failed' });
      }
    } catch (err: any) {
      setResult({ success: false, message: err.response?.data?.detail || 'Crop failed' });
    } finally {
      setProcessing(null);
    }
  };

  // Zoom
  const handleZoomIn = () => setScale(s => Math.min(s * 1.2, 3));
  const handleZoomOut = () => setScale(s => Math.max(s / 1.2, 0.1));
  const handleFit = () => {
    if (containerRef.current && imageRef.current) {
      const cw = containerRef.current.clientWidth - 32;
      const ch = containerRef.current.clientHeight - 32;
      setScale(Math.min(cw / imageRef.current.width, ch / imageRef.current.height, 1));
    }
  };

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

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-teal-500" />
      </div>
    );
  }

  if (loadError || !imageData) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <p className="text-white mb-4">{loadError || 'Failed to load batch'}</p>
          <Link href="/processing" className="text-teal-400 hover:text-teal-300">
            Back to Processing
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 flex">
      {/* Main canvas area */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <header className="bg-slate-800 border-b border-slate-700 px-4 py-3 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-4">
            <Link
              href="/processing"
              className="p-2 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors"
            >
              <ArrowLeft className="w-5 h-5 text-slate-300" />
            </Link>
            <div>
              <h1 className="text-lg font-semibold text-white">Crop: {batchName}</h1>
              <p className="text-sm text-slate-400">{imageData.filename}</p>
            </div>
          </div>

          {/* Zoom controls */}
          <div className="flex items-center gap-2">
            <button onClick={handleZoomOut} className="p-2 rounded-lg bg-slate-700 hover:bg-slate-600">
              <ZoomOut className="w-4 h-4 text-slate-300" />
            </button>
            <span className="text-sm text-slate-400 w-14 text-center">{Math.round(scale * 100)}%</span>
            <button onClick={handleZoomIn} className="p-2 rounded-lg bg-slate-700 hover:bg-slate-600">
              <ZoomIn className="w-4 h-4 text-slate-300" />
            </button>
            <button onClick={handleFit} className="p-2 rounded-lg bg-slate-700 hover:bg-slate-600" title="Fit">
              <Maximize className="w-4 h-4 text-slate-300" />
            </button>
          </div>
        </header>

        {/* Canvas */}
        <div ref={containerRef} className="flex-1 overflow-auto flex items-center justify-center p-4">
          {!imageLoaded ? (
            <div className="flex flex-col items-center gap-3 text-slate-400">
              <Loader2 className="w-8 h-8 animate-spin" />
              <p>Loading image...</p>
            </div>
          ) : (
            <canvas
              ref={canvasRef}
              className="rounded-lg shadow-2xl"
              style={{ cursor: cursorStyle }}
              onClick={handleCanvasClick}
              onMouseDown={handleMouseDown}
              onMouseMove={handleCanvasMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
            />
          )}
        </div>
      </div>

      {/* Right sidebar - all controls */}
      <div className="w-80 bg-slate-800 border-l border-slate-700 flex flex-col shrink-0">
        {/* Info */}
        <div className="p-4 border-b border-slate-700">
          <div className="text-sm text-slate-400 mb-1">Crop Size</div>
          <div className="text-xl font-semibold text-white">{dims.width} × {dims.height} <span className="text-sm font-normal text-slate-500">px</span></div>
          <div className="text-xs text-slate-500 mt-1">Original: {imageData.width} × {imageData.height}</div>
        </div>

        {/* Crop Points */}
        <div className="p-4 border-b border-slate-700">
          <div className="text-sm font-medium text-slate-300 mb-3">Crop Points</div>
          <div className="text-xs text-slate-500 mb-3">Click on image or select point below</div>
          <div className="grid grid-cols-4 gap-2">
            {pointLabels.map((label, i) => (
              <button
                key={i}
                onClick={() => setCurrentPointIndex(i)}
                title={label}
                className={`aspect-square rounded-lg text-sm font-bold transition-all ${
                  currentPointIndex === i
                    ? 'bg-teal-600 text-white ring-2 ring-teal-400'
                    : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                }`}
              >
                {i + 1}
              </button>
            ))}
          </div>
          <div className="text-xs text-slate-500 mt-2 text-center">
            {pointLabels[currentPointIndex]}
          </div>

          {/* Shape correction buttons */}
          <div className="mt-4 pt-3 border-t border-slate-600">
            <div className="text-xs text-slate-500 mb-2">Correct Shape</div>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={handleRectangularize}
                className="flex items-center justify-center gap-1.5 py-2 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors text-sm"
                title="Make all corners 90 degrees"
              >
                <RectangleHorizontal className="w-4 h-4" />
                Straighten
              </button>
              <button
                onClick={handleSquarify}
                className="flex items-center justify-center gap-1.5 py-2 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors text-sm"
                title="Make equal width and height"
              >
                <Square className="w-4 h-4" />
                Make Square
              </button>
            </div>
          </div>
        </div>

        {/* Rotation */}
        <div className="p-4 border-b border-slate-700">
          <div className="text-sm font-medium text-slate-300 mb-3">Rotation</div>

          {/* Quick rotate buttons */}
          <div className="flex items-center gap-2 mb-4">
            <button
              onClick={() => setRotation(r => r - 90)}
              className="flex-1 flex items-center justify-center gap-1 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors"
            >
              <RotateCcw className="w-4 h-4 text-slate-300" />
              <span className="text-sm text-slate-300">-90°</span>
            </button>
            <button
              onClick={() => setRotation(0)}
              className="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm text-slate-300 transition-colors"
            >
              0°
            </button>
            <button
              onClick={() => setRotation(r => r + 90)}
              className="flex-1 flex items-center justify-center gap-1 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors"
            >
              <RotateCw className="w-4 h-4 text-slate-300" />
              <span className="text-sm text-slate-300">+90°</span>
            </button>
          </div>

          {/* Slider */}
          <div className="mb-2">
            <input
              type="range"
              min="-180"
              max="180"
              step="0.5"
              value={rotation}
              onChange={(e) => setRotation(parseFloat(e.target.value))}
              className="w-full h-2 rounded-lg cursor-pointer"
              style={{
                background: `linear-gradient(to right, #14b8a6 0%, #14b8a6 ${((rotation + 180) / 360) * 100}%, #334155 ${((rotation + 180) / 360) * 100}%, #334155 100%)`,
              }}
            />
          </div>

          {/* Number input */}
          <div className="flex items-center gap-2">
            <input
              type="number"
              min="-180"
              max="180"
              step="0.1"
              value={rotation.toFixed(1)}
              onChange={(e) => setRotation(parseFloat(e.target.value) || 0)}
              className="flex-1 px-3 py-2 text-sm bg-slate-700 border border-slate-600 rounded-lg text-white text-center"
            />
            <span className="text-slate-500">°</span>
          </div>
        </div>

        {/* Actions */}
        <div className="p-4 border-b border-slate-700">
          <div className="text-sm font-medium text-slate-300 mb-3">Actions</div>
          <div className="space-y-2">
            <button
              onClick={handleAutoDetect}
              disabled={processing !== null}
              className="w-full flex items-center justify-center gap-2 py-2.5 bg-violet-600 text-white rounded-lg hover:bg-violet-500 disabled:opacity-50 transition-colors"
            >
              {processing === 'auto' ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Wand2 className="w-4 h-4" />
              )}
              Auto Detect
            </button>
            <button
              onClick={handleReset}
              className="w-full flex items-center justify-center gap-2 py-2.5 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors"
            >
              <RefreshCcw className="w-4 h-4" />
              Reset
            </button>
          </div>
        </div>

        {/* Method indicator */}
        <div className="p-4 border-b border-slate-700">
          <div className="text-xs text-slate-500 mb-1">Method</div>
          <div className={`inline-block px-3 py-1 rounded-full text-sm ${
            method === 'auto' ? 'bg-violet-600 text-white' : 'bg-teal-600 text-white'
          }`}>
            {method === 'auto' ? 'Auto-detected' : 'Manual'}
          </div>
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Bottom actions */}
        <div className="p-4 border-t border-slate-700 space-y-2">
          <button
            onClick={handleApply}
            disabled={processing !== null || points.length !== 4}
            className="w-full flex items-center justify-center gap-2 py-3 bg-green-600 text-white rounded-lg hover:bg-green-500 disabled:opacity-50 font-medium transition-colors"
          >
            {processing === 'apply' ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Check className="w-5 h-5" />
            )}
            Apply to All Images
          </button>
          <button
            onClick={() => router.push('/processing')}
            className="w-full py-2.5 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>

      {/* Result toast */}
      {result && (
        <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 px-6 py-4 rounded-xl shadow-lg flex items-center gap-3 ${
          result.success ? 'bg-green-600 text-white' : 'bg-red-600 text-white'
        }`}>
          {result.success ? <Check className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
          <span>{result.message}</span>
          <button onClick={() => setResult(null)} className="ml-2 hover:opacity-80">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Custom slider styles */}
      <style jsx>{`
        input[type="range"] {
          -webkit-appearance: none;
          appearance: none;
        }
        input[type="range"]::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: 16px;
          height: 16px;
          border-radius: 50%;
          background: #14b8a6;
          cursor: pointer;
          border: 2px solid #0d7377;
        }
        input[type="range"]::-moz-range-thumb {
          width: 16px;
          height: 16px;
          border-radius: 50%;
          background: #14b8a6;
          cursor: pointer;
          border: 2px solid #0d7377;
        }
      `}</style>
    </div>
  );
}
