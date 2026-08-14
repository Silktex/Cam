'use client';

import { Stage, Layer, Image as KonvaImage, Rect, Text, Line } from 'react-konva';
import { useState, useEffect } from 'react';

interface SeamScores {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

interface SeamHighlightProps {
  imageUrl: string;
  imageWidth: number;
  imageHeight: number;
  blendWidth: number;
  seamScores?: SeamScores;
  containerWidth: number;
  containerHeight: number;
  showSeamLine?: boolean;
}

function scoreColor(score: number): string {
  if (score < 10) return 'rgba(34, 197, 94, 0.35)'; // green
  if (score < 30) return 'rgba(234, 179, 8, 0.35)'; // yellow
  return 'rgba(239, 68, 68, 0.35)'; // red
}

function scoreBadge(score: number): string {
  if (score < 10) return '#22c55e';
  if (score < 30) return '#eab308';
  return '#ef4444';
}

export default function SeamHighlight({
  imageUrl,
  imageWidth,
  imageHeight,
  blendWidth,
  seamScores,
  containerWidth,
  containerHeight,
  showSeamLine = false,
}: SeamHighlightProps) {
  const [image, setImage] = useState<HTMLImageElement | null>(null);

  const scaleX = (containerWidth - 32) / imageWidth;
  const scaleY = (containerHeight - 32) / imageHeight;
  const displayScale = Math.min(scaleX, scaleY, 1);

  const displayWidth = imageWidth * displayScale;
  const displayHeight = imageHeight * displayScale;
  const ox = (containerWidth - displayWidth) / 2;
  const oy = (containerHeight - displayHeight) / 2;

  const bw = blendWidth * displayScale;

  useEffect(() => {
    const img = new window.Image();
    img.onload = () => setImage(img);
    img.onerror = () => {
      const retry = new window.Image();
      retry.onload = () => setImage(retry);
      retry.src = imageUrl;
    };
    img.crossOrigin = 'anonymous';
    img.src = imageUrl;
  }, [imageUrl]);

  return (
    <Stage width={containerWidth} height={containerHeight} className="bg-slate-950 rounded-xl">
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

        {/* Top edge strip */}
        <Rect
          x={ox} y={oy}
          width={displayWidth} height={bw}
          fill={seamScores ? scoreColor(seamScores.top) : 'rgba(239, 68, 68, 0.25)'}
        />
        {/* Bottom edge strip */}
        <Rect
          x={ox} y={oy + displayHeight - bw}
          width={displayWidth} height={bw}
          fill={seamScores ? scoreColor(seamScores.bottom) : 'rgba(59, 130, 246, 0.25)'}
        />
        {/* Left edge strip */}
        <Rect
          x={ox} y={oy}
          width={bw} height={displayHeight}
          fill={seamScores ? scoreColor(seamScores.left) : 'rgba(34, 197, 94, 0.25)'}
        />
        {/* Right edge strip */}
        <Rect
          x={ox + displayWidth - bw} y={oy}
          width={bw} height={displayHeight}
          fill={seamScores ? scoreColor(seamScores.right) : 'rgba(234, 179, 8, 0.25)'}
        />

        {/* Seam center cross lines */}
        {showSeamLine && (
          <>
            {/* Horizontal center line */}
            <Line
              points={[ox, oy + displayHeight / 2, ox + displayWidth, oy + displayHeight / 2]}
              stroke="rgba(239, 68, 68, 0.7)"
              strokeWidth={1.5}
              dash={[6, 4]}
            />
            {/* Vertical center line */}
            <Line
              points={[ox + displayWidth / 2, oy, ox + displayWidth / 2, oy + displayHeight]}
              stroke="rgba(239, 68, 68, 0.7)"
              strokeWidth={1.5}
              dash={[6, 4]}
            />
          </>
        )}

        {/* Score badges */}
        {seamScores && (
          <>
            <Text
              x={ox + displayWidth / 2 - 20} y={oy + 4}
              text={`\u2191 ${seamScores.top.toFixed(1)}`}
              fontSize={12} fontFamily="monospace"
              fill={scoreBadge(seamScores.top)}
            />
            <Text
              x={ox + displayWidth / 2 - 20} y={oy + displayHeight - 18}
              text={`\u2193 ${seamScores.bottom.toFixed(1)}`}
              fontSize={12} fontFamily="monospace"
              fill={scoreBadge(seamScores.bottom)}
            />
            <Text
              x={ox + 4} y={oy + displayHeight / 2 - 6}
              text={`\u2190 ${seamScores.left.toFixed(1)}`}
              fontSize={12} fontFamily="monospace"
              fill={scoreBadge(seamScores.left)}
            />
            <Text
              x={ox + displayWidth - 50} y={oy + displayHeight / 2 - 6}
              text={`${seamScores.right.toFixed(1)} \u2192`}
              fontSize={12} fontFamily="monospace"
              fill={scoreBadge(seamScores.right)}
            />
          </>
        )}
      </Layer>
    </Stage>
  );
}
