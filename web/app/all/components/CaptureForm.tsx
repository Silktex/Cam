'use client';

import { useState, useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  captureImages,
  getCameraStatus,
  type CaptureRequest,
  type CaptureResponse,
  type CameraStatus,
} from '@/lib/api';
import {
  Camera,
  FolderOpen,
  Download,
  Loader2,
  CheckCircle,
  XCircle,
  Clock,
} from 'lucide-react';

export default function CaptureForm() {
  const queryClient = useQueryClient();
  const [folder, setFolder] = useState('session_1');
  const [prefix, setPrefix] = useState('capture');
  const [count, setCount] = useState(1);
  const [lastCapture, setLastCapture] = useState<CaptureResponse | null>(null);
  const [cooldown, setCooldown] = useState(0);

  const { data: cameraStatus } = useQuery({
    queryKey: ['camera', 'status'],
    queryFn: () => getCameraStatus().then((res) => res.data as CameraStatus),
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
    mutationFn: (request: CaptureRequest) =>
      captureImages(request).then((res) => res.data as CaptureResponse),
    onSuccess: (response) => {
      setLastCapture(response);
      queryClient.invalidateQueries({ queryKey: ['captures'] });
      queryClient.invalidateQueries({ queryKey: ['camera'] });
      setCooldown(3);
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
        message:
          error.response?.data?.detail || error.message || 'Capture failed',
      });
      queryClient.invalidateQueries({ queryKey: ['camera'] });
      setCooldown(5);
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent('restartStream'));
      }, 3000);
    },
  });

  const handleCapture = () => {
    if (!isConnected || cooldown > 0) return;
    captureMutation.mutate({ folder, prefix, count });
  };

  const isCapturing = captureMutation.isPending;
  const isDisabled = isCapturing || !folder || !isConnected || cooldown > 0;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 relative">
      {/* Capturing overlay */}
      {isCapturing && (
        <div className="absolute inset-0 bg-slate-900/80 backdrop-blur-sm rounded-2xl flex items-center justify-center z-10">
          <div className="flex flex-col items-center gap-2">
            <Loader2 className="w-8 h-8 animate-spin text-teal-400" />
            <span className="text-sm font-medium text-white">
              Capturing image...
            </span>
          </div>
        </div>
      )}

      <div className="flex items-center gap-2 mb-4">
        <Camera className="w-5 h-5 text-teal-400" />
        <h2 className="text-base font-semibold text-white">Image Capture</h2>
      </div>

      <div className="space-y-3">
        {/* Folder */}
        <div>
          <label className="block text-sm text-slate-400 mb-1">
            <FolderOpen className="w-3.5 h-3.5 inline mr-1" />
            Folder Name
          </label>
          <input
            type="text"
            value={folder}
            onChange={(e) => setFolder(e.target.value)}
            placeholder="session_1"
            disabled={isCapturing}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 text-sm focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none disabled:opacity-50"
          />
          <p className="text-xs text-slate-500 mt-1">
            Saves to: media/captures/{folder}/
          </p>
        </div>

        {/* Prefix */}
        <div>
          <label className="block text-sm text-slate-400 mb-1">
            Filename Prefix
          </label>
          <input
            type="text"
            value={prefix}
            onChange={(e) => setPrefix(e.target.value)}
            placeholder="capture"
            disabled={isCapturing}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 text-sm focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none disabled:opacity-50"
          />
        </div>

        {/* Count */}
        <div>
          <label className="block text-sm text-slate-400 mb-1">Count</label>
          <input
            type="number"
            value={count}
            onChange={(e) =>
              setCount(Math.max(1, Math.min(100, parseInt(e.target.value) || 1)))
            }
            min={1}
            max={100}
            disabled={isCapturing}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none disabled:opacity-50"
          />
        </div>

        {/* Capture Button */}
        <button
          onClick={handleCapture}
          disabled={isDisabled}
          className={`w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl font-medium transition-colors ${
            !isConnected
              ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
              : cooldown > 0
                ? 'bg-yellow-500/20 text-yellow-400 cursor-wait'
                : isCapturing
                  ? 'bg-teal-500/30 text-teal-300 cursor-wait'
                  : 'bg-teal-600 text-white hover:bg-teal-500'
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
          <div
            className={`p-3 rounded-xl ${
              lastCapture.success
                ? 'bg-teal-500/10 border border-teal-500/30'
                : 'bg-red-500/10 border border-red-500/30'
            }`}
          >
            <div className="flex items-center gap-2 mb-1">
              {lastCapture.success ? (
                <CheckCircle className="w-4 h-4 text-teal-400" />
              ) : (
                <XCircle className="w-4 h-4 text-red-400" />
              )}
              <span
                className={`text-sm font-medium ${
                  lastCapture.success ? 'text-teal-300' : 'text-red-300'
                }`}
              >
                {lastCapture.message}
              </span>
            </div>
            {lastCapture.success && lastCapture.files.length > 0 && (
              <div className="text-xs text-slate-400 space-y-0.5 mt-1">
                {lastCapture.files
                  .filter((f) => f.success)
                  .map((file, i) => (
                    <div key={i} className="truncate">
                      {file.filename}
                      {file.file_size && (
                        <span className="text-slate-500 ml-1">
                          ({(file.file_size / 1024 / 1024).toFixed(1)} MB)
                        </span>
                      )}
                    </div>
                  ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
