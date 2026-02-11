'use client';

import { useState } from 'react';

interface LightState {
  id: number;
  name: string;
  pin: number;
  on: boolean;
  brightness: number;
}

interface LightCardProps {
  light: LightState;
  onToggle: (id: number, on: boolean) => void;
  onBrightnessChange: (id: number, brightness: number) => void;
}

export function LightCard({ light, onToggle, onBrightnessChange }: LightCardProps) {
  const [localBrightness, setLocalBrightness] = useState(light.brightness);

  const handleBrightnessInput = (value: number) => {
    setLocalBrightness(value);
  };

  const handleBrightnessCommit = () => {
    onBrightnessChange(light.id, localBrightness);
  };

  return (
    <div
      className={`
        relative overflow-hidden rounded-2xl p-6 transition-all duration-300
        ${light.on
          ? 'bg-slate-800/80 border-teal-500/40 shadow-lg shadow-teal-500/10'
          : 'bg-slate-800/50 border-slate-700'
        }
        border
      `}
    >
      {/* Active indicator bar */}
      <div
        className={`
          absolute top-0 left-0 right-0 h-1 bg-teal-500
          transition-opacity duration-300
          ${light.on ? 'opacity-100' : 'opacity-0'}
        `}
      />

      {/* Header */}
      <div className="flex justify-between items-center mb-5">
        <div className="flex items-center gap-3">
          <span className={`text-3xl transition-all ${light.on ? '' : 'grayscale opacity-40'}`}>
            {light.on ? '💡' : '🔌'}
          </span>
          <div>
            <h3 className="font-semibold text-white">{light.name}</h3>
            <p className="text-xs text-slate-400">GPIO {light.pin}</p>
          </div>
        </div>

        {/* Toggle Switch */}
        <label className="relative w-14 h-7 cursor-pointer">
          <input
            type="checkbox"
            checked={light.on}
            onChange={(e) => onToggle(light.id, e.target.checked)}
            className="sr-only peer"
          />
          <div className="w-full h-full bg-slate-700 rounded-full peer-checked:bg-teal-500 transition-all" />
          <div className="absolute top-1 left-1 w-5 h-5 bg-slate-500 rounded-full peer-checked:translate-x-7 peer-checked:bg-white transition-all" />
        </label>
      </div>

      {/* Brightness Control */}
      <div>
        <div className="flex justify-between text-sm text-slate-400 mb-2">
          <span>Brightness</span>
          <span className="text-teal-400 font-semibold">{localBrightness}%</span>
        </div>
        <input
          type="range"
          min="0"
          max="100"
          value={localBrightness}
          onInput={(e) => handleBrightnessInput(parseInt(e.currentTarget.value))}
          onChange={handleBrightnessCommit}
          className="w-full"
        />
      </div>
    </div>
  );
}
