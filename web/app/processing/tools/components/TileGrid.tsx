'use client';

import { Stage, Layer, Image as KonvaImage, Line } from 'react-konva';
import { useState, useEffect, useMemo } from 'react';

interface TileGridProps {
  imageUrl: string;
  tileX: number;
  tileY: number;
  offsetX?: number; // 0-1 fraction
  offsetY?: number;
  scale?: number; // 0.25-4.0
  rotation?: number; // degrees
  overlap?: number; // 0-0.5 fraction
  halfDrop?: boolean;
  containerWidth: number;
  containerHeight: number;
  showGridLines?: boolean;
}

export default function TileGrid({
  imageUrl,
  tileX,
  tileY,
  offsetX = 0,
  offsetY = 0,
  scale = 1,
  rotation = 0,
  overlap = 0,
  halfDrop = false,
  containerWidth,
  containerHeight,
  showGridLines = true,
}: TileGridProps) {
  const [image, setImage] = useState<HTMLImageElement | null>(null);

  useEffect(() => {
    const img = new window.Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => setImage(img);
    img.src = imageUrl;
  }, [imageUrl]);

  const tiles = useMemo(() => {
    if (!image) return [];

    const tileW = (containerWidth / tileX) * scale;
    const tileH = (containerHeight / tileY) * scale;
    const stepX = tileW * (1 - overlap);
    const stepY = tileH * (1 - overlap);

    const result: { x: number; y: number; w: number; h: number }[] = [];

    // Generate enough tiles to fill the view (with extra for offsets)
    for (let row = -1; row <= tileY + 1; row++) {
      for (let col = -1; col <= tileX + 1; col++) {
        let x = col * stepX;
        let y = row * stepY;

        // Half-drop offset
        if (halfDrop && row % 2 !== 0) {
          x += stepX * 0.5;
        }

        // User offset
        x += offsetX * stepX;
        y += offsetY * stepY;

        result.push({ x, y, w: tileW, h: tileH });
      }
    }

    return result;
  }, [image, tileX, tileY, offsetX, offsetY, scale, overlap, halfDrop, containerWidth, containerHeight]);

  // Grid lines
  const gridLines = useMemo(() => {
    if (!showGridLines || !image) return [];
    const lines: number[][] = [];
    const tileW = (containerWidth / tileX) * scale;
    const tileH = (containerHeight / tileY) * scale;
    const stepX = tileW * (1 - overlap);
    const stepY = tileH * (1 - overlap);

    for (let col = 0; col <= tileX; col++) {
      const x = col * stepX + offsetX * stepX;
      lines.push([x, 0, x, containerHeight]);
    }
    for (let row = 0; row <= tileY; row++) {
      const y = row * stepY + offsetY * stepY;
      lines.push([0, y, containerWidth, y]);
    }
    return lines;
  }, [showGridLines, image, tileX, tileY, scale, overlap, offsetX, offsetY, containerWidth, containerHeight]);

  return (
    <Stage
      width={containerWidth}
      height={containerHeight}
      className="bg-slate-950 rounded-xl overflow-hidden"
    >
      <Layer
        clipX={0}
        clipY={0}
        clipWidth={containerWidth}
        clipHeight={containerHeight}
      >
        {image && tiles.map((tile, i) => (
          <KonvaImage
            key={i}
            image={image}
            x={tile.x}
            y={tile.y}
            width={tile.w}
            height={tile.h}
            rotation={rotation}
            offsetX={tile.w / 2}
            offsetY={tile.h / 2}
          />
        ))}
        {gridLines.map((line, i) => (
          <Line
            key={`grid-${i}`}
            points={line}
            stroke="rgba(20, 184, 166, 0.15)"
            strokeWidth={1}
          />
        ))}
      </Layer>
    </Stage>
  );
}
