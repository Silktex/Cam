'use client';

import { useState, useEffect } from 'react';
import { useLightsWebSocket } from '@/hooks/useLightsWebSocket';
import { lightsApi } from '@/lib/lightsApi';
import { LightCard } from '@/components/LightCard';

export default function LightsPage() {
  const {
    lights,
    connected,
    wsConnected,
    esp32Host,
    setLight,
    setAllLights,
    requestState,
  } = useLightsWebSocket();

  const [masterBrightness, setMasterBrightness] = useState(100);
  const [toast, setToast] = useState<string | null>(null);
  const [isReconnecting, setIsReconnecting] = useState(false);

  const showToast = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(null), 2000);
  };

  const handleToggle = async (id: number, on: boolean) => {
    setLight(id, on);
    const light = lights.find(l => l.id === id);
    showToast(`${light?.name || 'Light'} ${on ? 'ON' : 'OFF'}`);
  };

  const handleBrightnessChange = async (id: number, brightness: number) => {
    setLight(id, true, brightness);
    const light = lights.find(l => l.id === id);
    showToast(`${light?.name || 'Light'} → ${brightness}%`);
  };

  const handleAllOn = () => {
    setAllLights(true, masterBrightness);
    showToast('All lights ON');
  };

  const handleAllOff = () => {
    setAllLights(false);
    showToast('All lights OFF');
  };

  const handleReconnect = async () => {
    setIsReconnecting(true);
    try {
      const result = await lightsApi.reconnect();
      showToast(result.message);
    } catch (e) {
      showToast('Failed to reconnect');
    } finally {
      setIsReconnecting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-white p-5">
      {/* Header */}
      <header className="text-center py-8 mb-8">
        <h1 className="text-4xl font-light tracking-wide mb-3">
          ESP32 <span className="font-semibold text-teal-400">Light Controller</span>
        </h1>

        {/* Status */}
        <div className="flex items-center justify-center gap-3">
          <div className={`w-3 h-3 rounded-full animate-pulse ${connected ? 'bg-teal-400' : 'bg-red-400'}`} />
          <span className="text-sm text-slate-400">
            {connected ? `Connected to ${esp32Host}` : 'Simulation Mode (ESP32 not connected)'}
          </span>
          <span className="text-slate-600">•</span>
          <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-teal-400' : 'bg-slate-500'}`} />
          <span className="text-xs text-slate-500">
            {wsConnected ? 'WebSocket Live' : 'WebSocket Disconnected'}
          </span>
        </div>
      </header>

      {/* Master Controls */}
      <div className="flex flex-wrap justify-center gap-4 mb-10">
        <button
          onClick={handleAllOn}
          className="px-8 py-3 rounded-2xl font-semibold bg-teal-500 text-slate-900
            hover:-translate-y-0.5 hover:bg-teal-400 hover:shadow-lg hover:shadow-teal-500/30 transition-all"
        >
          ALL ON
        </button>
        <button
          onClick={handleAllOff}
          className="px-8 py-3 rounded-2xl font-semibold bg-slate-700 text-white
            hover:-translate-y-0.5 hover:bg-slate-600 hover:shadow-lg transition-all"
        >
          ALL OFF
        </button>

        <div className="flex items-center gap-3 bg-slate-800/80 border border-slate-700 px-5 py-2 rounded-2xl">
          <label className="text-sm text-slate-400">Master</label>
          <input
            type="range"
            min="0"
            max="100"
            value={masterBrightness}
            onChange={(e) => setMasterBrightness(parseInt(e.target.value))}
            className="w-24"
          />
          <span className="text-sm min-w-[40px] text-right text-teal-400">{masterBrightness}%</span>
        </div>

        <button
          onClick={requestState}
          className="px-6 py-3 rounded-2xl font-medium bg-teal-600/20 text-teal-400 border border-teal-500/30
            hover:bg-teal-600/30 transition-all"
        >
          ↻ Refresh
        </button>

        <button
          onClick={handleReconnect}
          disabled={isReconnecting}
          className="px-6 py-3 rounded-2xl font-medium bg-slate-700/50 text-slate-300 border border-slate-600
            hover:bg-slate-700 disabled:opacity-50 transition-all"
        >
          {isReconnecting ? 'Reconnecting...' : 'Reconnect ESP32'}
        </button>
      </div>

      {/* Lights Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 max-w-6xl mx-auto">
        {lights.map((light) => (
          <LightCard
            key={light.id}
            light={light}
            onToggle={handleToggle}
            onBrightnessChange={handleBrightnessChange}
          />
        ))}
      </div>

      {/* Footer */}
      <footer className="text-center mt-12 py-6 text-slate-500 text-sm">
        ESP32 @ {esp32Host || '192.168.0.44'} • {lights.length} Lights •
        GPIO {lights.map(l => l.pin).join(', ')}
      </footer>

      {/* Toast */}
      <div
        className={`
          fixed bottom-8 right-8 bg-slate-800 border border-slate-700 text-white px-6 py-3 rounded-2xl text-sm
          transition-all duration-300
          ${toast ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-5 pointer-events-none'}
        `}
      >
        {toast}
      </div>
    </div>
  );
}
