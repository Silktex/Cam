'use client';

import { useState, useRef, useCallback, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import StudioHeader from '@/components/StudioHeader';
import {
  Images,
  Search,
  Filter,
  Download,
  ArrowRight,
  Maximize2,
  ZoomIn,
  Camera,
  Layers,
  Sparkles,
  Loader2,
} from 'lucide-react';

interface Toast {
  id: string;
  message: string;
  type: 'info' | 'success' | 'warn' | 'error';
}

const LIGHT_STEPS = [
  { id: 'top', label: 'TOP', name: 'Top Dome Light' },
  { id: '1', label: '1', name: 'Side Spot #1 (N)' },
  { id: '2', label: '2', name: 'Side Spot #2 (NE)' },
  { id: '3', label: '3', name: 'Side Spot #3 (E)' },
  { id: '4', label: '4', name: 'Side Spot #4 (SE)' },
  { id: '5', label: '5', name: 'Side Spot #5 (S)' },
  { id: '6', label: '6', name: 'Side Spot #6 (SW)' },
  { id: '7', label: '7', name: 'Side Spot #7 (W)' },
  { id: '8', label: '8', name: 'Side Spot #8 (NW)' },
];

export default function AssetInspectionGalleryPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-chassis flex items-center justify-center text-gray-400 font-mono text-sm">
        <Loader2 className="w-5 h-5 animate-spin mr-2 text-accent" />
        Loading Asset Inspection Lightbox...
      </div>
    }>
      <AssetInspectionContent />
    </Suspense>
  );
}

