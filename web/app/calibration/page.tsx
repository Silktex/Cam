'use client';

import { useState, useCallback } from 'react';
import StudioHeader from '@/components/StudioHeader';
import {
  Palette,
  RotateCw,
  FlipHorizontal,
  CheckCircle2,
  Download,
  Save,
  Sliders,
  Layers,
  Sparkles,
} from 'lucide-react';

interface Toast {
  id: string;
  message: string;
  type: 'info' | 'success' | 'warn' | 'error';
}

interface Patch {
  num: number;
  name: string;
  hex: string;
  refRgb: string;
  measRgb: string;
  deltaE: number;
}

const COLOR_CHECKER_PATCHES: Patch[] = [
  { num: 1, name: 'Dark Skin', hex: '#735244', refRgb: '115, 82, 68', measRgb: '118, 79, 65', deltaE: 1.12 },
  { num: 2, name: 'Light Skin', hex: '#c29682', refRgb: '194, 150, 130', measRgb: '198, 147, 128', deltaE: 1.25 },
  { num: 3, name: 'Blue Sky', hex: '#627a9d', refRgb: '98, 122, 157', measRgb: '95, 126, 160', deltaE: 0.94 },
  { num: 4, name: 'Foliage', hex: '#576c43', refRgb: '87, 108, 67', measRgb: '89, 106, 64', deltaE: 1.05 },
  { num: 5, name: 'Blue Flower', hex: '#8580b1', refRgb: '133, 128, 177', measRgb: '130, 131, 174', deltaE: 0.88 },
  { num: 6, name: 'Bluish Green', hex: '#67bdaa', refRgb: '103, 189, 170', measRgb: '106, 186, 172', deltaE: 1.15 },

  { num: 7, name: 'Orange', hex: '#d87f33', refRgb: '216, 127, 51', measRgb: '219, 124, 49', deltaE: 1.30 },
  { num: 8, name: 'Purplish Blue', hex: '#4754a2', refRgb: '71, 84, 162', measRgb: '69, 87, 165', deltaE: 1.18 },
  { num: 9, name: 'Moderate Red', hex: '#c05963', refRgb: '192, 89, 99', measRgb: '195, 87, 96', deltaE: 1.22 },
  { num: 10, name: 'Purple', hex: '#5b3c66', refRgb: '91, 60, 102', measRgb: '93, 58, 105', deltaE: 1.02 },
  { num: 11, name: 'Yellow Green', hex: '#93c343', refRgb: '147, 195, 67', measRgb: '144, 198, 70', deltaE: 1.10 },
  { num: 12, name: 'Orange Yellow', hex: '#e5a02e', refRgb: '229, 160, 46', measRgb: '231, 158, 44', deltaE: 1.14 },

  { num: 13, name: 'Blue', hex: '#293d8b', refRgb: '41, 61, 139', measRgb: '43, 59, 142', deltaE: 1.28 },
  { num: 14, name: 'Green', hex: '#4ca14f', refRgb: '76, 161, 79', measRgb: '74, 164, 82', deltaE: 1.16 },
  { num: 15, name: 'Primary Red', hex: '#b2393c', refRgb: '178, 57, 60', measRgb: '184, 52, 58', deltaE: 2.18 },
  { num: 16, name: 'Yellow', hex: '#e2be2c', refRgb: '226, 190, 44', measRgb: '224, 193, 47', deltaE: 1.06 },
  { num: 17, name: 'Magenta', hex: '#a64782', refRgb: '166, 71, 130', measRgb: '168, 69, 133', deltaE: 1.20 },
  { num: 18, name: 'Cyan', hex: '#1f87a6', refRgb: '31, 135, 166', measRgb: '33, 133, 169', deltaE: 1.09 },

  { num: 19, name: 'White 9.5 (.05 D)', hex: '#ffffff', refRgb: '255, 255, 255', measRgb: '252, 252, 251', deltaE: 0.65 },
  { num: 20, name: 'Neutral 8 (.23 D)', hex: '#dcdcdc', refRgb: '220, 220, 220', measRgb: '219, 219, 218', deltaE: 0.72 },
  { num: 21, name: 'Neutral 6.5 (.44 D)', hex: '#a0a0a0', refRgb: '160, 160, 160', measRgb: '161, 160, 159', deltaE: 0.81 },
  { num: 22, name: 'Neutral 5 (.70 D)', hex: '#707070', refRgb: '112, 112, 112', measRgb: '113, 111, 110', deltaE: 0.89 },
  { num: 23, name: 'Neutral 3.5 (1.05 D)', hex: '#404040', refRgb: '64, 64, 64', measRgb: '66, 63, 62', deltaE: 0.95 },
  { num: 24, name: 'Black 2 (1.50 D)', hex: '#1a1a1a', refRgb: '26, 26, 26', measRgb: '28, 25, 24', deltaE: 0.98 },
];

