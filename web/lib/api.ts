import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Health
export const getHealth = () => api.get('/health');

// Camera
export const getCameraStatus = () => api.get('/api/camera/status');
export const connectCamera = () => api.post('/api/camera/connect');
export const disconnectCamera = () => api.post('/api/camera/disconnect');
export const troubleshootCamera = () => api.post('/api/camera/troubleshoot');
export const getCameraSettings = () => api.get('/api/camera/settings');
export const setCameraSetting = (name: string, value: any) => 
  api.post('/api/camera/settings', { name, value });

// Capture
export const captureImages = (request: CaptureRequest) =>
  api.post('/api/capture/', request);
export const getCaptureFolders = () => api.get('/api/capture/folders');
export const getFolderContents = (folder: string) =>
  api.get(`/api/capture/folders/${folder}`);
export const deleteFolder = (folder: string) =>
  api.delete(`/api/capture/folders/${folder}`);
export const browsePath = (path: string = "") =>
  api.get(`/api/capture/browse/${path}`);
export const getMediaUrl = (path: string) => `${API_BASE_URL}/media/captures/${path}`;

// Live View
export const getLiveViewStatus = () => api.get('/api/liveview/status');
export const stopLiveView = () => api.post('/api/liveview/stop');
export const getLiveViewUrl = () => `${API_BASE_URL}/api/liveview/stream`;

// Types
export interface HealthResponse {
  status: string;
  services: {
    api_server: boolean;
    camera_detected: boolean;
    camera_connected: boolean;
    live_view_available: boolean;
  };
  camera: {
    connected: boolean;
    detected: boolean;
    model?: string;
  };
}

export interface CameraStatus {
  connected: boolean;
  detected: boolean;
  model?: string;
  error?: string;
}

export interface TroubleshootResult {
  success: boolean;
  killed_processes: string[];
  camera_detected: boolean;
  message: string;
}

export interface CameraSetting {
  name: string;
  label: string;
  value: any;
  type: string;
  readonly: boolean;
  choices?: string[];
  range?: { min: number; max: number; step: number };
}

export interface CaptureRequest {
  folder: string;
  prefix?: string;
  count?: number;
}

export interface CaptureResult {
  success: boolean;
  filename?: string;
  filepath?: string;
  file_url?: string;
  file_size?: number;
  error?: string;
  captured_at?: string;
}

export interface CaptureResponse {
  success: boolean;
  captured_count: number;
  total_requested: number;
  folder: string;
  files: CaptureResult[];
  message: string;
}

export interface FolderInfo {
  name: string;
  path: string;
  file_count: number;
  total_size: number;
}
