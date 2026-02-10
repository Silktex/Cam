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
          ? 'bg-white/10 border-amber-500/30 shadow-lg shadow-amber-500/10' 
          : 'bg-white/5 border-white/10'
        }
        border backdrop-blur-lg
      `}
    >
      {/* Active indicator bar */}
      <div
        className={`
          absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-amber-400 to-orange-500
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
            <p className="text-xs text-gray-400">GPIO {light.pin}</p>
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
          <div className="w-full h-full bg-white/10 rounded-full peer-checked:bg-gradient-to-r peer-checked:from-amber-400 peer-checked:to-orange-500 transition-all" />
          <div className="absolute top-1 left-1 w-5 h-5 bg-gray-500 rounded-full peer-checked:translate-x-7 peer-checked:bg-white transition-all" />
        </label>
      </div>

      {/* Brightness Control */}
      <div>
        <div className="flex justify-between text-sm text-gray-400 mb-2">
          <span>Brightness</span>
          <span className="text-amber-400 font-semibold">{localBrightness}%</span>
        </div>
        <input
          type="range"
          min="0"
          max="100"
          value={localBrightness}
          onInput={(e) => handleBrightnessInput(parseInt(e.currentTarget.value))}
          onChange={handleBrightnessCommit}
          className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer
            [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5
            [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-gradient-to-r 
            [&::-webkit-slider-thumb]:from-amber-400 [&::-webkit-slider-thumb]:to-orange-500
            [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:shadow-amber-500/30
            [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:transition-transform
            [&::-webkit-slider-thumb]:hover:scale-110"
        />
      </div>
    </div>
  );
}
