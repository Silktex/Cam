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
      <div className="bg-white rounded-lg shadow p-4">
        <div className="animate-pulse flex items-center gap-3">
          <div className="w-12 h-12 bg-gray-200 rounded-full" />
          <div className="flex-1">
            <div className="h-4 bg-gray-200 rounded w-24 mb-2" />
            <div className="h-3 bg-gray-200 rounded w-32" />
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center">
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
  let statusColor = 'gray';
  let statusText = 'No Camera';
  let StatusIcon = XCircle;

  if (isConnected) {
    statusColor = 'green';
    statusText = 'Connected';
    StatusIcon = CheckCircle;
  } else if (isDetected) {
    statusColor = 'yellow';
    statusText = 'Detected';
    StatusIcon = AlertCircle;
  }

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex items-center gap-3">
        <div className={`w-12 h-12 rounded-full flex items-center justify-center ${
          statusColor === 'green' ? 'bg-green-100' : statusColor === 'yellow' ? 'bg-yellow-100' : 'bg-gray-100'
        }`}>
          <Camera className={`w-6 h-6 ${
            statusColor === 'green' ? 'text-green-600' : statusColor === 'yellow' ? 'text-yellow-600' : 'text-gray-600'
          }`} />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-gray-900">
              {model || 'Camera'}
            </span>
            <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-xs ${
              statusColor === 'green' ? 'bg-green-100 text-green-700' : 
              statusColor === 'yellow' ? 'bg-yellow-100 text-yellow-700' : 
              'bg-gray-100 text-gray-700'
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
