'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import dynamic from 'next/dynamic';
import { useLightsWebSocket } from '@/hooks/useLightsWebSocket';
import { stopLiveView } from '@/lib/api';

const DashboardHeader = dynamic(() => import('./all/components/DashboardHeader'), {
  ssr: false,
});
const CaptureForm = dynamic(() => import('./all/components/CaptureForm'), {
  ssr: false,
});
const BatchCaptureForm = dynamic(() => import('./all/components/BatchCaptureForm'), {
  ssr: false,
});
const ColorCheckerForm = dynamic(
  () => import('./all/components/ColorCheckerForm'),
  { ssr: false }
);
const LightControlPanel = dynamic(
  () => import('./all/components/LightControlPanel'),
  { ssr: false }
);
const LiveViewPanel = dynamic(() => import('./all/components/LiveViewPanel'), {
  ssr: false,
});
const CompactCameraSettings = dynamic(
  () => import('./all/components/CompactCameraSettings'),
  { ssr: false }
);

type Tab = 'single' | 'color' | 'batch';

export default function Home() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<Tab>('batch');
  const [showLiveView, setShowLiveView] = useState(true);
  const {
    lights,
    connected,
    wsConnected,
    setLight,
    setAllLights,
    requestState,
  } = useLightsWebSocket();

  const tabs: { key: Tab; label: string }[] = [
    { key: 'batch', label: 'Batch' },
    { key: 'single', label: 'Single' },
    { key: 'color', label: 'Color' },
  ];

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Skip if user is typing in an input/textarea/select
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      // Let Cmd/Ctrl shortcuts pass through (e.g. Cmd+S for capture)
      if (e.metaKey || e.ctrlKey) return;

      switch (e.key) {
        case ' ':
          e.preventDefault();
          // Toggle all lights: if any are on, turn all off; otherwise turn all on
          const anyOn = lights.some((l) => l.on);
          setAllLights(!anyOn);
          break;
        case 't':
        case 'T': {
          // Top Light = lights[0]
          const topLight = lights[0];
          if (topLight) setLight(topLight.id, !topLight.on);
          break;
        }
        case '1': case '2': case '3': case '4':
        case '5': case '6': case '7': case '8': {
          // Side N Light = lights[N] (key '1' → lights[1], etc.)
          const idx = parseInt(e.key);
          const light = lights[idx];
          if (light) setLight(light.id, !light.on);
          break;
        }
        case 's':
          setActiveTab('single');
          break;
        case 'b':
          setActiveTab('batch');
          break;
        case 'c':
          setActiveTab('color');
          break;
        case 'f':
          // Focus folder name input in batch capture form
          window.dispatchEvent(new Event('focusFolderInput'));
          break;
        case 'l':
          setShowLiveView((prev) => {
            if (prev) {
              // Switching away from live view — stop the stream
              stopLiveView().catch(() => {});
            }
            return !prev;
          });
          break;
        case 'p':
          router.push('/processing');
          break;
        case 'g':
          router.push('/gallery');
          break;
        case 'd':
          router.push('/');
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [lights, setLight, setAllLights, router]);

  return (
    <div className="h-screen w-screen bg-slate-950 text-white grid grid-cols-[460px_1fr] grid-rows-[auto_1fr] overflow-hidden">
      {/* Header — spans full width */}
      <div className="col-span-2">
        <DashboardHeader />
      </div>

      {/* Left sidebar */}
      <div className="overflow-y-auto border-r border-slate-800 p-4 space-y-4">
        {/* Tab bar */}
        <div className="flex bg-slate-900 rounded-xl p-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-1 py-2 text-sm font-medium rounded-lg transition-colors ${
                activeTab === tab.key
                  ? 'bg-teal-600 text-white'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === 'single' && <CaptureForm />}
        {activeTab === 'color' && <ColorCheckerForm />}
        {activeTab === 'batch' && <BatchCaptureForm />}

        {/* Divider */}
        <div className="border-t border-slate-800" />

        {/* Light Control — always visible */}
        <LightControlPanel
          lights={lights}
          connected={connected}
          wsConnected={wsConnected}
          setLight={setLight}
          setAllLights={setAllLights}
          requestState={requestState}
        />
      </div>

      {/* Right content */}
      <div className="overflow-y-auto p-4 space-y-4">
        <div className={showLiveView ? '' : 'hidden'}>
          <LiveViewPanel />
        </div>
        {!showLiveView && <CompactCameraSettings />}
      </div>
    </div>
  );
}
