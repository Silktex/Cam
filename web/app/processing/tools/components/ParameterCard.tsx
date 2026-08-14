'use client';

import { ReactNode } from 'react';

interface ParameterCardProps {
  title: string;
  description?: string;
  children: ReactNode;
  collapsed?: boolean;
}

export default function ParameterCard({ title, description, children, collapsed }: ParameterCardProps) {
  return (
    <div className="bg-slate-800/50 rounded-2xl border border-slate-700/50 p-4">
      <h3 className="text-sm font-medium text-slate-200 mb-1">{title}</h3>
      {description && (
        <p className="text-xs text-slate-400 mb-3">{description}</p>
      )}
      {!collapsed && <div className="space-y-3">{children}</div>}
    </div>
  );
}

// Reusable slider control
interface SliderControlProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (value: number) => void;
  tooltip?: string;
}

export function SliderControl({
  label, value, min, max, step = 1, unit = '', onChange, tooltip
}: SliderControlProps) {
  return (
    <div className="space-y-1" title={tooltip}>
      <div className="flex items-center justify-between">
        <label className="text-xs text-slate-400">{label}</label>
        <span className="text-xs text-teal-400 font-mono">
          {Number.isInteger(step) ? value : value.toFixed(1)}{unit}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1.5 bg-slate-700 rounded-full appearance-none cursor-pointer
          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5
          [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-teal-400
          [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:shadow-lg"
      />
    </div>
  );
}

// Toggle control
interface ToggleControlProps {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
  tooltip?: string;
}

export function ToggleControl({ label, value, onChange, tooltip }: ToggleControlProps) {
  return (
    <div className="flex items-center justify-between" title={tooltip}>
      <label className="text-xs text-slate-400">{label}</label>
      <button
        onClick={() => onChange(!value)}
        className={`relative w-9 h-5 rounded-full transition-colors ${
          value ? 'bg-teal-500' : 'bg-slate-600'
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
            value ? 'translate-x-4' : ''
          }`}
        />
      </button>
    </div>
  );
}

// Select control
interface SelectControlProps {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  tooltip?: string;
}

export function SelectControl({ label, value, options, onChange, tooltip }: SelectControlProps) {
  return (
    <div className="space-y-1" title={tooltip}>
      <label className="text-xs text-slate-400">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-200
          focus:outline-none focus:ring-1 focus:ring-teal-500"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
  );
}