export default function ColorCalibrationStudioPage() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const addToast = useCallback((message: string, type: 'info' | 'success' | 'warn' | 'error' = 'info') => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  const [rotationAngle, setRotationAngle] = useState(0);
  const [isFlipped, setIsFlipped] = useState(false);
  const [selectedPatch, setSelectedPatch] = useState<Patch>(COLOR_CHECKER_PATCHES[14]); // #15 Primary Red default
  const [isDetecting, setIsDetecting] = useState(false);
  const [detectionStatus, setDetectionStatus] = useState('✓ 24 / 24 Swatches Locked (Confidence: 99.8%)');
  const [profileName, setProfileName] = useState('STUDIO-SONY-A7R3-5600K-AUG26');

  const handleRotate = () => {
    const next = (rotationAngle + 90) % 360;
    setRotationAngle(next);
    addToast(`Target canvas rotated to ${next}°`);
  };

  const handleFlip = () => {
    setIsFlipped((f) => !f);
    addToast(!isFlipped ? 'Target flipped horizontally' : 'Target reset flip');
  };

  const handleSelectPatch = (p: Patch) => {
    setSelectedPatch(p);
    addToast(`Patch #${p.num} (${p.name}): ${p.deltaE.toFixed(2)} ΔE error`);
  };

  const handleAutoDetect = () => {
    setIsDetecting(true);
    setDetectionStatus('Scanning ColorChecker grid (SAM)...');
    setTimeout(() => {
      setIsDetecting(false);
      setDetectionStatus('✓ 24 / 24 Swatches Locked (Confidence: 99.8%)');
      addToast('All 24 ColorChecker patches accurately locked with 99.8% confidence', 'success');
    }, 850);
  };

  const handleSaveProfile = () => {
    addToast(`Profile "${profileName}" saved and applied to batch pipeline`, 'success');
  };

  const handleExportIcc = () => {
    addToast(`Generated ICC Profile: ${profileName}.icc (Ready for download)`, 'success');
  };

  const avgDeltaE = (
    COLOR_CHECKER_PATCHES.reduce((acc, p) => acc + p.deltaE, 0) / COLOR_CHECKER_PATCHES.length
  ).toFixed(2);

  const maxDeltaEPatch = COLOR_CHECKER_PATCHES.reduce(
    (max, p) => (p.deltaE > max.deltaE ? p : max),
    COLOR_CHECKER_PATCHES[0]
  );

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
      <StudioHeader stationSubtitle="COLOR SCIENCE" />

      {/* Main Calibration Studio */}
      <main className="flex-1 p-6 max-w-7xl mx-auto w-full grid grid-cols-12 gap-6 overflow-y-auto">
        {/* LEFT: ColorChecker 24-Patch Detection Canvas (7 Cols) */}
        <div className="col-span-12 lg:col-span-7 space-y-6">
          {/* Interactive Calibration Viewport */}
          <div className="p-5 rounded-xl bg-surface border border-border-subtle space-y-4 shadow-lg">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-display font-bold text-white text-base">
                  X-Rite ColorChecker Classic (24 Patch)
                </h2>
                <p className="text-xs text-gray-400">
                  Automated corner-pin detection and chromatic adaptation (D65)
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleRotate}
                  className="px-2.5 py-1 rounded bg-surface-raised text-xs font-mono text-gray-300 border border-border-subtle hover:bg-white/10 transition active:scale-95 flex items-center gap-1"
                >
                  <RotateCw className="w-3 h-3" /> ↻ Rotate 90°
                </button>
                <button
                  onClick={handleFlip}
                  className="px-2.5 py-1 rounded bg-surface-raised text-xs font-mono text-gray-300 border border-border-subtle hover:bg-white/10 transition active:scale-95 flex items-center gap-1"
                >
                  <FlipHorizontal className="w-3 h-3" /> ⇄ Flip H
                </button>
              </div>
            </div>

            {/* Detected Target with Corner Pin Overlay */}
            <div className="relative w-full aspect-[4/3] rounded-lg bg-black border border-border-strong overflow-hidden flex items-center justify-center group">
              <div
                className="w-full h-full relative transition-transform duration-300"
                style={{
                  transform: `rotate(${rotationAngle}deg) scale(${isFlipped ? -1 : 1}, 1)`,
                }}
              >
                <img
                  src="https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&w=1000&q=80"
                  alt="ColorChecker Target"
                  className="w-full h-full object-cover opacity-85"
                />

                {/* 24-Patch Detected Grid Overlay */}
                <div className="absolute inset-8 border-2 border-accent/80 rounded grid grid-cols-6 grid-rows-4 gap-1.5 p-2 bg-black/40 backdrop-blur-xs shadow-2xl transition-all duration-300">
                  {COLOR_CHECKER_PATCHES.map((p) => {
                    const isSelected = selectedPatch.num === p.num;
                    return (
                      <button
                        key={p.num}
                        onClick={() => handleSelectPatch(p)}
                        style={{ backgroundColor: p.hex }}
                        className={`rounded border transition flex items-center justify-center text-[8px] font-mono hover:scale-105 ${
                          p.num >= 19 && p.num <= 21
                            ? 'text-black font-bold'
                            : 'text-white/90 font-medium'
                        } ${
                          isSelected
                            ? 'ring-2 ring-accent border-accent scale-105 z-10'
                            : 'border-white/20 hover:border-accent'
                        }`}
                      >
                        #{p.num}
                      </button>
                    );
                  })}
                </div>

                {/* Corner Anchors */}
                <div className="absolute top-6 left-6 w-4 h-4 rounded-full bg-accent border-2 border-white shadow cursor-grab"></div>
                <div className="absolute top-6 right-6 w-4 h-4 rounded-full bg-accent border-2 border-white shadow cursor-grab"></div>
                <div className="absolute bottom-6 left-6 w-4 h-4 rounded-full bg-accent border-2 border-white shadow cursor-grab"></div>
                <div className="absolute bottom-6 right-6 w-4 h-4 rounded-full bg-accent border-2 border-white shadow cursor-grab"></div>
              </div>
            </div>

            <div className="flex items-center justify-between text-xs pt-1">
              <button
                onClick={handleAutoDetect}
                disabled={isDetecting}
                className="px-4 py-2 rounded bg-accent/20 border border-accent/40 text-accent font-mono font-bold hover:bg-accent/30 transition active:scale-95 flex items-center gap-2 disabled:opacity-50"
              >
                <Sparkles className="w-3.5 h-3.5" />
                Auto-Detect Swatches (SAM)
              </button>
              <span
                className={`font-mono ${
                  isDetecting ? 'text-accent animate-pulse' : 'text-status-ok'
                }`}
              >
                {detectionStatus}
              </span>
            </div>
          </div>

          {/* Selected Patch Deep Inspector Card */}
          <div className="p-4 rounded-xl bg-surface border border-border-subtle space-y-3 shadow-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className="w-4 h-4 rounded border border-white/30"
                  style={{ backgroundColor: selectedPatch.hex }}
                ></span>
                <span className="font-mono font-bold text-sm text-white">
                  Selected: Patch #{selectedPatch.num} ({selectedPatch.name})
                </span>
              </div>
              <span
                className={`px-2 py-0.5 rounded font-mono text-xs font-bold ${
                  selectedPatch.deltaE > 2.0
                    ? 'bg-accent/20 text-accent'
                    : 'bg-status-ok/20 text-status-ok'
                }`}
              >
                {selectedPatch.deltaE.toFixed(2)} ΔE
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs font-mono">
              <div className="p-2.5 rounded bg-surface-raised border border-border-subtle">
                <span className="text-gray-400 block mb-1">REFERENCE sRGB (D65)</span>
                <span className="text-white font-bold">RGB({selectedPatch.refRgb})</span>
              </div>
              <div className="p-2.5 rounded bg-surface-raised border border-border-subtle">
                <span className="text-gray-400 block mb-1">MEASURED CAMERA RGB</span>
                <span className="text-accent font-bold">RGB({selectedPatch.measRgb})</span>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT: Spectral Delta-E Analysis & Matrix Output (5 Cols) */}
        <div className="col-span-12 lg:col-span-5 space-y-6">
          {/* Metrics Card */}
          <div className="p-5 rounded-xl bg-surface border border-border-subtle space-y-4 shadow-lg">
            <div className="flex items-center justify-between">
              <h3 className="font-display font-bold text-white text-sm uppercase tracking-wider">
                Calibration Metrics
              </h3>
              <span className="px-2 py-0.5 rounded bg-status-ok/15 text-status-ok font-mono text-xs font-bold">
                EXCELLENT
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 rounded-lg bg-surface-raised border border-border-subtle">
                <div className="text-xs text-gray-400 font-mono">AVG DELTA-E (CIE2000)</div>
                <div className="text-xl font-mono font-bold text-status-ok mt-1">
                  {avgDeltaE} ΔE
                </div>
              </div>
              <div className="p-3 rounded-lg bg-surface-raised border border-border-subtle">
                <div className="text-xs text-gray-400 font-mono">
                  MAX DELTA-E (#{maxDeltaEPatch.num})
                </div>
                <div className="text-xl font-mono font-bold text-accent mt-1">
                  {maxDeltaEPatch.deltaE.toFixed(2)} ΔE
                </div>
              </div>
            </div>

            {/* 3x3 Color Correction Matrix Output */}
            <div className="space-y-2 pt-2">
              <div className="text-xs font-mono text-gray-400">CALCULATED 3x3 CCM MATRIX:</div>
              <div className="p-3 rounded-lg bg-chassis border border-border-strong font-mono text-xs text-gray-300 leading-relaxed">
                [ +1.542, -0.412, -0.098 ]<br />
                [ -0.218, +1.389, -0.142 ]<br />
                [ +0.034, -0.321, +1.287 ]
              </div>
            </div>

            {/* Profile Persistence Form */}
            <div className="space-y-3 pt-3 border-t border-border-subtle">
              <div>
                <label className="block text-xs font-mono text-gray-400 mb-1.5">
                  PROFILE NAME
                </label>
                <input
                  type="text"
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                  className="w-full bg-chassis border border-border-strong rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-accent"
                />
              </div>

              <div className="space-y-2">
                <button
                  onClick={handleSaveProfile}
                  className="w-full py-3 rounded-lg bg-accent hover:bg-amber-500 text-chassis font-display font-bold text-sm tracking-wide shadow-lg shadow-accent/20 transition active:scale-95 cursor-pointer flex items-center justify-center gap-2"
                >
                  <Save className="w-4 h-4" />
                  SAVE & APPLY PROFILE TO SESSIONS
                </button>
                <button
                  onClick={handleExportIcc}
                  className="w-full py-2.5 rounded-lg bg-surface-raised hover:bg-white/10 text-gray-200 font-mono text-xs border border-border-strong transition flex items-center justify-center gap-2 active:scale-95"
                >
                  <Download className="w-3.5 h-3.5 text-accent" />
                  Export ICC Profile (.icc)
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
