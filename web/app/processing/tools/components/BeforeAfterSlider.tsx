'use client';

import { useState, useRef, useCallback, useEffect } from 'react';

interface BeforeAfterSliderProps {
  beforeUrl: string;
  afterUrl: string;
  width: number;
  height: number;
  label?: { before: string; after: string };
}

export default function BeforeAfterSlider({
  beforeUrl,
  afterUrl,
  width,
  height,
  label = { before: 'Before', after: 'After' },
}: BeforeAfterSliderProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState(50); // percentage
  const [isDragging, setIsDragging] = useState(false);

  const handleMove = useCallback((clientX: number) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const x = clientX - rect.left;
    const pct = Math.max(0, Math.min(100, (x / rect.width) * 100));
    setPosition(pct);
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => handleMove(e.clientX);
    const handleMouseUp = () => setIsDragging(false);
    const handleTouchMove = (e: TouchEvent) => handleMove(e.touches[0].clientX);

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    window.addEventListener('touchmove', handleTouchMove);
    window.addEventListener('touchend', handleMouseUp);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      window.removeEventListener('touchmove', handleTouchMove);
      window.removeEventListener('touchend', handleMouseUp);
    };
  }, [isDragging, handleMove]);

  const aspectRatio = width / height;

  return (
    <div
      ref={containerRef}
      className="relative w-full overflow-hidden rounded-xl border border-slate-700/50 cursor-col-resize select-none"
      style={{ aspectRatio }}
      onMouseDown={(e) => {
        setIsDragging(true);
        handleMove(e.clientX);
      }}
      onTouchStart={(e) => {
        setIsDragging(true);
        handleMove(e.touches[0].clientX);
      }}
    >
      {/* After image (full) */}
      <img
        src={afterUrl}
        alt={label.after}
        className="absolute inset-0 w-full h-full object-contain"
        draggable={false}
      />

      {/* Before image (clipped) */}
      <div
        className="absolute inset-0 overflow-hidden"
        style={{ width: `${position}%` }}
      >
        <img
          src={beforeUrl}
          alt={label.before}
          className="absolute inset-0 w-full h-full object-contain"
          style={{ width: `${(100 / position) * 100}%`, maxWidth: 'none' }}
          draggable={false}
        />
      </div>

      {/* Divider line */}
      <div
        className="absolute top-0 bottom-0 w-0.5 bg-white/80 shadow-lg pointer-events-none"
        style={{ left: `${position}%` }}
      >
        {/* Handle */}
        <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-8 h-8 rounded-full
          bg-white/90 border-2 border-teal-400 flex items-center justify-center shadow-xl">
          <div className="flex gap-0.5">
            <div className="w-0.5 h-3 bg-teal-500 rounded-full" />
            <div className="w-0.5 h-3 bg-teal-500 rounded-full" />
          </div>
        </div>
      </div>

      {/* Labels */}
      <div className="absolute top-2 left-2 px-2 py-0.5 bg-black/60 rounded text-xs text-slate-300">
        {label.before}
      </div>
      <div className="absolute top-2 right-2 px-2 py-0.5 bg-black/60 rounded text-xs text-slate-300">
        {label.after}
      </div>
    </div>
  );
}
