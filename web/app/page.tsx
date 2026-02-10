'use client';

import { HealthMonitor } from '@/components/health-monitor';
import { CameraControl } from '@/components/camera-control';
import { CapturePanel } from '@/components/capture-panel';
import { StreamViewer } from '@/components/stream-viewer';
import { CameraSettings } from '@/components/camera-settings';
import { Camera, Images, Lightbulb, Layers } from 'lucide-react';
import Link from 'next/link';

export default function Home() {
  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Camera className="w-8 h-8 text-blue-500" />
              <div>
                <h1 className="text-2xl font-bold text-gray-900">
                  Camera Control
                </h1>
                <p className="text-sm text-gray-500">
                  Sony A7R III via gphoto2
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Link
                href="/batch"
                className="flex items-center gap-2 px-4 py-2 bg-purple-500 text-white rounded-lg hover:bg-purple-600 transition-colors"
              >
                <Layers className="w-5 h-5" />
                <span>Batch</span>
              </Link>
              <Link
                href="/lights"
                className="flex items-center gap-2 px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors"
              >
                <Lightbulb className="w-5 h-5" />
                <span>Lights</span>
              </Link>
              <Link
                href="/gallery"
                className="flex items-center gap-2 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
              >
                <Images className="w-5 h-5" />
                <span>Gallery</span>
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
          {/* Left Column - Capture */}
          <div className="space-y-6">
            <CapturePanel />
          </div>

          {/* Middle + Right Column - Stream & Settings */}
          <div className="lg:col-span-2 space-y-6">
            <StreamViewer />
            <CameraSettings />
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="bg-white border-t mt-12">
        <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8">
          <p className="text-center text-sm text-gray-500">
            Camera Control API - FastAPI + Next.js
          </p>
        </div>
      </footer>
    </div>
  );
}
