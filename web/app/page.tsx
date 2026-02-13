'use client';

import { useState } from 'react';
import { HealthMonitor } from '@/components/health-monitor';
import { CameraControl } from '@/components/camera-control';
import { CapturePanel } from '@/components/capture-panel';
import { ColorCheckerPanel } from '@/components/color-checker-panel';
import { StreamViewer } from '@/components/stream-viewer';
import { CameraSettings } from '@/components/camera-settings';
import { Camera, Images, Lightbulb, Layers, Workflow, Palette } from 'lucide-react';
import Link from 'next/link';

export default function Home() {
  const [activeTab, setActiveTab] = useState<'capture' | 'colorchecker'>('capture');

  return (
    <div className="min-h-screen bg-cloud">
      {/* Header */}
      <header className="bg-white border-b border-slate-200/60">
        <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Camera className="w-8 h-8 text-teal-600" />
              <div>
                <h1 className="text-2xl font-semibold text-slate-800">
                  Camera Control
                </h1>
                <p className="text-sm text-slate-500">
                  Sony A7R III via gphoto2
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Link
                href="/batch"
                className="flex items-center gap-2 px-4 py-2 bg-slate-100 text-slate-700 rounded-2xl hover:bg-slate-200 transition-colors"
              >
                <Layers className="w-5 h-5" />
                <span>Batch</span>
              </Link>
              <Link
                href="/lights"
                className="flex items-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-2xl hover:bg-teal-700 transition-colors shadow-teal-glow"
              >
                <Lightbulb className="w-5 h-5" />
                <span>Lights</span>
              </Link>
              <Link
                href="/gallery"
                className="flex items-center gap-2 px-4 py-2 bg-slate-100 text-slate-700 rounded-2xl hover:bg-slate-200 transition-colors"
              >
                <Images className="w-5 h-5" />
                <span>Gallery</span>
              </Link>
              <Link
                href="/processing"
                className="flex items-center gap-2 px-4 py-2 bg-violet-600 text-white rounded-2xl hover:bg-violet-700 transition-colors"
              >
                <Workflow className="w-5 h-5" />
                <span>Processing</span>
              </Link>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        {/* Status Bar - Camera + Controls */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <HealthMonitor />
          <CameraControl />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column - Capture / Color Checker */}
          <div className="space-y-4">
            {/* Tabs */}
            <div className="flex bg-slate-100 rounded-xl p-1">
              <button
                onClick={() => setActiveTab('capture')}
                className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  activeTab === 'capture'
                    ? 'bg-white text-slate-800 shadow-sm'
                    : 'text-slate-600 hover:text-slate-800'
                }`}
              >
                <Camera className="w-4 h-4" />
                Capture
              </button>
              <button
                onClick={() => setActiveTab('colorchecker')}
                className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  activeTab === 'colorchecker'
                    ? 'bg-white text-slate-800 shadow-sm'
                    : 'text-slate-600 hover:text-slate-800'
                }`}
              >
                <Palette className="w-4 h-4" />
                Color Checker
              </button>
            </div>

            {/* Panel Content */}
            {activeTab === 'capture' ? <CapturePanel /> : <ColorCheckerPanel />}
          </div>

          {/* Middle + Right Column - Stream & Settings */}
          <div className="lg:col-span-2 space-y-6">
            <StreamViewer />
            <CameraSettings />
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-slate-200/60 mt-12">
        <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8">
          <p className="text-center text-sm text-slate-500">
            Camera Control API - FastAPI + Next.js
          </p>
        </div>
      </footer>
    </div>
  );
}
