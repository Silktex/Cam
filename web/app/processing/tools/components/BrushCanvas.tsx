'use client';

import { Stage, Layer, Image as KonvaImage, Line } from 'react-konva';
import { useState, useRef, useEffect, useCallback } from 'react';
import Konva from 'konva';

interface BrushCanvasProps {
  imageUrl: string;
  imageWidth: number;
  imageHeight: number;
  brushRadius: number;
  brushColor?: string;
  containerWidth: number;
  containerHeight: number;
  onMaskChange?: (maskDataUrl: string) => void;
  mode?: 'paint' | 'erase';
}

export default function BrushCanvas({
  imageUrl,
  imageWidth,
  imageHeight,
  brushRadius,
  brushColor = 'rgba(239, 68, 68, 0.5)',
  containerWidth,
  containerHeight,
  onMaskChange,
  mode = 'paint',
}: BrushCanvasProps) {
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const stageRef = useRef<Konva.Stage>(null);
  const isDrawing = useRef(false);
  const [lines, setLines] = useState<{ points: number[]; strokeWidth: number }[]>([]);
  const [undoStack, setUndoStack] = useState<{ points: number[]; strokeWidth: number }[][]>([]);

  const scaleX = (containerWidth - 32) / imageWidth;
  const scaleY = (containerHeight - 32) / imageHeight;
  const displayScale = Math.min(scaleX, scaleY, 1);
  const displayWidth = imageWidth * displayScale;
  const displayHeight = imageHeight * displayScale;
  const ox = (containerWidth - displayWidth) / 2;
  const oy = (containerHeight - displayHeight) / 2;

  useEffect(() => {
    const img = new window.Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => setImage(img);
    img.src = imageUrl;
  }, [imageUrl]);

  const handleMouseDown = useCallback(() => {
    isDrawing.current = true;
    const stage = stageRef.current;
    if (!stage) return;
    const pos = stage.getPointerPosition();
    if (!pos) return;
    setLines((prev) => [...prev, { points: [pos.x, pos.y], strokeWidth: brushRadius * 2 * displayScale }]);
  }, [brushRadius, displayScale]);

  const handleMouseMove = useCallback(() => {
    if (!isDrawing.current) return;
    const stage = stageRef.current;
    if (!stage) return;
    const pos = stage.getPointerPosition();
    if (!pos) return;
    setLines((prev) => {
      const updated = [...prev];
      const last = updated[updated.length - 1];
      if (last) {
        last.points = [...last.points, pos.x, pos.y];
      }
      return updated;
    });
  }, []);

  const handleMouseUp = useCallback(() => {
    isDrawing.current = false;
    // Generate mask data
    if (onMaskChange) {
      const maskCanvas = document.createElement('canvas');
      maskCanvas.width = imageWidth;
      maskCanvas.height = imageHeight;
      const ctx = maskCanvas.getContext('2d');
      if (ctx) {
        ctx.fillStyle = 'black';
        ctx.fillRect(0, 0, imageWidth, imageHeight);
        ctx.strokeStyle = 'white';
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        lines.forEach((line) => {
          ctx.lineWidth = line.strokeWidth / displayScale;
          ctx.beginPath();
          for (let i = 0; i < line.points.length; i += 2) {
            const x = (line.points[i] - ox) / displayScale;
            const y = (line.points[i + 1] - oy) / displayScale;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          }
          ctx.stroke();
        });
        onMaskChange(maskCanvas.toDataURL('image/png'));
      }
    }
  }, [lines, imageWidth, imageHeight, displayScale, ox, oy, onMaskChange]);

  const undo = useCallback(() => {
    setLines((prev) => {
      if (prev.length === 0) return prev;
      setUndoStack((stack) => [...stack, prev]);
      return prev.slice(0, -1);
    });
  }, []);

  const redo = useCallback(() => {
    setUndoStack((stack) => {
      if (stack.length === 0) return stack;
      const last = stack[stack.length - 1];
      setLines(last);
      return stack.slice(0, -1);
    });
  }, []);

  const clear = useCallback(() => {
    setUndoStack((stack) => [...stack, lines]);
    setLines([]);
  }, [lines]);

  return (
    <div className="relative">
      <Stage
        ref={stageRef}
        width={containerWidth}
        height={containerHeight}
        className="bg-slate-950 rounded-xl cursor-crosshair"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onTouchStart={handleMouseDown}
        onTouchMove={handleMouseMove}
        onTouchEnd={handleMouseUp}
      >
        <Layer>
          {image && (
            <KonvaImage
              image={image}
              x={ox}
              y={oy}
              width={displayWidth}
              height={displayHeight}
            />
          )}
          {lines.map((line, i) => (
            <Line
              key={i}
              points={line.points}
              stroke={mode === 'erase' ? 'rgba(0,0,0,0.8)' : brushColor}
              strokeWidth={line.strokeWidth}
              lineCap="round"
              lineJoin="round"
              globalCompositeOperation={mode === 'erase' ? 'destination-out' : 'source-over'}
            />
          ))}
        </Layer>
      </Stage>

      {/* Undo/Redo/Clear controls */}
      <div className="absolute bottom-3 left-3 flex gap-2">
        <button
          onClick={undo}
          disabled={lines.length === 0}
          className="px-2.5 py-1 bg-slate-800/90 text-xs text-slate-300 rounded-lg
            hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Undo
        </button>
        <button
          onClick={redo}
          disabled={undoStack.length === 0}
          className="px-2.5 py-1 bg-slate-800/90 text-xs text-slate-300 rounded-lg
            hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Redo
        </button>
        <button
          onClick={clear}
          disabled={lines.length === 0}
          className="px-2.5 py-1 bg-red-900/50 text-xs text-red-300 rounded-lg
            hover:bg-red-900/70 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Clear
        </button>
      </div>
    </div>
  );
}
