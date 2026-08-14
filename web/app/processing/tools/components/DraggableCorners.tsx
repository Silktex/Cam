'use client';

import { Stage, Layer, Circle, Line, Text, Image as KonvaImage } from 'react-konva';
import { useState, useRef, useEffect, useCallback } from 'react';
import Konva from 'konva';

export interface Point {
  x: number;
  y: number;
}

interface DraggableCornersProps {
  imageUrl: string;
  imageWidth: number;
  imageHeight: number;
  points: Point[];
  onPointsChange: (points: Point[]) => void;
  containerWidth: number;
  containerHeight: number;
  showGrid?: boolean;
  labels?: string[];
}

export default function DraggableCorners({
  imageUrl,
  imageWidth,
  imageHeight,
  points,
  onPointsChange,
  containerWidth,
  containerHeight,
  showGrid = true,
  labels = ['TL', 'TR', 'BR', 'BL'],
}: DraggableCornersProps) {
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const stageRef = useRef<Konva.Stage>(null);

  // Calculate display scale
  const scaleX = (containerWidth - 32) / imageWidth;
  const scaleY = (containerHeight - 32) / imageHeight;
  const displayScale = Math.min(scaleX, scaleY, 1);

  const displayWidth = imageWidth * displayScale;
  const displayHeight = imageHeight * displayScale;
  const offsetX = (containerWidth - displayWidth) / 2;
  const offsetY = (containerHeight - displayHeight) / 2;

  // Load image
  useEffect(() => {
    const img = new window.Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => setImage(img);
    img.src = imageUrl;
  }, [imageUrl]);

  // Convert between image coords and display coords
  const toDisplay = useCallback((p: Point) => ({
    x: p.x * displayScale + offsetX,
    y: p.y * displayScale + offsetY,
  }), [displayScale, offsetX, offsetY]);

  const toImage = useCallback((x: number, y: number) => ({
    x: Math.round((x - offsetX) / displayScale),
    y: Math.round((y - offsetY) / displayScale),
  }), [displayScale, offsetX, offsetY]);

  const handleDrag = useCallback((index: number, e: Konva.KonvaEventObject<DragEvent>) => {
    const node = e.target;
    const imgPoint = toImage(node.x(), node.y());
    // Clamp to image bounds
    imgPoint.x = Math.max(0, Math.min(imageWidth, imgPoint.x));
    imgPoint.y = Math.max(0, Math.min(imageHeight, imgPoint.y));

    const newPoints = [...points];
    newPoints[index] = imgPoint;
    onPointsChange(newPoints);
  }, [points, onPointsChange, toImage, imageWidth, imageHeight]);

  const displayPoints = points.map(toDisplay);

  // Quadrilateral outline
  const flatLinePoints = displayPoints.flatMap((p) => [p.x, p.y]);

  // Grid lines within the quadrilateral
  const gridLines = [];
  if (showGrid && displayPoints.length === 4) {
    const gridCount = 4;
    for (let i = 1; i < gridCount; i++) {
      const t = i / gridCount;
      // Horizontal
      const hLeft = {
        x: displayPoints[0].x + (displayPoints[3].x - displayPoints[0].x) * t,
        y: displayPoints[0].y + (displayPoints[3].y - displayPoints[0].y) * t,
      };
      const hRight = {
        x: displayPoints[1].x + (displayPoints[2].x - displayPoints[1].x) * t,
        y: displayPoints[1].y + (displayPoints[2].y - displayPoints[1].y) * t,
      };
      gridLines.push([hLeft.x, hLeft.y, hRight.x, hRight.y]);
      // Vertical
      const vTop = {
        x: displayPoints[0].x + (displayPoints[1].x - displayPoints[0].x) * t,
        y: displayPoints[0].y + (displayPoints[1].y - displayPoints[0].y) * t,
      };
      const vBottom = {
        x: displayPoints[3].x + (displayPoints[2].x - displayPoints[3].x) * t,
        y: displayPoints[3].y + (displayPoints[2].y - displayPoints[3].y) * t,
      };
      gridLines.push([vTop.x, vTop.y, vBottom.x, vBottom.y]);
    }
  }

  return (
    <Stage
      ref={stageRef}
      width={containerWidth}
      height={containerHeight}
      className="bg-slate-950 rounded-xl"
    >
      <Layer>
        {/* Background image */}
        {image && (
          <KonvaImage
            image={image}
            x={offsetX}
            y={offsetY}
            width={displayWidth}
            height={displayHeight}
          />
        )}

        {/* Dark overlay outside selection */}
        {displayPoints.length === 4 && (
          <>
            {/* Outline */}
            <Line
              points={[...flatLinePoints, displayPoints[0].x, displayPoints[0].y]}
              stroke="#14B8A6"
              strokeWidth={2}
              closed
            />

            {/* Grid */}
            {gridLines.map((line, i) => (
              <Line
                key={`grid-${i}`}
                points={line}
                stroke="rgba(20, 184, 166, 0.25)"
                strokeWidth={1}
                dash={[4, 4]}
              />
            ))}
          </>
        )}

        {/* Corner handles */}
        {displayPoints.map((dp, i) => (
          <Circle
            key={i}
            x={dp.x}
            y={dp.y}
            radius={8}
            fill="#14B8A6"
            stroke="white"
            strokeWidth={2}
            draggable
            onDragMove={(e) => handleDrag(i, e)}
            onMouseEnter={(e) => {
              const container = e.target.getStage()?.container();
              if (container) container.style.cursor = 'grab';
            }}
            onMouseLeave={(e) => {
              const container = e.target.getStage()?.container();
              if (container) container.style.cursor = 'default';
            }}
          />
        ))}

        {/* Corner labels */}
        {displayPoints.map((dp, i) => (
          <Text
            key={`label-${i}`}
            x={dp.x + 12}
            y={dp.y - 8}
            text={`${labels[i]} (${points[i]?.x || 0}, ${points[i]?.y || 0})`}
            fontSize={11}
            fill="rgba(148, 163, 184, 0.8)"
            fontFamily="monospace"
          />
        ))}
      </Layer>
    </Stage>
  );
}
