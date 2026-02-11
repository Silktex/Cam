'use client';

import { useQuery } from '@tanstack/react-query';
import { getCameraStatus, type CameraStatus } from '@/lib/api';
import { useWebSocket } from '@/app/providers';
import { Camera, CheckCircle, XCircle, Wifi, WifiOff, AlertCircle } from 'lucide-react';

export function HealthMonitor() {
  const { status: wsStatus } = useWebSocket();
  const wsConnected = wsStatus === 'connected';

  // Use same query as CameraControl for consistency
  const { data, isLoading, error } = useQuery({
    queryKey: ['camera', 'status'],
    queryFn: () => getCameraStatus().then(res => res.data as CameraStatus),
    refetchInterval: 5000, // Poll every 5s
    retry: 2,
  });

  if (isLoading) {
    return (
      <div className="bg-white border border-slate-200 rounded-2xl p-4">
        <div className="animate-pulse flex items-center gap-3">
          <div className="w-12 h-12 bg-slate-100 rounded-xl" />
          <div className="flex-1">
            <div className="h-4 bg-slate-100 rounded w-24 mb-2" />
            <div className="h-3 bg-slate-100 rounded w-32" />
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-2xl p-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-red-100 rounded-xl flex items-center justify-center">
            <XCircle className="w-6 h-6 text-red-500" />
          </div>
          <div>
            <div className="font-medium text-red-700">API Offline</div>
            <div className="text-sm text-red-600">Backend not running</div>
          </div>
        </div>
      </div>
    );
  }

  const isConnected = data?.connected ?? false;
  const isDetected = data?.detected ?? false;
  const model = data?.model;

  // Determine status
  let statusColor = 'slate';
  let statusText = 'No Camera';
  let StatusIcon = XCircle;

  if (isConnected) {
    statusColor = 'teal';
    statusText = 'Connected';
    StatusIcon = CheckCircle;
  } else if (isDetected) {
    statusColor = 'yellow';
    statusText = 'Detected';
    StatusIcon = AlertCircle;
  }

  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-4">
      <div className="flex items-center gap-3">
        <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
          statusColor === 'teal' ? 'bg-teal-100' : statusColor === 'yellow' ? 'bg-yellow-100' : 'bg-slate-100'
        }`}>
          <Camera className={`w-6 h-6 ${
            statusColor === 'teal' ? 'text-teal-600' : statusColor === 'yellow' ? 'text-yellow-600' : 'text-slate-600'
          }`} />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-800">
              {model || 'Camera'}
            </span>
            <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-xs ${
              statusColor === 'teal' ? 'bg-teal-100 text-teal-700' :
              statusColor === 'yellow' ? 'bg-yellow-100 text-yellow-700' :
              'bg-slate-100 text-slate-700'
            }`}>
              <StatusIcon className="w-3 h-3" />
              {statusText}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
