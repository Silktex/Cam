import axios from 'axios';
import { getApiBaseUrl } from './urlHelpers';

export const API_BASE_URL = getApiBaseUrl();

interface RequestIdError extends Error {
  requestId?: string;
}

// Convert relative URL to full backend URL
export const getFullUrl = (path: string) => {
  if (!path) return '';
  if (path.startsWith('data:') || path.startsWith('http')) return path;
  const base = getApiBaseUrl();
  return base ? `${base}${path.startsWith('/') ? '' : '/'}${path}` : path;
};

export const api = axios.create({
  baseURL: getApiBaseUrl(),
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const dynamicBase = getApiBaseUrl();
  if (dynamicBase && !config.url?.startsWith('http://') && !config.url?.startsWith('https://')) {
    config.baseURL = dynamicBase;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.headers) {
      const requestId = error.response.headers['x-request-id'];
      if (typeof requestId === 'string') {
        (error as RequestIdError).requestId = requestId;
      }
    }
    return Promise.reject(error);
  }
);

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
export const triggerAutofocus = () => api.post('/api/camera/autofocus');

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

// Helper to resolve media URLs
export const getMediaUrl = (url: string | null | undefined): string => {
  if (!url) return '';
  if (url.startsWith('http://') || url.startsWith('https://') || url.startsWith('data:')) return url;
  const base = getApiBaseUrl();
  return `${base}${url.startsWith('/') ? '' : '/'}${url}`;
};

// Live View & Video Capture Card
export const getLiveViewStatus = () => api.get('/api/liveview/status');
export const setLiveViewSource = (source: 'hdmi' | 'ptp') =>
  api.post('/api/liveview/source', { source });
export const getLiveViewCapabilities = () => api.get('/api/liveview/capabilities');
export const getVideoDevices = () => api.get('/api/devices/video');
export const stopLiveView = () => api.post('/api/liveview/stop');
export const getLiveViewUrl = () => `${getApiBaseUrl()}/api/liveview/stream`;
export const getWhepStreamUrl = () => `${getApiBaseUrl()}/stream/whep`;

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

export interface LiveViewStatus {
  available: boolean;
  active: boolean;
  model: string;
  active_source: 'hdmi' | 'ptp';
  available_sources: ('hdmi' | 'ptp')[];
  device_name: string;
  stream_type: 'webrtc_h264' | 'ptp_direct';
  whep_url: string;
  rtsp_url: string;
  hls_url: string;
  resolution: string;
  fps: number;
  hw_accel?: {
    enabled: boolean;
    encoder: string;
    device: string;
    profile: string;
    latency: string;
  };
}

