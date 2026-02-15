import axios from 'axios';

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Convert relative URL to full backend URL
export const getFullUrl = (path: string) => {
  if (path.startsWith('data:') || path.startsWith('http')) return path;
  return `${API_BASE_URL}${path}`;
};

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
export const deleteFile = (filePath: string) =>
  api.delete(`/api/capture/files/${filePath}`);
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

// Processing API - Interactive Crop Workflow
export const getTopImageForCrop = (batchName: string) =>
  api.get(`/api/processing/crop/top-image/${batchName}`);

export const autoDetectCrop = (batchName: string, cropSize: number = 2048) =>
  api.post('/api/processing/crop/auto-detect', { batch_name: batchName, crop_size: cropSize });

export const previewManualCrop = (batchName: string, bbox: number[]) =>
  api.post('/api/processing/crop/preview-manual', { batch_name: batchName, bbox });

export interface CropPoint {
  x: number;
  y: number;
}

export const applyCrop = (
  batchName: string,
  cropType: 'manual' | 'auto',
  options: {
    bbox?: number[];
    points?: CropPoint[];
    rotation?: number;
  }
) =>
  api.post('/api/processing/crop/apply', {
    batch_name: batchName,
    crop_type: cropType,
    bbox: options.bbox,
    points: options.points,
    rotation: options.rotation || 0,
  });

// Legacy crop endpoints (backward compatibility)
export const manualCrop = (batchName: string, bbox: number[], applyToAll: boolean = true) =>
  api.post('/api/processing/crop/manual', {
    batch_name: batchName,
    bbox,
    apply_to_all: applyToAll,
  });

export const autoCrop = (batchName: string, prompt: string = 'fabric sample') =>
  api.post('/api/processing/crop/auto', {
    batch_name: batchName,
    prompt,
  });

export const getCropPreview = (batchName: string) =>
  api.get(`/api/processing/crop/preview/${batchName}`);

export const detectColorChecker = (imagePath: string, saveProfile: boolean = false, profileName?: string) =>
  api.post('/api/processing/colorchecker/detect', {
    image_path: imagePath,
    save_profile: saveProfile,
    profile_name: profileName,
  });

export const getColorCheckerProfiles = () =>
  api.get('/api/processing/colorchecker/profiles');

export const calibrateBatch = (batchName: string, profileName?: string, colorcheckerImage?: string) =>
  api.post('/api/processing/calibrate', {
    batch_name: batchName,
    profile_name: profileName,
    colorchecker_image: colorcheckerImage,
  });

export const getCalibrationPreview = (batchName: string) =>
  api.get(`/api/processing/calibrate/preview/${batchName}`);

export const generatePBR = (
  batchName: string,
  mode: 'grayscale' | 'colored' | 'both' = 'grayscale',
  selectedImages?: string[]
) =>
  api.post('/api/processing/pbr', {
    batch_name: batchName,
    mode,
    selected_images: selectedImages,
  });

export const getPBRPreview = (batchName: string) =>
  api.get(`/api/processing/pbr/preview/${batchName}`);

export const getProcessingStatus = (batchName: string) =>
  api.get(`/api/processing/status/${batchName}`);

// TIFF Re-conversion
export const reconvertTiff = (path: string, checkerRawPath?: string) =>
  api.post('/api/processing/reconvert-tiff', {
    path,
    ...(checkerRawPath ? { checker_raw_path: checkerRawPath } : {}),
  });

// ColorChecker API - Detection and Calibration Workflow
export const getAvailableCheckerImages = () =>
  api.get('/api/colorchecker/available-images');

export const getBatchesWithRaw = () =>
  api.get('/api/colorchecker/batches-with-raw');

export const captureColorChecker = () =>
  api.post('/api/colorchecker/capture');

export const uploadColorChecker = (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post('/api/colorchecker/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};

export const detectColorCheckerSwatches = (imagePath: string, wbSourceBatch?: string) =>
  api.post('/api/colorchecker/detect', {
    image_path: imagePath,
    ...(wbSourceBatch ? { wb_source_batch: wbSourceBatch } : {}),
  });

export const flipColorChecker = (detectionId: string, axis: string) =>
  api.post('/api/colorchecker/flip', { detection_id: detectionId, axis });

export const rotateColorChecker = (detectionId: string, degrees: number) =>
  api.post('/api/colorchecker/rotate', { detection_id: detectionId, degrees });

export const getColorCheckerOverlay = (detectionId: string) =>
  `${API_BASE_URL}/api/colorchecker/overlay/${detectionId}`;

export const saveColorCheckerProfile = (detectionId: string, profileName: string) =>
  api.post('/api/colorchecker/save', { detection_id: detectionId, profile_name: profileName });

export const listColorCheckerProfiles = () =>
  api.get('/api/colorchecker/profiles');

export const getColorCheckerProfile = (name: string) =>
  api.get(`/api/colorchecker/profiles/${name}`);

export const deleteColorCheckerProfile = (name: string) =>
  api.delete(`/api/colorchecker/profiles/${name}`);

export const getReferenceSwatches = () =>
  api.get('/api/colorchecker/reference-swatches');

export const getDetectedSwatches = (detectionId: string) =>
  api.get(`/api/colorchecker/detected-swatches/${detectionId}`);

// Calibration page API
export const getColorCheckerImageForBatch = (batchName: string) =>
  api.get(`/api/processing/colorchecker/batch-image/${batchName}`);

export const applyCalibrationToBatch = (batchName: string, profileName: string) =>
  api.post('/api/processing/calibrate/apply', {
    batch_name: batchName,
    profile_name: profileName,
  });

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
