'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Video, VideoOff, RefreshCw, Layers, ShieldCheck, Eye, EyeOff, Zap, Grid, Focus } from 'lucide-react';
import { getWhepStreamUrl, getLiveViewUrl, setLiveViewSource, type LiveViewStatus } from '@/lib/api';

export interface WebRTCStreamViewerProps {
  streamSource?: 'hdmi' | 'ptp';
  onSourceChange?: (newSource: 'hdmi' | 'ptp') => void;
  gridVisible?: boolean;
  zebraVisible?: boolean;
  peakingVisible?: boolean;
  isFrozen?: boolean;
  afPulsing?: boolean;
  masterLux?: number;
  onSnapshotTaken?: (snapshotDataUrl: string) => void;
  onToast?: (message: string, type?: 'info' | 'success' | 'warn' | 'error') => void;
}

export function WebRTCStreamViewer({
  streamSource = 'hdmi',
  onSourceChange,
  gridVisible = true,
  zebraVisible = false,
  peakingVisible = false,
  isFrozen = false,
  afPulsing = false,
  masterLux = 100,
  onSnapshotTaken,
  onToast,
}: WebRTCStreamViewerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const sessionUrlRef = useRef<string | null>(null);
  const retryTimerRef = useRef<NodeJS.Timeout | null>(null);

  const [connectionState, setConnectionState] = useState<'connecting' | 'connected' | 'failed' | 'fallback'>('connecting');
  const [frozenFrame, setFrozenFrame] = useState<string | null>(null);
  const [activeSource, setActiveSource] = useState<'hdmi' | 'ptp'>(streamSource);
  const [currentFps, setCurrentFps] = useState<number>(30);

  // Sync prop changes
  useEffect(() => {
    setActiveSource(streamSource);
  }, [streamSource]);

  // Connect via WebRTC WHEP
  const connectWhep = useCallback(async () => {
    if (typeof window === 'undefined' || typeof RTCPeerConnection === 'undefined') {
      setConnectionState('fallback');
      return;
    }

    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }

    // Teardown existing connection
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }
    if (sessionUrlRef.current) {
      fetch(sessionUrlRef.current, { method: 'DELETE' }).catch(() => {});
      sessionUrlRef.current = null;
    }

    setConnectionState('connecting');

    try {
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
      });
      pcRef.current = pc;

      // Add recvonly transceiver for video
      pc.addTransceiver('video', { direction: 'recvonly' });

      pc.ontrack = (event) => {
        if (videoRef.current && event.streams[0]) {
          videoRef.current.srcObject = event.streams[0];
          setConnectionState('connected');
        }
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'connected') {
          setConnectionState('connected');
        } else if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
          setConnectionState('fallback');
          if (!retryTimerRef.current) {
            retryTimerRef.current = setTimeout(() => {
              connectWhep();
            }, 4000);
          }
        }
      };

      // Create Offer
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const whepUrl = getWhepStreamUrl();
      const response = await fetch(whepUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/sdp' },
        body: offer.sdp,
      });

      if (!response.ok) {
        throw new Error(`WHEP signaling returned status ${response.status}`);
      }

      const locationHeader = response.headers.get('Location');
      if (locationHeader) {
        sessionUrlRef.current = new URL(locationHeader, whepUrl).toString();
      }

      const answerSdp = await response.text();
      await pc.setRemoteDescription(new RTCSessionDescription({ type: 'answer', sdp: answerSdp }));
    } catch (err) {
      console.warn('WebRTC WHEP connection failed, using hardware fallback:', err);
      setConnectionState('fallback');
      if (!retryTimerRef.current) {
        retryTimerRef.current = setTimeout(() => {
          connectWhep();
        }, 5000);
      }
    }
  }, []);

  // Initialize stream on mount & active source change
  useEffect(() => {
    if (activeSource === 'ptp') {
      // PTP mode renders the MJPEG endpoint directly - no WebRTC involved
      return;
    }
    connectWhep();
    return () => {
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      if (pcRef.current) {
        pcRef.current.close();
        pcRef.current = null;
      }
      if (sessionUrlRef.current) {
        fetch(sessionUrlRef.current, { method: 'DELETE' }).catch(() => {});
        sessionUrlRef.current = null;
      }
    };
  }, [connectWhep, activeSource]);

  // Handle freeze frame snapshot
  useEffect(() => {
    if (isFrozen) {
      // Capture frame from video or fallback canvas
      if (videoRef.current && videoRef.current.videoWidth > 0) {
        const canvas = document.createElement('canvas');
        canvas.width = videoRef.current.videoWidth;
        canvas.height = videoRef.current.videoHeight;
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.drawImage(videoRef.current, 0, 0);
          const dataUrl = canvas.toDataURL('image/jpeg', 0.95);
          setFrozenFrame(dataUrl);
          onSnapshotTaken?.(dataUrl);
        }
      } else {
        // Fallback snapshot
        setFrozenFrame('https://images.unsplash.com/photo-1579546929518-9e396f3cc809?auto=format&fit=crop&w=1200&q=80');
      }
    } else {
      setFrozenFrame(null);
    }
  }, [isFrozen, onSnapshotTaken]);

  const handleToggleSource = async (newSource: 'hdmi' | 'ptp') => {
    setActiveSource(newSource);
    onSourceChange?.(newSource);
    try {
      await setLiveViewSource(newSource);
      onToast?.(
        newSource === 'hdmi'
          ? 'Switched to HDMI Clean Stream (MacroSilicon USB 3.0)'
          : 'Switched to Sony PTP Direct Sensor Stream',
        'success'
      );
    } catch {
      onToast?.(`Stream source switched to: ${newSource.toUpperCase()}`, 'info');
    }
    connectWhep();
  };

  const brightnessStyle = {
    filter: `brightness(${0.4 + (masterLux / 100) * 0.6})`,
  };

  return (
    <div
      data-testid="webrtc-stream-viewer"
      className={`relative w-full max-w-2xl aspect-[3/2] rounded-lg border border-border-strong overflow-hidden bg-zinc-900 shadow-2xl flex items-center justify-center group transition-all duration-200 ${
        peakingVisible ? 'peaking-glow' : ''
      }`}
    >
      {/* Hidden Offscreen Canvas for Snapshot / Processing */}
      <canvas ref={canvasRef} className="hidden" />

      {/* PTP Direct: MJPEG stream rendered natively */}
      {!isFrozen && activeSource === 'ptp' && (
        <img
          data-testid="ptp-mjpeg-feed"
          src={`${getLiveViewUrl()}?t=${Date.now()}`}
          alt="PTP Live View"
          className="w-full h-full object-cover"
          style={brightnessStyle}
        />
      )}

      {/* Primary Video Element (WebRTC HW Encoded Stream) */}
      {!isFrozen && activeSource !== 'ptp' && (
        <video
          ref={videoRef}
          data-testid="live-video-element"
          autoPlay
          playsInline
          muted
          className={`w-full h-full object-cover transition-opacity duration-300 ${
            connectionState === 'connected' ? 'opacity-95' : 'hidden'
          }`}
          style={brightnessStyle}
        />
      )}

      {/* No-signal placeholder (WebRTC unreachable) */}
      {(!isFrozen && activeSource !== 'ptp' && connectionState !== 'connected') && (
        <div
          data-testid="fallback-live-feed"
          className="w-full h-full flex flex-col items-center justify-center bg-zinc-950 text-zinc-500 gap-2"
        >
          <VideoOff className="w-10 h-10 opacity-40" />
          <span className="text-xs font-mono uppercase tracking-widest">No Signal</span>
          <span className="text-[10px] font-mono opacity-60">WebRTC unreachable - check network or switch SRC to PTP</span>
        </div>
      )}

      {/* Frozen Snapshot Image */}
      {isFrozen && (
        <img
          data-testid="frozen-snapshot-img"
          src={frozenFrame || 'https://images.unsplash.com/photo-1579546929518-9e396f3cc809?auto=format&fit=crop&w=1200&q=80'}
          alt="Frozen Live Feed"
          className="w-full h-full object-cover opacity-95"
          style={brightnessStyle}
        />
      )}

      {/* Rule-of-Thirds Grid Reticle & Center AF Crosshair */}
      {gridVisible && (
        <div className="absolute inset-0 grid grid-cols-3 grid-rows-3 pointer-events-none opacity-30 transition-opacity duration-200">
          <div className="border-r border-b border-white/40"></div>
          <div className="border-r border-b border-white/40"></div>
          <div className="border-b border-white/40"></div>
          <div className="border-r border-b border-white/40"></div>
          <div className="border-r border-b border-white/40 flex items-center justify-center">
            <div
              className={`w-8 h-8 rounded-full border flex items-center justify-center transition-all duration-300 ${
                afPulsing
                  ? 'scale-150 border-status-ok bg-status-ok/20'
                  : 'border-accent/80'
              }`}
            >
              <div className="w-1.5 h-1.5 bg-accent rounded-full"></div>
            </div>
          </div>
          <div className="border-b border-white/40"></div>
          <div className="border-r border-b border-white/40"></div>
          <div className="border-r border-b border-white/40"></div>
          <div></div>
        </div>
      )}

      {/* Zebra Clipping Highlight Overlay */}
      {zebraVisible && (
        <div className="absolute inset-0 zebra-pattern pointer-events-none opacity-30" />
      )}

      {/* Stream Source Switcher Pill (Top Right on Hover / PTP indicator) */}
      <div className="absolute top-2 right-2 z-30 flex items-center gap-1.5 pointer-events-auto">
        <button
          onClick={() => handleToggleSource(activeSource === 'hdmi' ? 'ptp' : 'hdmi')}
          title="Toggle Stream Source (HDMI vs PTP) [Shortcut: S]"
          className="px-2.5 py-1 rounded-md bg-black/80 hover:bg-black/95 text-[10px] font-mono text-gray-200 border border-white/15 flex items-center gap-1.5 backdrop-blur transition active:scale-95 shadow-lg"
        >
          <span
            className={`w-2 h-2 rounded-full ${
              activeSource === 'hdmi' ? 'bg-status-ok animate-pulse' : 'bg-accent'
            }`}
          />
          <span>{activeSource === 'hdmi' ? 'HDMI (MacroSilicon)' : 'PTP (Sony ILCE-7RM3)'}</span>
        </button>
      </div>
    </div>
  );
}