function AssetInspectionContent() {
  const searchParams = useSearchParams();
  const initialFolder = searchParams.get('folder') || 'batch_silk_velvet_4355';

  const [toasts, setToasts] = useState<Toast[]>([]);
  const addToast = useCallback((message: string, type: 'info' | 'success' | 'warn' | 'error' = 'info') => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  const [selectedLight, setSelectedLight] = useState('top');
  const [searchQuery, setSearchQuery] = useState('Daylily 4355');
  const [loupeMode, setLoupeMode] = useState(true);

  // Loupe Mouse Tracking State
  const [cursorPos, setCursorPos] = useState({ x: 0, y: 0 });
  const [pctPos, setPctPos] = useState({ x: 50, y: 50 });
  const [isInsideContainer, setIsInsideContainer] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!containerRef.current || !loupeMode) return;
    const rect = containerRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    setCursorPos({ x, y });
    const px = Math.max(0, Math.min(100, (x / rect.width) * 100));
    const py = Math.max(0, Math.min(100, (y / rect.height) * 100));
    setPctPos({ x: px, y: py });
  };

  const handleSwitchLight = (lightId: string) => {
    setSelectedLight(lightId);
    const item = LIGHT_STEPS.find((l) => l.id === lightId);
    addToast(`Switched view to ${item?.name} (sample_posh_4355_${lightId}.ARW)`);
  };

  const handleDownloadZip = () => {
    addToast('Downloading batch_silk_velvet_4355_raw_set.zip (1.1 GB)...', 'success');
  };

  const activeLightObj = LIGHT_STEPS.find((l) => l.id === selectedLight) || LIGHT_STEPS[0];

  return (
    <div className="min-h-screen bg-chassis text-gray-100 font-sans flex flex-col antialiased selection:bg-accent selection:text-white">
      {/* Toast notifications */}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className="px-4 py-2.5 rounded-lg bg-surface-raised border border-border-strong text-xs font-mono text-white shadow-2xl flex items-center gap-2 transform transition-all duration-300 pointer-events-auto"
          >
            <span
              className={`w-2 h-2 rounded-full ${
                t.type === 'success'
                  ? 'bg-status-ok'
                  : t.type === 'warn'
                  ? 'bg-status-warn'
                  : t.type === 'error'
                  ? 'bg-status-err'
                  : 'bg-accent'
              }`}
            />
            <span>{t.message}</span>
          </div>
        ))}
      </div>

      {/* Global Header with Search Bar */}
      <header className="h-14 border-b border-border-subtle bg-surface/90 backdrop-blur px-5 flex items-center justify-between shrink-0 sticky top-0 z-40">
        <StudioHeader stationSubtitle="INSPECTION LIGHTBOX" />
      </header>

      {/* Main Deep-Zoom Lightbox View */}
      <main className="flex-1 p-6 max-w-7xl mx-auto w-full grid grid-cols-12 gap-6 overflow-y-auto">
        {/* LEFT: 61MP Deep-Zoom Loupe Viewport (8 Cols) */}
        <div className="col-span-12 lg:col-span-8 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-display font-bold text-white text-base">
                sample_posh_4355_{selectedLight}.ARW
              </h2>
              <p className="text-xs text-gray-400">
                9504 x 6336 px • 61.0 MP Uncompressed RAW • 122.4 MB
              </p>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  setLoupeMode(true);
                  addToast('100% 1:1 Pixel Loupe Mode: ENABLED');
                }}
                className={`px-2.5 py-1 rounded font-mono text-xs font-bold transition ${
                  loupeMode
                    ? 'bg-accent/20 border border-accent text-accent'
                    : 'bg-surface-raised border border-border-subtle text-gray-300 hover:text-white'
                }`}
              >
                100% 1:1 Pixel View
              </button>
              <button
                onClick={() => {
                  setLoupeMode(false);
                  addToast('Fit to Screen Mode: ENABLED');
                }}
                className={`px-2.5 py-1 rounded font-mono text-xs font-bold transition ${
                  !loupeMode
                    ? 'bg-accent/20 border border-accent text-accent'
                    : 'bg-surface-raised border border-border-subtle text-gray-300 hover:text-white'
                }`}
              >
                Fit to Screen
              </button>
            </div>
          </div>

          {/* Main Zoom Canvas with Loupe Target */}
          <div
            ref={containerRef}
            onMouseMove={handleMouseMove}
            onMouseEnter={() => setIsInsideContainer(true)}
            onMouseLeave={() => setIsInsideContainer(false)}
            className="relative w-full aspect-[3/2] rounded-xl bg-black border border-border-strong overflow-hidden flex items-center justify-center group shadow-2xl cursor-crosshair select-none"
          >
            <img
              src="https://images.unsplash.com/photo-1579546929518-9e396f3cc809?auto=format&fit=crop&w=1400&q=90"
              alt="61MP RAW Inspection Target"
              className="w-full h-full object-cover select-none pointer-events-none"
            />

            {/* 100% Zoom Loupe Floating Reticle */}
            {loupeMode && isInsideContainer && (
              <div
                style={{
                  left: `${cursorPos.x}px`,
                  top: `${cursorPos.y}px`,
                }}
                className="absolute w-48 h-48 rounded-full border-2 border-accent shadow-2xl bg-black overflow-hidden pointer-events-none transform -translate-x-1/2 -translate-y-1/2 transition-opacity duration-75"
              >
                <img
                  src="https://images.unsplash.com/photo-1579546929518-9e396f3cc809?auto=format&fit=crop&w=2400&q=100"
                  alt="100% Loupe Magnified Crop"
                  style={{
                    transform: `translate(-${pctPos.x * 2.8}%, -${pctPos.y * 2.8}%)`,
                  }}
                  className="w-[400%] h-[400%] object-cover absolute top-0 left-0"
                />
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                  <div className="w-2 h-2 rounded-full bg-accent"></div>
                </div>
                <span className="absolute bottom-2 left-1/2 transform -translate-x-1/2 text-[9px] font-mono font-bold text-accent bg-black/80 px-2 py-0.5 rounded">
                  100% CROP
                </span>
              </div>
            )}

            {/* Photometric Light Step Selector Toolbar */}
            <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2 bg-black/85 backdrop-blur px-4 py-2 rounded-full border border-white/10 flex items-center gap-2 font-mono text-xs shadow-2xl z-20">
              <span className="text-gray-400 text-[10px] pr-2 border-r border-white/10">LIGHT:</span>
              {LIGHT_STEPS.map((l) => (
                <button
                  key={l.id}
                  onClick={() => handleSwitchLight(l.id)}
                  className={`w-6 h-6 rounded-full text-[10px] font-bold transition ${
                    selectedLight === l.id
                      ? 'bg-accent text-chassis font-extrabold'
                      : 'bg-surface-raised text-gray-300 hover:text-white'
                  }`}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* RIGHT: EXIF Telemetry & Batch Operations (4 Cols) */}
        <div className="col-span-12 lg:col-span-4 space-y-6">
          {/* Search Bar */}
          <div className="p-4 rounded-xl bg-surface border border-border-subtle space-y-2 shadow-lg">
            <label className="block text-xs font-mono text-gray-400">SEARCH ARCHIVE (MEILISEARCH)</label>
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search SKU, fabric, batch..."
                className="w-full bg-chassis border border-border-strong rounded-lg pl-8 pr-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-accent"
              />
              <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-3" />
            </div>
          </div>

          {/* EXIF Telemetry Card */}
          <div className="p-5 rounded-xl bg-surface border border-border-subtle space-y-4 shadow-lg">
            <h3 className="font-display font-bold text-white text-sm uppercase tracking-wider">
              EXIF Hardware Telemetry
            </h3>

            <div className="space-y-2 font-mono text-xs divide-y divide-border-subtle">
              <div className="flex justify-between py-1.5">
                <span className="text-gray-400">CAMERA MODEL</span>
                <span className="text-white font-bold">Sony ILCE-7RM3</span>
              </div>
              <div className="flex justify-between py-1.5">
                <span className="text-gray-400">LENS</span>
                <span className="text-white">FE 90mm F2.8 Macro G OSS</span>
              </div>
              <div className="flex justify-between py-1.5">
                <span className="text-gray-400">EXPOSURE</span>
                <span className="text-accent font-bold">1/125s • f/8.0 • ISO 100</span>
              </div>
              <div className="flex justify-between py-1.5">
                <span className="text-gray-400">FOCAL LENGTH</span>
                <span className="text-white">90.0 mm</span>
              </div>
              <div className="flex justify-between py-1.5">
                <span className="text-gray-400">COLOR SPACE</span>
                <span className="text-white">sRGB (Calibrated D65)</span>
              </div>
              <div className="flex justify-between py-1.5">
                <span className="text-gray-400">ESP32 RIG STATE</span>
                <span className="text-status-ok font-bold">
                  {activeLightObj.name} (100% PWM)
                </span>
              </div>
            </div>

            <div className="pt-3 space-y-2">
              <button
                onClick={handleDownloadZip}
                className="w-full py-2.5 rounded-lg bg-surface-raised hover:bg-white/10 text-white font-mono text-xs border border-border-strong flex items-center justify-center gap-2 transition active:scale-95 cursor-pointer"
              >
                <Download className="w-4 h-4 text-accent" />
                Download RAW + TIFF Set (.zip)
              </button>
              <Link
                href="/processing"
                className="w-full py-2.5 rounded-lg bg-accent hover:bg-amber-500 text-chassis font-display font-bold text-xs tracking-wide shadow-lg shadow-accent/20 transition flex items-center justify-center gap-1 active:scale-95"
              >
                Send Batch to PBR Processing <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
