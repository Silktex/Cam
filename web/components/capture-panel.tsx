'use client';

import { useState, useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { captureImages, getCameraStatus, type CaptureRequest, type CaptureResponse, type CameraStatus } from '@/lib/api';
import { Camera, FolderOpen, Download, Loader2, CheckCircle, XCircle, Image, Clock } from 'lucide-react';
import Link from 'next/link';

export function CapturePanel() {
  const queryClient = useQueryClient();
  const [folder, setFolder] = useState('session_1');
  const [prefix, setPrefix] = useState('capture');
  const [count, setCount] = useState(1);
  const [lastCapture, setLastCapture] = useState<CaptureResponse | null>(null);
  const [cooldown, setCooldown] = useState(0); // Cooldown in seconds

  const { data: cameraStatus } = useQuery({
    queryKey: ['camera', 'status'],
    queryFn: () => getCameraStatus().then(res => res.data as CameraStatus),
    refetchInterval: 10000,
  });

  const isConnected = cameraStatus?.connected ?? false;

  // Cooldown timer
  useEffect(() => {
    if (cooldown > 0) {
      const timer = setTimeout(() => setCooldown(cooldown - 1), 1000);
      return () => clearTimeout(timer);
    }
  }, [cooldown]);

  const captureMutation = useMutation({
    mutationFn: (request: CaptureRequest) => captureImages(request).then(res => res.data as CaptureResponse),
    onSuccess: (response) => {
      setLastCapture(response);
      queryClient.invalidateQueries({ queryKey: ['captures'] });
      queryClient.invalidateQueries({ queryKey: ['camera'] });
      // 3 second cooldown after successful capture
      setCooldown(3);
      // Dispatch event to restart stream after cooldown
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent('restartStream'));
      }, 1500);
    },
    onError: (error: any) => {
      setLastCapture({
        success: false,
        captured_count: 0,
        total_requested: count,
        files: [],
        folder: folder,
        message: error.response?.data?.detail || error.message || 'Capture failed'
      });
      queryClient.invalidateQueries({ queryKey: ['camera'] });
      // 5 second cooldown after failed capture (camera needs recovery time)
      setCooldown(5);
      // Dispatch event to restart stream after longer delay
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent('restartStream'));
      }, 3000);
    }
  });

  const handleCapture = () => {
    if (!isConnected || cooldown > 0) return;
    captureMutation.mutate({
      folder,
      prefix,
      count,
    });
  };

  const isCapturing = captureMutation.isPending;
  const isDisabled = isCapturing || !folder || !isConnected || cooldown > 0;

  return (
    <div className="bg-white rounded-lg shadow p-4 relative">
      {/* Capturing overlay */}
      {isCapturing && (
        <div className="absolute inset-0 bg-white/80 backdrop-blur-sm rounded-lg flex items-center justify-center z-10">
          <div className="flex flex-col items-center gap-2">
            <Loader2 className="w-8 h-8 animate-spin text-green-500" />
            <span className="text-sm font-medium text-gray-700">Capturing image...</span>
            <span className="text-xs text-gray-500">Please wait</span>
          </div>
        </div>
      )}

      <div className="flex items-center gap-2 mb-4">
        <Camera className="w-5 h-5 text-gray-700" />
        <h2 className="text-lg font-semibold text-gray-900">Image Capture</h2>
      </div>

      <div className="space-y-4">
        {/* Folder Input */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            <FolderOpen className="w-4 h-4 inline mr-1" />
            Folder Name
          </label>
          <input
            type="text"
            value={folder}
            onChange={(e) => setFolder(e.target.value)}
            placeholder="session_1"
            disabled={isCapturing}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm disabled:bg-gray-100 disabled:cursor-not-allowed"
          />
          <p className="text-xs text-gray-500 mt-1">Saves to: media/captures/{folder}/</p>
        </div>

        {/* Prefix Input */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Filename Prefix
          </label>
          <input
            type="text"
            value={prefix}
            onChange={(e) => setPrefix(e.target.value)}
            placeholder="capture"
            disabled={isCapturing}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm disabled:bg-gray-100 disabled:cursor-not-allowed"
          />
        </div>

        {/* Count */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Count
          </label>
          <input
            type="number"
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(100, parseInt(e.target.value) || 1)))}
            min={1}
            max={100}
            disabled={isCapturing}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm disabled:bg-gray-100 disabled:cursor-not-allowed"
          />
        </div>

        {/* Capture Button */}
        <button
          onClick={handleCapture}
          disabled={isDisabled}
          className={`w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg font-medium transition-colors ${
            !isConnected 
              ? 'bg-gray-200 text-gray-500 cursor-not-allowed'
              : cooldown > 0
                ? 'bg-yellow-100 text-yellow-700 cursor-wait'
                : isCapturing
                  ? 'bg-green-300 text-white cursor-wait'
                  : 'bg-green-500 text-white hover:bg-green-600'
          }`}
        >
          {isCapturing ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              Capturing...
            </>
          ) : cooldown > 0 ? (
            <>
              <Clock className="w-5 h-5" />
              Wait {cooldown}s...
            </>
          ) : !isConnected ? (
            <>
              <Camera className="w-5 h-5" />
              Connect Camera First
            </>
          ) : (
            <>
              <Download className="w-5 h-5" />
              Capture {count > 1 ? `${count} Images` : 'Image'}
            </>
          )}
        </button>

        {/* Last Capture Result */}
        {lastCapture && (
          <div className={`p-3 rounded-lg ${lastCapture.success ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}`}>
            <div className="flex items-center gap-2 mb-2">
              {lastCapture.success ? (
                <CheckCircle className="w-4 h-4 text-green-600" />
              ) : (
                <XCircle className="w-4 h-4 text-red-600" />
              )}
              <span className={`text-sm font-medium ${lastCapture.success ? 'text-green-700' : 'text-red-700'}`}>
                {lastCapture.message}
              </span>
            </div>
            
            {lastCapture.success && lastCapture.files.length > 0 && (
              <div className="text-xs text-gray-600 space-y-1 max-h-32 overflow-y-auto">
                {lastCapture.files.filter(f => f.success).map((file, i) => (
                  <div key={i} className="flex items-center gap-1">
                    <Image className="w-3 h-3" />
                    <span className="truncate">{file.filename}</span>
                    {file.file_size && (
                      <span className="text-gray-400">
                        ({(file.file_size / 1024 / 1024).toFixed(1)} MB)
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
            
            {lastCapture.success && (
              <Link
                href="/gallery"
                className="inline-flex items-center gap-1 mt-2 text-xs text-blue-600 hover:text-blue-800"
              >
                <Image className="w-3 h-3" />
                View in Gallery
              </Link>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
