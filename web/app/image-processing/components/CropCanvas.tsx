'use client';

import { useCallback, useEffect } from 'react';
import { Loader2, ZoomIn, ZoomOut, Maximize, Check, AlertCircle, X } from 'lucide-react';
import type { CropState, CropActions, CropRefs, Point } from './useCropEditor';

interface CropCanvasProps {
  state: CropState;
  actions: CropActions;
  refs: CropRefs;
}

export default function CropCanvas({ state, actions, refs }: CropCanvasProps) {
  const {
    imageData, imageLoaded, loadError, loading,
    points, currentPointIndex, rotation, isDragging, isDraggingArea, dragStart,
    scale, cursorStyle, result, scaleRatio,
  } = state;

  const { canvasRef, containerRef, imageRef } = refs;

  // Convert original coords to display coords
  const toDisplayCoords = (p: Point): Point => ({
    x: (p.x / scaleRatio) * scale,
    y: (p.y / scaleRatio) * scale,
  });

  // Get original coords from mouse event
  const getOriginalCoords = (e: React.MouseEvent): Point => {
    const canvas = canvasRef.current;
    if (!canvas || !imageData) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.round(((e.clientX - rect.left) / scale) * scaleRatio),
      y: Math.round(((e.clientY - rect.top) / scale) * scaleRatio),
    };
  };

  // Point-in-polygon test
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

  // Draw canvas
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imageRef.current;
    if (!canvas || !img || !imageLoaded || !imageData) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const displayWidth = img.width * scale;
    const displayHeight = img.height * scale;

    canvas.width = displayWidth * dpr;
    canvas.height = displayHeight * dpr;
    canvas.style.width = `${displayWidth}px`;
    canvas.style.height = `${displayHeight}px`;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, displayWidth, displayHeight);

    // Draw image with rotation
    ctx.save();
    ctx.translate(displayWidth / 2, displayHeight / 2);
    ctx.rotate((rotation * Math.PI) / 180);
    ctx.translate(-displayWidth / 2, -displayHeight / 2);
    ctx.drawImage(img, 0, 0, displayWidth, displayHeight);
    ctx.restore();

    const toDisplay = (p: Point) => ({
      x: (p.x / scaleRatio) * scale,
      y: (p.y / scaleRatio) * scale,
    });

    if (points.length === 4) {
      const displayPoints = points.map(toDisplay);

      // Semi-transparent overlay outside crop
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, displayWidth, displayHeight);
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
  }, [points, rotation, scale, currentPointIndex, imageLoaded, imageData, scaleRatio, canvasRef, imageRef]);

  useEffect(() => {
    drawCanvas();
  }, [drawCanvas]);

  // Mouse handlers
  const handleCanvasClick = (e: React.MouseEvent) => {
    if (isDragging !== null || isDraggingArea || !imageData) return;

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
          actions.setCurrentPointIndex(i);
          return;
        }
      }
    }

    if (points.length === 4) {
      const coords = getOriginalCoords(e);
      if (!isPointInPolygon(coords.x, coords.y, points)) {
        const newPoints = [...points];
        newPoints[currentPointIndex] = coords;
        actions.setPoints(newPoints);
        actions.setCurrentPointIndex((currentPointIndex + 1) % 4);
        actions.setMethod('manual');
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

      for (let i = 0; i < points.length; i++) {
        const dp = toDisplayCoords(points[i]);
        if (Math.sqrt(Math.pow(dp.x - clickX, 2) + Math.pow(dp.y - clickY, 2)) < 20) {
          actions.setIsDragging(i);
          actions.setCurrentPointIndex(i);
          return;
        }
      }

      const coords = getOriginalCoords(e);
      if (points.length === 4 && isPointInPolygon(coords.x, coords.y, points)) {
        actions.setIsDraggingArea(true);
        actions.setDragStart(coords);
      }
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!imageData) return;
    const coords = getOriginalCoords(e);

    if (isDragging !== null) {
      const newPoints = [...points];
      newPoints[isDragging] = {
        x: Math.max(0, Math.min(imageData.width, coords.x)),
        y: Math.max(0, Math.min(imageData.height, coords.y)),
      };
      actions.setPoints(newPoints);
      actions.setMethod('manual');
      return;
    }

    if (isDraggingArea && dragStart) {
      const dx = coords.x - dragStart.x;
      const dy = coords.y - dragStart.y;
      const newPoints = points.map(p => ({ x: p.x + dx, y: p.y + dy }));
      const minX = Math.min(...newPoints.map(p => p.x));
      const maxX = Math.max(...newPoints.map(p => p.x));
      const minY = Math.min(...newPoints.map(p => p.y));
      const maxY = Math.max(...newPoints.map(p => p.y));
      if (minX >= 0 && maxX <= imageData.width && minY >= 0 && maxY <= imageData.height) {
        actions.setPoints(newPoints);
        actions.setDragStart(coords);
        actions.setMethod('manual');
      }
    }
  };

  const handleMouseUp = () => {
    actions.setIsDragging(null);
    actions.setIsDraggingArea(false);
    actions.setDragStart(null);
  };

  const handleMouseMoveForCursor = (e: React.MouseEvent) => {
    if (!imageData || points.length !== 4) return;
    const canvas = canvasRef.current;
    if (canvas) {
      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      for (let i = 0; i < points.length; i++) {
        const dp = toDisplayCoords(points[i]);
        if (Math.sqrt(Math.pow(dp.x - mouseX, 2) + Math.pow(dp.y - mouseY, 2)) < 20) {
          actions.setCursorStyle('grab');
          return;
        }
      }

      const coords = getOriginalCoords(e);
      if (isPointInPolygon(coords.x, coords.y, points)) {
        actions.setCursorStyle('move');
      } else {
        actions.setCursorStyle('crosshair');
      }
    }
  };

  const handleCanvasMouseMove = (e: React.MouseEvent) => {
    handleMouseMove(e);
    if (isDragging !== null) {
      actions.setCursorStyle('grabbing');
    } else if (isDraggingArea) {
      actions.setCursorStyle('move');
    } else {
      handleMouseMoveForCursor(e);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col h-full items-center justify-center bg-slate-950">
        <Loader2 className="w-8 h-8 animate-spin text-teal-500" />
        <p className="text-slate-400 text-sm mt-2">Loading image...</p>
      </div>
    );
  }

  if (loadError || !imageData) {
    return (
      <div className="flex flex-col h-full items-center justify-center bg-slate-950">
        <AlertCircle className="w-12 h-12 text-red-500 mb-4" />
        <p className="text-white mb-2">{loadError || 'Failed to load batch'}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar — matches ImagePreview style */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800 shrink-0">
        <span className="text-xs text-slate-400">
          Crop Editor — {imageData.filename}
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={actions.handleZoomOut}
            className="p-1 text-slate-400 hover:text-slate-200 rounded hover:bg-slate-800"
            title="Zoom Out"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <span className="text-xs text-slate-500 w-10 text-center font-mono">
            {Math.round(scale * 100)}%
          </span>
          <button
            onClick={actions.handleZoomIn}
            className="p-1 text-slate-400 hover:text-slate-200 rounded hover:bg-slate-800"
            title="Zoom In"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={actions.handleFit}
            className="p-1 text-slate-400 hover:text-slate-200 rounded hover:bg-slate-800"
            title="Fit"
          >
            <Maximize className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Canvas area */}
      <div ref={containerRef} className="flex-1 overflow-auto bg-slate-950 flex items-center justify-center p-4">
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

      {/* Result toast */}
      {result && (
        <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 px-6 py-4 rounded-xl shadow-lg flex items-center gap-3 z-50 ${
          result.success ? 'bg-green-600 text-white' : 'bg-red-600 text-white'
        }`}>
          {result.success ? <Check className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
          <span>{result.message}</span>
          <button onClick={() => actions.setResult(null)} className="ml-2 hover:opacity-80">
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
