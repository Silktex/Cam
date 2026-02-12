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

// Batches / Processing
export const syncAllBatches = () => api.post('/api/batches/sync');
export const syncBatch = (name: string) => api.post(`/api/batches/sync/${name}`);
export const getBatches = () => api.get('/api/batches/');
export const getBatchesSummary = () => api.get('/api/batches/summary');
export const getBatch = (name: string) => api.get(`/api/batches/${name}`);
export const getBatchImages = (name: string) => api.get(`/api/batches/${name}/images`);
export const getBatchesByStatus = (phase: string, status: string) =>
  api.get(`/api/batches/status/${phase}/${status}`);
export const updateBatchCrop = (name: string, status: string, cropType?: string) =>
  api.put(`/api/batches/${name}/crop`, { status, crop_type: cropType });
export const updateBatchCalibration = (name: string, status: string) =>
  api.put(`/api/batches/${name}/calibration`, { status });
export const updateBatchPBR = (name: string, status: string, pbrMode?: string) =>
  api.put(`/api/batches/${name}/pbr`, { status, pbr_mode: pbrMode });
export const updatePBRSelection = (name: string, filename: string, selected: boolean) =>
  api.put(`/api/batches/${name}/pbr-selection`, { filename, selected });
export const getSettings = () => api.get('/api/batches/settings');
export const updateMediaPath = (path: string) =>
  api.put('/api/batches/settings/media-path', { path });

// Batch Types
export interface BatchSummary {
  total_batches: number;
  crop: { pending: number; in_progress: number; completed: number };
  calibration: { pending: number; in_progress: number; completed: number };
  pbr: { pending: number; in_progress: number; completed: number };
}

export interface Batch {
  id: number;
  name: string;
  folder_path: string;
  created_at: string;
  image_count: number;
  crop_status: 'pending' | 'in_progress' | 'completed';
  crop_type: 'manual' | 'auto' | null;
  crop_completed_at: string | null;
  calibration_status: 'pending' | 'in_progress' | 'completed';
  calibration_completed_at: string | null;
  pbr_status: 'pending' | 'in_progress' | 'completed';
  pbr_mode: 'grayscale' | 'colored' | 'both' | null;
  pbr_completed_at: string | null;
  synced_at: string;
  notes: string | null;
}

export interface BatchImage {
  id: number;
  batch_id: number;
  filename: string;
  position: string;
  camera: string;
  lens: string;
  resolution_w: number;
  resolution_h: number;
  iso: number;
  aperture: string;
  shutter: string;
  focal_length: string;
  captured_at: string;
  file_size: number;
  is_cropped: number;
  is_calibrated: number;
  pbr_selected: number;
  pbr_grayscale_done: number;
  pbr_colored_done: number;
}
