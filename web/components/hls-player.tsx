'use client';

import { useEffect, useRef, useState } from 'react';
import Hls from 'hls.js';

interface HlsPlayerProps {
  src: string;
  fallbackSrc?: string;
  className?: string;
  onFallback?: () => void;
}

export function HlsPlayer({ src, fallbackSrc, className, onFallback }: HlsPlayerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [useFallback, setUseFallback] = useState(false);

  useEffect(() => {
    if (!src) return;
    setUseFallback(false);

    const video = videoRef.current;
    if (!video) return;

    let hls: Hls | null = null;
    let cancelled = false;
    const fail = () => {
      if (!cancelled) {
        setUseFallback(true);
        onFallback?.();
      }
    };

    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = src;
      video.addEventListener('error', fail, { once: true });
      video.play().catch(() => {});
    } else if (Hls.isSupported()) {
      hls = new Hls({ lowLatencyMode: true, enableWorker: true });
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data.fatal) return;
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          hls?.startLoad();
        } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          hls?.recoverMediaError();
        } else {
          fail();
        }
      });
      video.play().catch(() => {});
    } else {
      fail();
    }

    return () => {
      cancelled = true;
      hls?.destroy();
      video.removeAttribute('src');
      video.load();
    };
  }, [src]);

  if (useFallback && fallbackSrc) {
    return <img src={fallbackSrc} alt="Live view" className={className} />;
  }

  return (
    <video
      ref={videoRef}
      className={className}
      autoPlay
      muted
      playsInline
    />
  );
}