export interface VideoDevice {
  device_node: string;
  sysfs_path: string;
  raw_name: string;
  name: string;
  is_capture_card: boolean;
  formats: {
    pixel_format: string;
    description: string;
    resolutions: {
      width: number;
      height: number;
      fps: number[];
      default?: boolean;
    }[];
  }[];
  hw_accel: {
    enabled: boolean;
    encoder: string;
    device: string;
    profile: string;
  };
  stream_endpoints: {
    rtsp: string;
    whep: string;
    hls: string;
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

// Post-capture processing (calibrate + crop background jobs)
export const getPostCaptureJobs = () => api.get('/api/batch/process');
export const getPostCaptureStatus = (folder: string) =>
  api.get(`/api/batch/process/${folder}`);
export const queuePostCapture = (folder: string) =>
  api.post(`/api/batch/process/${folder}`);
export const getCalibration = (folder: string) =>
  api.get(`/api/batch/calibration/${folder}`);
export const renderBatchImage = (
  folder: string, filename: string, format: 'jpg' | 'tiff' = 'jpg', crop: boolean = true
) => `${API_BASE_URL}/api/batch/render/${folder}/${filename}?format=${format}&crop=${crop}`;

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

export const captureColorChecker = (profileName?: string, overwrite?: boolean) =>
  api.post('/api/colorchecker/capture', { profile_name: profileName || null, overwrite: overwrite ?? false });

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

export const saveColorCheckerProfile = (detectionId: string, profileName: string, overwrite?: boolean) =>
  api.post('/api/colorchecker/save', { detection_id: detectionId, profile_name: profileName, overwrite: overwrite ?? false });

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

// ─── Material Tools API ───

// Tool 1: Equalize
export const equalizePreview = (batchName: string, method: string, opts?: {
  reference_image?: string;
  clip_limit?: number;
}) =>
  api.post('/api/processing/equalize/preview', { batch_name: batchName, method, ...opts });

export const equalizeApply = (batchName: string, method: string, opts?: {
  reference_image?: string;
  clip_limit?: number;
  apply_to_all?: boolean;
}) =>
  api.post('/api/processing/equalize/apply', { batch_name: batchName, method, ...opts });

// Tool 2: Delight
export const delightPreview = (batchName: string, opts?: {
  blur_radius?: number;
  strength?: number;
  method?: string;
}) =>
  api.post('/api/processing/delight/preview', { batch_name: batchName, ...opts });

export const delightApply = (batchName: string, opts: {
  blur_radius: number;
  strength: number;
  method?: string;
  apply_to_all?: boolean;
}) =>
  api.post('/api/processing/delight/apply', { batch_name: batchName, ...opts });

// Tool: Flatten
export const flattenPreview = (batchName: string, opts?: {
  strength?: number;
  smoothing_radius?: number;
  pbr_mode?: string;
}) =>
  api.post('/api/processing/flatten/preview', { batch_name: batchName, ...opts });

export const flattenApply = (batchName: string, opts: {
  strength: number;
  smoothing_radius: number;
  pbr_mode?: string;
  apply_to_all?: boolean;
}) =>
  api.post('/api/processing/flatten/apply', { batch_name: batchName, ...opts });

// Tool 3: Perspective Transform
export const perspectiveDetectLines = (batchName: string) =>
  api.post('/api/processing/perspective/detect-lines', { batch_name: batchName });

export const perspectivePreview = (batchName: string, sourcePoints: CropPoint[], destPoints?: CropPoint[]) =>
  api.post('/api/processing/perspective/preview', {
    batch_name: batchName, source_points: sourcePoints, dest_points: destPoints,
  });

export const perspectiveApply = (batchName: string, sourcePoints: CropPoint[], opts?: {
  dest_points?: CropPoint[];
  apply_to_all?: boolean;
}) =>
  api.post('/api/processing/perspective/apply', {
    batch_name: batchName, source_points: sourcePoints, ...opts,
  });

// Tool 4: Make Seamless
export const seamlessAnalyze = (batchName: string, blendWidth?: number) =>
  api.post('/api/processing/seamless/analyze', { batch_name: batchName, blend_width: blendWidth });

export const seamlessPreview = (batchName: string, opts: {
  method: string;
  blend_width: number;
  spots_removal?: boolean;
  color_equalizer?: number;
  tile_count?: number;
}) =>
  api.post('/api/processing/seamless/preview', { batch_name: batchName, ...opts });

export const seamlessApply = (batchName: string, opts: {
  method: string;
  blend_width: number;
  spots_removal?: boolean;
  color_equalizer?: number;
}) =>
  api.post('/api/processing/seamless/apply', { batch_name: batchName, ...opts });

// Tool 5: Tiling
export const tilePreview = (batchName: string, params: {
  tile_x: number;
  tile_y: number;
  offset_x?: number;
  offset_y?: number;
  scale?: number;
  rotation?: number;
  overlap?: number;
  half_drop?: boolean;
}) =>
  api.post('/api/processing/tile/preview', { batch_name: batchName, ...params });

export const tileApply = (batchName: string, params: {
  tile_x: number;
  tile_y: number;
  offset_x?: number;
  offset_y?: number;
  scale?: number;
  rotation?: number;
  overlap?: number;
  half_drop?: boolean;
  output_resolution?: [number, number];
}) =>
  api.post('/api/processing/tile/apply', { batch_name: batchName, ...params });

// Tool 6: PBR Validate
export const pbrValidateCheck = (batchName: string, opts?: {
  mode?: string;
  albedo_dark_threshold?: number;
  metal_range?: [number, number];
}) =>
  api.post('/api/processing/validate/check', { batch_name: batchName, ...opts });

export const pbrValidateStats = (batchName: string) =>
  api.get(`/api/processing/validate/stats/${batchName}`);

// Tool 7: Clone Stamp / Inpaint
export const cloneInpaint = (batchName: string, maskData: string, opts?: {
  method?: string;
  radius?: number;
}) =>
  api.post('/api/processing/clone/inpaint', {
    batch_name: batchName, mask_data: maskData, ...opts,
  });

export const cloneStamp = (batchName: string, opts: {
  source_pos: { x: number; y: number };
  target_pos: { x: number; y: number };
  radius: number;
  fade?: number;
  blur_mask?: number;
  mirror?: boolean;
}) =>
  api.post('/api/processing/clone/stamp', { batch_name: batchName, ...opts });

export const cloneApply = (batchName: string, operations: object[]) =>
  api.post('/api/processing/clone/apply', { batch_name: batchName, operations });

// Tool 8: Yarn Straighten
export const straightenAnalyze = (batchName: string, opts?: {
  grid_divisions?: number;
  direction?: string;
}) =>
  api.post('/api/processing/straighten/analyze', { batch_name: batchName, ...opts });

export const straightenPreview = (batchName: string, opts: {
  mode: string;
  strength: number;
  direction?: string;
  grid_divisions?: number;
  manual_skew_angle?: number | null;
}) =>
  api.post('/api/processing/straighten/preview', { batch_name: batchName, ...opts });

export const straightenApply = (batchName: string, opts: {
  mode: string;
  strength: number;
  direction?: string;
  grid_divisions?: number;
  manual_skew_angle?: number | null;
}) =>
  api.post('/api/processing/straighten/apply', { batch_name: batchName, ...opts });

// Tool pipeline status
export const getToolsStatus = (batchName: string) =>
  api.get(`/api/processing/tools/status/${batchName}`);

// Tool image helpers
export const getToolImage = (batchName: string, tool: string) =>
  api.get(`/api/processing/${tool}/image/${batchName}`);

export const getToolPreviewUrl = (batchName: string, tool: string, filename: string) =>
  `${API_BASE_URL}/media/captures/${batchName}/${tool}/${filename}`;

// ─── Image Processing Pipeline API ───

export interface ProcessTrackPhase {
  status: 'pending' | 'in_progress' | 'completed' | 'skipped';
  params: Record<string, any>;
}

export interface ProcessTrack {
  version: number;
  batch_name: string;
  created_at: string;
  updated_at: string;
  phases: {
    crop_align: ProcessTrackPhase;
    color: ProcessTrackPhase;
    pbr: ProcessTrackPhase;
    map_refine: ProcessTrackPhase;
    seamless_tiling: ProcessTrackPhase;
    validate_export: ProcessTrackPhase;
  };
}

export interface PipelineBatch {
  name: string;
  image_count: number;
  completed_phases: number;
  total_phases: number;
  has_track: boolean;
  phase_statuses: Record<string, string>;
}

// Batch list
export const getImageProcessingBatches = () =>
  api.get<{ batches: PipelineBatch[] }>('/api/image-processing/batches');

// Track CRUD
export const getProcessTrack = (batchName: string) =>
  api.get<ProcessTrack>(`/api/image-processing/track/${batchName}`);

export const createProcessTrack = (batchName: string) =>
  api.post<{ created: boolean; track: ProcessTrack }>(`/api/image-processing/track/${batchName}`);

export const updatePhaseParams = (
  batchName: string,
  phase: string,
  data: { status?: string; params?: Record<string, any> }
) =>
  api.put(`/api/image-processing/track/${batchName}/${phase}`, data);

// Preview (in-memory chain, returns JPEG URL)
// Each new call aborts the previous in-flight request to avoid stale previews
let previewAbortController: AbortController | null = null;

export const pipelinePreview = (batchName: string, phase: string) => {
  if (previewAbortController) previewAbortController.abort();
  previewAbortController = new AbortController();
  return api.post<{ success: boolean; preview_url?: string; albedo_url?: string; error?: string }>(
    `/api/image-processing/preview/${batchName}/${phase}`,
    undefined,
    { signal: previewAbortController.signal }
  );
};

// Save (full pipeline from RAW)
export const pipelineSave = (batchName: string) =>
  api.post(`/api/image-processing/save/${batchName}`);

export const pipelineSaveThrough = (batchName: string, phase: string) =>
  api.post(`/api/image-processing/save/${batchName}/${phase}`);

// Exposure preview
export const exposurePreview = (batchName: string, offset: number, method?: string) =>
  api.post(`/api/image-processing/exposure/preview/${batchName}`, {
    offset, method: method || 'offset',
  });

// Roughness scale preview
export const roughnessScalePreview = (batchName: string, scale: number, pbrMode?: string) =>
  api.post(`/api/image-processing/roughness/preview/${batchName}`, {
    scale, pbr_mode: pbrMode || 'grayscale',
  });

// Apply calibration profile to track (computes matrix_3x3, extracts checker_wb)
export const applyProfileToTrack = (batchName: string, profileName: string) =>
  api.post<{ success: boolean; params_saved: string[]; track: ProcessTrack }>(
    `/api/image-processing/apply-profile/${batchName}`,
    { profile_name: profileName },
  );

// ─── Auto Exposure API ───

export interface ExposureConfig {
  enabled: boolean;
  mode: string;
  iso: number;
  aperture: number;
  target_percentile: number;
  target_normalized: number;
  acceptable_low: number;
  acceptable_high: number;
  near_clip_threshold: number;
  hard_clip_threshold: number;
  max_hard_clip_fraction: number;
  max_near_clip_fraction: number;
  retake_limit: number;
  minimum_p95_normalized: number;
}

export interface ExposureStatus {
  connected: boolean;
  iso: number | null;
  aperture: number | null;
  shutter_seconds: number | null;
  shutter_label: string | null;
  camera_mode: string | null;
}

export interface PreflightLightResult {
  name: string;
  status: string;
  limiting_channel: string | null;
  measured_normalized: number | null;
  clipped_fraction: number | null;
}

export interface PreflightResponse {
  status: string;
  selected_shutter_seconds: number | null;
  selected_shutter_label: string | null;
  iso: number | null;
  aperture: number | null;
  limiting_light: string | null;
  limiting_channel: string | null;
  predicted_peak: number | null;
  headroom_ev: number | null;
  iterations: number;
  lights: PreflightLightResult[];
  errors: string[];
  warnings: string[];
}

export interface FrameQaResponse {
  status: string;
  reason: string;
  p99_9: Record<string, number>;
  limiting_channel: string | null;
  measured_normalized: number | null;
  hard_clip_fraction: number | null;
  near_clip_fraction: number | null;
  headroom_ev: number | null;
}

export const getExposureConfig = () =>
  api.get<ExposureConfig>('/api/exposure/config');
export const getExposureStatus = () =>
  api.get<ExposureStatus>('/api/exposure/status');
export const runExposurePreflight = () =>
  api.post<PreflightResponse>('/api/exposure/preflight');
export const qaFrame = (folder: string, filename: string) =>
  api.post<FrameQaResponse>(`/api/exposure/qa/${folder}/${filename}`);
