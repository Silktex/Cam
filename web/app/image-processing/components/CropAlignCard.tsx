'use client';

import {
  Crop, RotateCcw, RotateCw, Check, X, Wand2, Loader2,
  RefreshCcw, RectangleHorizontal, Square, ChevronDown, ChevronRight, Waves
} from 'lucide-react';
import { getFullUrl } from '@/lib/api';
import PhaseCard from './PhaseCard';
import type { CropState, CropActions } from './useCropEditor';
import { pointLabels } from './useCropEditor';

interface CropAlignCardProps {
  batchName: string;
  status: string;
  params: Record<string, any>;
  onParamsChange: (params: Record<string, any>) => void;
  isActive: boolean;
  onActivate: () => void;
  onDeactivate: () => void;
  cropState: CropState | null;
  cropActions: CropActions | null;
  onRevert?: () => void;
}

export default function CropAlignCard({
  batchName,
  status,
  params,
  onParamsChange,
  isActive,
  onActivate,
  onDeactivate,
  cropState,
  cropActions,
  onRevert,
}: CropAlignCardProps) {
  // When not active, show simple "Open Crop Editor" button
  if (!isActive || !cropState || !cropActions) {
    return (
      <PhaseCard phaseNumber={1} title="Crop & Align" status={status} defaultOpen={status !== 'completed'} onRevert={onRevert}>
        <button
          onClick={onActivate}
          className="w-full flex items-center gap-2 px-3 py-2.5 bg-slate-800 hover:bg-slate-700
            rounded-lg text-sm text-slate-300 transition-colors"
        >
          <Crop className="w-4 h-4 text-teal-400" />
          Open Crop Editor
        </button>
        <p className="text-[11px] text-slate-500 mt-1.5">
          Crop, rotate, perspective correct & yarn straighten
        </p>

        {params.crop_type && (
          <div className="text-xs text-slate-500 mt-2">
            Crop: {params.crop_type} | Size: {params.crop_size}px
            {params.rotation ? ` | Rotation: ${params.rotation}°` : ''}
          </div>
        )}
      </PhaseCard>
    );
  }

  // Active: full crop controls
  const s = cropState;
  const a = cropActions;
  const dims = a.getCropDimensions();

  return (
    <PhaseCard phaseNumber={1} title="Crop & Align" status={status} forceOpen={true} onRevert={onRevert}>
      {/* Crop Size display */}
      <div className="mb-3">
        <div className="text-xs text-slate-400 mb-0.5">Crop Size</div>
        <div className="text-lg font-semibold text-white">
          {dims.width} x {dims.height}{' '}
          <span className="text-xs font-normal text-slate-500">px</span>
        </div>
        {s.imageData && (
          <div className="text-[11px] text-slate-500">
            Original: {s.imageData.width} x {s.imageData.height}
          </div>
        )}
      </div>

      {/* Crop Points */}
      <div className="mb-3 pb-3 border-b border-slate-700/50">
        <div className="text-xs font-medium text-slate-300 mb-2">Crop Points</div>
        <div className="text-[11px] text-slate-500 mb-2">Click on image or select point below</div>
        <div className="grid grid-cols-4 gap-1.5">
          {pointLabels.map((label, i) => (
            <button
              key={i}
              onClick={() => a.setCurrentPointIndex(i)}
              title={label}
              className={`aspect-square rounded-lg text-xs font-bold transition-all ${
                s.currentPointIndex === i
                  ? 'bg-teal-600 text-white ring-2 ring-teal-400'
                  : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
              }`}
            >
              {i + 1}
            </button>
          ))}
        </div>
        <div className="text-[11px] text-slate-500 mt-1 text-center">
          {pointLabels[s.currentPointIndex]}
        </div>

        {/* Shape correction */}
        <div className="mt-3 pt-2 border-t border-slate-700/50">
          <div className="text-[11px] text-slate-500 mb-1.5">Correct Shape</div>
          <div className="grid grid-cols-2 gap-1.5">
            <button
              onClick={a.handleRectangularize}
              className="flex items-center justify-center gap-1 py-1.5 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors text-xs"
              title="Make all corners 90 degrees"
            >
              <RectangleHorizontal className="w-3.5 h-3.5" />
              Straighten
            </button>
            <button
              onClick={a.handleSquarify}
              className="flex items-center justify-center gap-1 py-1.5 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors text-xs"
              title="Make equal width and height"
            >
              <Square className="w-3.5 h-3.5" />
              Make Square
            </button>
          </div>
        </div>
      </div>

      {/* Rotation */}
      <div className="mb-3 pb-3 border-b border-slate-700/50">
        <div className="text-xs font-medium text-slate-300 mb-2">Rotation</div>
        <div className="flex items-center gap-1.5 mb-2">
          <button
            onClick={() => a.setRotation((r: number) => r - 90)}
            className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5 text-slate-300" />
            <span className="text-xs text-slate-300">-90</span>
          </button>
          <button
            onClick={() => a.setRotation(0)}
            className="px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-xs text-slate-300 transition-colors"
          >
            0
          </button>
          <button
            onClick={() => a.setRotation((r: number) => r + 90)}
            className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors"
          >
            <RotateCw className="w-3.5 h-3.5 text-slate-300" />
            <span className="text-xs text-slate-300">+90</span>
          </button>
        </div>

        <input
          type="range"
          min="-180"
          max="180"
          step="0.5"
          value={s.rotation}
          onChange={(e) => a.setRotation(parseFloat(e.target.value))}
          className="w-full h-1.5 rounded-lg cursor-pointer mb-1.5"
          style={{
            background: `linear-gradient(to right, #14b8a6 0%, #14b8a6 ${((s.rotation + 180) / 360) * 100}%, #334155 ${((s.rotation + 180) / 360) * 100}%, #334155 100%)`,
          }}
        />

        <div className="flex items-center gap-1.5">
          <input
            type="number"
            min="-180"
            max="180"
            step="0.1"
            value={s.rotation.toFixed(1)}
            onChange={(e) => a.setRotation(parseFloat(e.target.value) || 0)}
            className="flex-1 px-2 py-1.5 text-xs bg-slate-700 border border-slate-600 rounded-lg text-white text-center"
          />
          <span className="text-xs text-slate-500">deg</span>
        </div>
      </div>

      {/* Yarn Straighten */}
      <div className="mb-3 pb-3 border-b border-slate-700/50">
        <button
          onClick={() => a.setStraightenExpanded(!s.straightenExpanded)}
          className="flex items-center justify-between w-full text-xs font-medium text-slate-300"
        >
          <span className="flex items-center gap-1.5">
            <Waves className="w-3.5 h-3.5" />
            Yarn Straighten
          </span>
          {s.straightenExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </button>

        {s.straightenExpanded && (
          <div className="mt-2 space-y-2">
            <button
              onClick={a.handleStraightenAnalyze}
              disabled={s.straightenProcessing !== null}
              className="w-full flex items-center justify-center gap-1.5 py-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 disabled:opacity-50 text-xs"
            >
              {s.straightenProcessing === 'analyze' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
              Analyze Yarns
            </button>

            {s.straightenAnalysis && (
              <div className="bg-slate-700/50 rounded-lg p-2 text-[11px] space-y-0.5">
                <div className="flex justify-between">
                  <span className="text-slate-400">Skew:</span>
                  <span className="text-white">{s.straightenAnalysis.skew_angle_deg?.toFixed(2)}deg</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Weft bow:</span>
                  <span className="text-white">{s.straightenAnalysis.max_weft_bow_px?.toFixed(1)}px</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Warp bow:</span>
                  <span className="text-white">{s.straightenAnalysis.max_warp_bow_px?.toFixed(1)}px</span>
                </div>
                {s.straightenAnalysis.recommendation && (
                  <div className="text-slate-400 pt-1 border-t border-slate-600">{s.straightenAnalysis.recommendation}</div>
                )}
              </div>
            )}

            {/* Mode */}
            <div>
              <label className="text-[11px] text-slate-400 block mb-0.5">Mode</label>
              <div className="grid grid-cols-3 gap-1">
                {['auto', 'skew', 'bow'].map(m => (
                  <button
                    key={m}
                    onClick={() => a.setStraightenMode(m)}
                    className={`py-1 rounded text-[11px] capitalize ${s.straightenMode === m ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'}`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>

            {/* Strength */}
            <div>
              <div className="flex justify-between text-[11px] mb-0.5">
                <span className="text-slate-400">Strength</span>
                <span className="text-white">{Math.round(s.straightenStrength * 100)}%</span>
              </div>
              <input
                type="range" min="0" max="1" step="0.05"
                value={s.straightenStrength}
                onChange={e => a.setStraightenStrength(parseFloat(e.target.value))}
                className="w-full h-1.5 rounded-lg cursor-pointer"
                style={{ background: `linear-gradient(to right, #6366f1 0%, #6366f1 ${s.straightenStrength * 100}%, #334155 ${s.straightenStrength * 100}%, #334155 100%)` }}
              />
            </div>

            {/* Direction */}
            <div>
              <label className="text-[11px] text-slate-400 block mb-0.5">Direction</label>
              <div className="grid grid-cols-3 gap-1">
                {['both', 'warp', 'weft'].map(d => (
                  <button
                    key={d}
                    onClick={() => a.setStraightenDirection(d)}
                    className={`py-1 rounded text-[11px] capitalize ${s.straightenDirection === d ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'}`}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>

            {/* Grid divisions */}
            <div>
              <div className="flex justify-between text-[11px] mb-0.5">
                <span className="text-slate-400">Grid Divisions</span>
                <span className="text-white">{s.straightenGrid}</span>
              </div>
              <input
                type="range" min="10" max="40" step="1"
                value={s.straightenGrid}
                onChange={e => a.setStraightenGrid(parseInt(e.target.value))}
                className="w-full h-1.5 rounded-lg cursor-pointer"
                style={{ background: `linear-gradient(to right, #6366f1 0%, #6366f1 ${((s.straightenGrid - 10) / 30) * 100}%, #334155 ${((s.straightenGrid - 10) / 30) * 100}%, #334155 100%)` }}
              />
            </div>

            {/* Manual angle */}
            <div>
              <label className="text-[11px] text-slate-400 block mb-0.5">Manual Angle Override</label>
              <div className="flex items-center gap-1.5">
                <input
                  type="number" step="0.1" min="-45" max="45"
                  value={s.manualSkewAngle ?? ''}
                  placeholder="Auto"
                  onChange={e => a.setManualSkewAngle(e.target.value ? parseFloat(e.target.value) : null)}
                  className="flex-1 px-2 py-1 text-[11px] bg-slate-700 border border-slate-600 rounded-lg text-white"
                />
                <span className="text-[11px] text-slate-500">deg</span>
              </div>
            </div>

            {/* Preview / Undo */}
            <div className="flex gap-1.5">
              <button
                onClick={a.handleStraightenPreview}
                disabled={s.straightenProcessing !== null}
                className="flex-1 flex items-center justify-center gap-1 py-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 disabled:opacity-50 text-xs"
              >
                {s.straightenProcessing === 'preview' ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                Preview
              </button>
              <button
                onClick={a.handleStraightenUndo}
                className="px-2 py-1.5 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 text-xs"
              >
                Undo
              </button>
            </div>

            {/* Preview images */}
            {s.straightenPreviewData && s.straightenPreviewData.before_url && (
              <div className="space-y-1">
                <div className="text-[11px] text-slate-400">Before / After</div>
                <div className="grid grid-cols-2 gap-1.5">
                  <img src={getFullUrl(s.straightenPreviewData.before_url)} alt="Before" className="rounded border border-slate-600" />
                  <img src={getFullUrl(s.straightenPreviewData.after_url)} alt="After" className="rounded border border-slate-600" />
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="mb-3 pb-3 border-b border-slate-700/50">
        <div className="text-xs font-medium text-slate-300 mb-2">Actions</div>
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 mb-1">
            <label className="text-[11px] text-slate-400">Crop Size:</label>
            <select
              value={s.cropSize}
              onChange={(e) => a.setCropSize(parseInt(e.target.value))}
              className="flex-1 px-2 py-1 text-xs bg-slate-700 border border-slate-600 rounded-lg text-white"
            >
              <option value={2048}>2048 x 2048</option>
              <option value={4096}>4096 x 4096</option>
              <option value={1024}>1024 x 1024</option>
            </select>
          </div>
          <button
            onClick={a.handleAutoDetect}
            disabled={s.processing !== null}
            className="w-full flex items-center justify-center gap-1.5 py-2 bg-violet-600 text-white rounded-lg hover:bg-violet-500 disabled:opacity-50 transition-colors text-xs"
          >
            {s.processing === 'auto' ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Wand2 className="w-3.5 h-3.5" />
            )}
            Auto Detect ({s.cropSize}px)
          </button>
          <button
            onClick={a.handleReset}
            className="w-full flex items-center justify-center gap-1.5 py-2 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors text-xs"
          >
            <RefreshCcw className="w-3.5 h-3.5" />
            Reset
          </button>
        </div>
      </div>

      {/* Method indicator */}
      <div className="mb-3">
        <div className="text-[11px] text-slate-500 mb-1">Method</div>
        <div className={`inline-block px-2 py-0.5 rounded-full text-xs ${
          s.method === 'auto' ? 'bg-violet-600 text-white' : 'bg-teal-600 text-white'
        }`}>
          {s.method === 'auto' ? 'Auto-detected' : 'Manual'}
        </div>
      </div>

      {/* Apply / Cancel */}
      <div className="space-y-1.5">
        <button
          onClick={a.handleApply}
          disabled={s.processing !== null || s.points.length !== 4}
          className="w-full flex items-center justify-center gap-1.5 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-500 disabled:opacity-50 font-medium transition-colors text-sm"
        >
          {s.processing === 'apply' ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Check className="w-4 h-4" />
          )}
          Apply to All Images
        </button>
        <button
          onClick={onDeactivate}
          className="w-full py-2 bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors text-xs"
        >
          Cancel
        </button>
      </div>

      {/* Custom slider styles */}
      <style jsx>{`
        input[type="range"] {
          -webkit-appearance: none;
          appearance: none;
        }
        input[type="range"]::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: 14px;
          height: 14px;
          border-radius: 50%;
          background: #14b8a6;
          cursor: pointer;
          border: 2px solid #0d7377;
        }
        input[type="range"]::-moz-range-thumb {
          width: 14px;
          height: 14px;
          border-radius: 50%;
          background: #14b8a6;
          cursor: pointer;
          border: 2px solid #0d7377;
        }
      `}</style>
    </PhaseCard>
  );
}
