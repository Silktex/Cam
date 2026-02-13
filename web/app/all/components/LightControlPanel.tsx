'use client';

import { Lightbulb, Wifi, WifiOff, RefreshCw } from 'lucide-react';
import { lightsApi } from '@/lib/lightsApi';
import { useState } from 'react';

interface LightState {
  id: number;
  name: string;
  pin: number;
  on: boolean;
  brightness: number;
}

interface LightControlPanelProps {
  lights: LightState[];
  connected: boolean;
  wsConnected: boolean;
  setLight: (id: number, on: boolean, brightness?: number) => void;
  setAllLights: (on: boolean, brightness?: number) => void;
  requestState: () => void;
}

export default function LightControlPanel({
  lights,
  connected,
  wsConnected,
  setLight,
  setAllLights,
  requestState,
}: LightControlPanelProps) {
  const [isReconnecting, setIsReconnecting] = useState(false);

  const activeCount = lights.filter((l) => l.on).length;

  const handleReconnect = async () => {
    setIsReconnecting(true);
    try {
      await lightsApi.reconnect();
    } catch (e) {
      // ignore
    } finally {
      setIsReconnecting(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Lightbulb className="w-5 h-5 text-teal-400" />
          <h2 className="text-base font-semibold text-white">Light Control</h2>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400">
            {activeCount}/{lights.length}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className={`w-2 h-2 rounded-full ${
              wsConnected ? 'bg-teal-400' : 'bg-slate-600'
            }`}
          />
          <button
            onClick={requestState}
            className="p-1 text-slate-400 hover:text-slate-200 rounded transition-colors"
            title="Refresh state"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Master controls */}
      <div className="flex gap-2 mb-3">
        <button
          onClick={() => setAllLights(true, 100)}
          className="flex-1 py-1.5 text-xs font-medium bg-teal-600 text-white rounded-lg hover:bg-teal-500 transition-colors"
        >
          All On
        </button>
        <button
          onClick={() => setAllLights(false)}
          className="flex-1 py-1.5 text-xs font-medium bg-slate-800 text-slate-300 rounded-lg hover:bg-slate-700 transition-colors"
        >
          All Off
        </button>
        <button
          onClick={handleReconnect}
          disabled={isReconnecting}
          className="px-3 py-1.5 text-xs font-medium bg-slate-800 text-slate-400 rounded-lg hover:bg-slate-700 disabled:opacity-50 transition-colors"
          title="Reconnect ESP32"
        >
          {isReconnecting ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          ) : connected ? (
            <Wifi className="w-3.5 h-3.5" />
          ) : (
            <WifiOff className="w-3.5 h-3.5" />
          )}
        </button>
      </div>

      {/* Light list */}
      <div className="space-y-1">
        {lights.map((light) => (
          <div
            key={light.id}
            className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-slate-800/50 transition-colors"
          >
            <div className="flex items-center gap-2.5">
              <span
                className={`w-2 h-2 rounded-full ${
                  light.on ? 'bg-teal-400' : 'bg-slate-600'
                }`}
              />
              <span className="text-sm text-slate-300">{light.name}</span>
            </div>
            {/* Toggle switch */}
            <button
              onClick={() => setLight(light.id, !light.on)}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                light.on ? 'bg-teal-500' : 'bg-slate-600'
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
                  light.on ? 'translate-x-[18px]' : 'translate-x-[3px]'
                }`}
              />
            </button>
          </div>
        ))}
      </div>

      {/* Connection status footer */}
      {!connected && (
        <div className="mt-3 text-xs text-center text-slate-500">
          ESP32 not connected — simulation mode
        </div>
      )}
    </div>
  );
}
