'use client';

import { useState, useRef, useEffect, useCallback, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import StudioHeader from '@/components/StudioHeader';
import {
  Layers,
  Sparkles,
  Sliders,
  Download,
  RotateCw,
  Eye,
  Maximize2,
  CheckCircle2,
  PackageCheck,
  FolderOpen,
  Loader2,
} from 'lucide-react';

interface Toast {
  id: string;
  message: string;
  type: 'info' | 'success' | 'warn' | 'error';
}

export default function PbrMaterialSynthesisPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-chassis flex items-center justify-center text-gray-400 font-mono text-sm">
        <Loader2 className="w-5 h-5 animate-spin mr-2 text-accent" />
        Loading PBR Material Lab...
      </div>
    }>
      <PbrSynthesisContent />
    </Suspense>
  );
}

function PbrSynthesisContent() {
  const searchParams = useSearchParams();
  const initialBatch = searchParams.get('batch') || 'batch_silk_velvet_4355';

  const [toasts, setToasts] = useState<Toast[]>([]);
  const addToast = useCallback((message: string, type: 'info' | 'success' | 'warn' | 'error' = 'info') => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  const [batchName, setBatchName] = useState(initialBatch);
  const [resolution, setResolution] = useState<'4K' | '8K'>('4K');
  const [materialClass, setMaterialClass] = useState('textile');
  const [normalStrength, setNormalStrength] = useState(1.4);
  const [roughnessBias, setRoughnessBias] = useState(0.65);
  const [seamlessTiling, setSeamlessTiling] = useState(true);

  // 3D Virtual Light Probe State
  const [probePos, setProbePos] = useState({ x: 30, y: 30 }); // percentage
  const [isDraggingProbe, setIsDraggingProbe] = useState(false);
  const normalContainerRef = useRef<HTMLDivElement>(null);

  // PBR Regeneration State
  const [isCalculating, setIsCalculating] = useState(false);
  const [calcProgress, setCalcProgress] = useState(0);

  // Probe Drag Handlers
  const handleMouseDownProbe = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsDraggingProbe(true);
  };

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDraggingProbe || !normalContainerRef.current) return;
      const rect = normalContainerRef.current.getBoundingClientRect();
      const x = Math.max(5, Math.min(rect.width - 20, e.clientX - rect.left));
      const y = Math.max(5, Math.min(rect.height - 20, e.clientY - rect.top));

      const pctX = Math.round((x / rect.width) * 100);
      const pctY = Math.round((y / rect.height) * 100);
      setProbePos({ x: pctX, y: pctY });
    };

    const handleMouseUp = () => {
      if (isDraggingProbe) {
        setIsDraggingProbe(false);
        addToast('Updated 3D virtual light probe vector', 'success');
      }
    };

    if (isDraggingProbe) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
    }
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDraggingProbe, addToast]);

  const handleRegeneratePbr = () => {
    setIsCalculating(true);
    setCalcProgress(0);

    let p = 0;
    const timer = setInterval(() => {
      p += 20;
      setCalcProgress(p);
      if (p >= 100) {
        clearInterval(timer);
        setTimeout(() => {
          setIsCalculating(false);
          addToast('PBR Material Synthesis completed: Albedo, Normal, Roughness, Height updated', 'success');
        }, 300);
      }
    }, 140);
  };

  const handleExportGltf = () => {
    addToast(`Generated glTF 2.0 Material Archive (${resolution}) with 16-bit maps (.zip)`, 'success');
  };

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

      {/* Global Header */}
      <StudioHeader stationSubtitle="PBR SYNTHESIS LAB" />

      {/* Main Material Workbench */}
      <main className="flex-1 p-6 max-w-7xl mx-auto w-full grid grid-cols-12 gap-6 overflow-y-auto">
        {/* LEFT: 2x2 Interactive PBR Quad-Map Viewport (8 Cols) */}
        <div className="col-span-12 lg:col-span-8 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-display font-bold text-white text-base">
                Photometric Stereo Material Extraction
              </h2>
              <p className="text-xs text-gray-400">
                Derived from 9 multi-light directional RAW captures ({batchName})
              </p>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-gray-400">RESOLUTION:</span>
              <button
                onClick={() => {
                  setResolution('4K');
                  addToast('Texture synthesis resolution set to 4K (4096px)');
                }}
                className={`px-2.5 py-0.5 rounded font-mono text-xs font-bold transition ${
                  resolution === '4K'
                    ? 'bg-accent/20 border border-accent text-accent'
                    : 'bg-surface-raised border border-border-subtle text-gray-400 hover:text-white'
                }`}
              >
                4K (4096px)
              </button>
              <button
                onClick={() => {
                  setResolution('8K');
                  addToast('Texture synthesis resolution set to 8K MASTER');
                }}
                className={`px-2.5 py-0.5 rounded font-mono text-xs font-bold transition ${
                  resolution === '8K'
                    ? 'bg-accent/20 border border-accent text-accent'
                    : 'bg-surface-raised border border-border-subtle text-gray-400 hover:text-white'
                }`}
              >
                8K MASTER
              </button>
            </div>
          </div>

          {/* 2x2 Texture Maps Grid */}
          <div className="grid grid-cols-2 gap-3 aspect-square max-h-[620px] w-full">
            {/* Quad 1: Albedo / Base Color */}
            <div className="rounded-xl bg-black border border-border-strong overflow-hidden relative group shadow-lg">
              <img
                src="https://images.unsplash.com/photo-1579546929518-9e396f3cc809?auto=format&fit=crop&w=600&q=80"
                alt="Albedo Map"
                className="w-full h-full object-cover"
              />
              <div className="absolute top-2 left-2 px-2 py-1 rounded bg-black/80 backdrop-blur text-xs font-mono text-white font-bold border border-white/10">
                ALBEDO (DIFFUSE BASE)
              </div>
              <button
                onClick={() => addToast('Inspecting 1:1 Albedo Diffuse Map')}
                className="absolute bottom-2 right-2 p-1.5 rounded bg-black/70 hover:bg-black text-gray-300 hover:text-white border border-white/10 transition"
              >
                <Maximize2 className="w-4 h-4" />
              </button>
            </div>

            {/* Quad 2: Tangent Normal Map with 3D Light Probe */}
            <div
              ref={normalContainerRef}
              className="rounded-xl bg-black border border-border-strong overflow-hidden relative group shadow-lg select-none"
            >
              <img
                src="https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=600&q=80"
                alt="Normal Map"
                style={{ filter: `contrast(${100 + (normalStrength - 1) * 30}%)` }}
                className="w-full h-full object-cover hue-rotate-180 brightness-110 transition-all duration-150"
              />
              <div className="absolute top-2 left-2 px-2 py-1 rounded bg-black/80 backdrop-blur text-xs font-mono text-accent font-bold border border-white/10 flex items-center gap-2">
                <span>TANGENT NORMAL</span>
                <span className="w-2 h-2 rounded-full bg-accent animate-ping"></span>
              </div>

              {/* Dynamic Specular Lighting Overlay */}
              <div
                className="absolute inset-0 pointer-events-none opacity-40 mix-blend-overlay"
                style={{
                  background: `radial-gradient(circle at ${probePos.x}% ${probePos.y}%, rgba(255,255,255,0.9), transparent 60%)`,
                }}
              />

              {/* Interactive 3D Virtual Sphere Light Probe */}
              <div
                onMouseDown={handleMouseDownProbe}
                style={{
                  left: `${probePos.x}%`,
                  top: `${probePos.y}%`,
                  transform: 'translate(-50%, -50%)',
                }}
                className="absolute w-14 h-14 rounded-full border-2 border-white/60 bg-[radial-gradient(ellipse_at_35%_35%,_var(--tw-gradient-stops))] from-white via-amber-400 to-amber-900 shadow-2xl shadow-black flex items-center justify-center cursor-grab active:cursor-grabbing select-none transition-all hover:scale-110"
                title="Drag to adjust virtual 3D lighting vector"
              >
                <span className="text-[8px] font-mono text-chassis font-extrabold pointer-events-none">
                  LIGHT
                </span>
              </div>
            </div>

            {/* Quad 3: Roughness Map */}
            <div className="rounded-xl bg-black border border-border-strong overflow-hidden relative group shadow-lg">
              <img
                src="https://images.unsplash.com/photo-1579546929518-9e396f3cc809?auto=format&fit=crop&w=600&q=80"
                alt="Roughness Map"
                style={{ opacity: 0.4 + roughnessBias * 0.6 }}
                className="w-full h-full object-cover grayscale contrast-150 transition-all duration-300"
              />
              <div className="absolute top-2 left-2 px-2 py-1 rounded bg-black/80 backdrop-blur text-xs font-mono text-gray-200 font-bold border border-white/10">
                ROUGHNESS (SPECULAR)
              </div>
            </div>

            {/* Quad 4: Height / Displacement Map */}
            <div className="rounded-xl bg-black border border-border-strong overflow-hidden relative group shadow-lg">
              <img
                src="https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&w=600&q=80"
                alt="Displacement Map"
                className="w-full h-full object-cover grayscale brightness-75 contrast-200 transition-all duration-300"
              />
              <div className="absolute top-2 left-2 px-2 py-1 rounded bg-black/80 backdrop-blur text-xs font-mono text-gray-200 font-bold border border-white/10">
                DISPLACEMENT (HEIGHT)
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT: Extraction Parameters & Seamless Tiling (4 Cols) */}
        <div className="col-span-12 lg:col-span-4 space-y-6">
          {/* Material Properties Card */}
          <div className="p-5 rounded-xl bg-surface border border-border-subtle space-y-4 shadow-lg">
            <h3 className="font-display font-bold text-white text-sm uppercase tracking-wider">
              PBR Extraction Parameters
            </h3>

            <div className="space-y-3 text-xs">
              <div>
                <label className="block font-mono text-gray-400 mb-1">MATERIAL CLASS</label>
                <select
                  value={materialClass}
                  onChange={(e) => {
                    setMaterialClass(e.target.value);
                    addToast(`Material preset loaded: ${e.target.value.toUpperCase()}`);
                  }}
                  className="w-full bg-chassis border border-border-strong rounded-lg px-3 py-2 font-mono text-white focus:outline-none focus:border-accent"
                >
                  <option value="textile">Woven Textile / Jacquard</option>
                  <option value="velvet">Velvet / Cut Pile</option>
                  <option value="leather">Leather / Natural Grain</option>
                  <option value="metal">Hard Metallic Coating</option>
                </select>
              </div>

              <div>
                <div className="flex justify-between font-mono text-gray-400 mb-1">
                  <span>NORMAL MAP STRENGTH</span>
                  <span className="text-accent font-bold">{normalStrength.toFixed(1)}x</span>
                </div>
                <input
                  type="range"
                  min="0.5"
                  max="3.0"
                  step="0.1"
                  value={normalStrength}
                  onChange={(e) => setNormalStrength(parseFloat(e.target.value))}
                  className="w-full accent-accent h-1.5 bg-chassis rounded-lg appearance-none cursor-pointer"
                />
              </div>

              <div>
                <div className="flex justify-between font-mono text-gray-400 mb-1">
                  <span>ROUGHNESS BIAS</span>
                  <span className="text-accent font-bold">{roughnessBias.toFixed(2)}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={roughnessBias}
                  onChange={(e) => setRoughnessBias(parseFloat(e.target.value))}
                  className="w-full accent-accent h-1.5 bg-chassis rounded-lg appearance-none cursor-pointer"
                />
              </div>

              {/* Seamless Tiling Toggle */}
              <div className="p-3 rounded-lg bg-surface-raised border border-border-subtle flex items-center justify-between pt-2">
                <div>
                  <div className="font-mono font-bold text-white">Seamless Texture Tiling</div>
                  <div className="text-[10px] text-gray-400">Synthesis boundary blending</div>
                </div>
                <input
                  type="checkbox"
                  checked={seamlessTiling}
                  onChange={(e) => {
                    setSeamlessTiling(e.target.checked);
                    addToast(`Seamless boundary tiling: ${e.target.checked ? 'ENABLED' : 'DISABLED'}`);
                  }}
                  className="w-4 h-4 accent-accent rounded cursor-pointer"
                />
              </div>
            </div>

            {/* Extraction Progress Indicator */}
            {isCalculating && (
              <div className="space-y-1.5 pt-2">
                <div className="flex justify-between text-xs font-mono">
                  <span className="text-accent font-bold">Solving Surface Gradients...</span>
                  <span className="text-gray-300">{calcProgress}%</span>
                </div>
                <div className="w-full bg-chassis rounded-full h-1.5 overflow-hidden">
                  <div
                    className="bg-accent h-full rounded-full transition-all duration-150"
                    style={{ width: `${calcProgress}%` }}
                  />
                </div>
              </div>
            )}

            <div className="space-y-2 pt-2">
              <button
                onClick={handleRegeneratePbr}
                disabled={isCalculating}
                className="w-full py-3 rounded-lg bg-accent hover:bg-amber-500 text-chassis font-display font-bold text-sm tracking-wide shadow-lg shadow-accent/20 transition active:scale-95 cursor-pointer disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {isCalculating ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Sparkles className="w-4 h-4" />
                )}
                RE-GENERATE PBR TEXTURES
              </button>

              <button
                onClick={handleExportGltf}
                className="w-full py-2.5 rounded-lg bg-surface-raised hover:bg-white/10 text-white font-mono text-xs border border-border-strong transition flex items-center justify-center gap-2 active:scale-95"
              >
                <Download className="w-3.5 h-3.5 text-accent" />
                Export glTF 2.0 Package (.zip)
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
