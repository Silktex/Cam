'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import { useLightsWebSocket } from '@/hooks/useLightsWebSocket';

const DashboardHeader = dynamic(() => import('./components/DashboardHeader'), {
  ssr: false,
});
const CaptureForm = dynamic(() => import('./components/CaptureForm'), {
  ssr: false,
});
const BatchCaptureForm = dynamic(() => import('./components/BatchCaptureForm'), {
  ssr: false,
});
const ColorCheckerForm = dynamic(
  () => import('./components/ColorCheckerForm'),
  { ssr: false }
);
const LightControlPanel = dynamic(
  () => import('./components/LightControlPanel'),
  { ssr: false }
);
const LiveViewPanel = dynamic(() => import('./components/LiveViewPanel'), {
  ssr: false,
});
const CompactCameraSettings = dynamic(
  () => import('./components/CompactCameraSettings'),
  { ssr: false }
);

type Tab = 'single' | 'color' | 'batch';

export default function AllPage() {
  const [activeTab, setActiveTab] = useState<Tab>('single');
  const {
    lights,
    connected,
    wsConnected,
    setLight,
    setAllLights,
    requestState,
  } = useLightsWebSocket();

  const tabs: { key: Tab; label: string }[] = [
    { key: 'single', label: 'Single' },
    { key: 'color', label: 'Color' },
    { key: 'batch', label: 'Batch' },
  ];

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
        <LiveViewPanel />
        <CompactCameraSettings />
      </div>
    </div>
  );
}
