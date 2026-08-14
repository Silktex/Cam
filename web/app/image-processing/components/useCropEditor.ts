'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  getTopImageForCrop, autoDetectCrop, applyCrop, getFullUrl,
  straightenAnalyze, straightenPreview, straightenApply,
  updatePhaseParams,
} from '@/lib/api';

export interface Point {
  x: number;
  y: number;
}

export interface CropImageData {
  width: number;
  height: number;
  preview_width: number;
  preview_height: number;
  preview_url: string;
  filename: string;
}

export interface CropState {
  imageData: CropImageData | null;
  imageLoaded: boolean;
  loadError: string | null;
  loading: boolean;
  points: Point[];
  currentPointIndex: number;
  rotation: number;
  isDragging: number | null;
  isDraggingArea: boolean;
  dragStart: Point | null;
  scale: number;
  method: 'manual' | 'auto';
  cropSize: number;
  cursorStyle: string;
  processing: string | null;
  result: { success: boolean; message: string } | null;
  scaleRatio: number;
  // Straighten
  straightenAnalysis: any;
  straightenMode: string;
  straightenStrength: number;
  straightenDirection: string;
  straightenGrid: number;
  straightenPreviewData: any;
  manualSkewAngle: number | null;
  straightenExpanded: boolean;
  straightenProcessing: string | null;
}

export interface CropActions {
  setPoints: (points: Point[]) => void;
  setCurrentPointIndex: (i: number) => void;
  setRotation: (r: number | ((prev: number) => number)) => void;
  setIsDragging: (i: number | null) => void;
  setIsDraggingArea: (b: boolean) => void;
  setDragStart: (p: Point | null) => void;
  setScale: (s: number | ((prev: number) => number)) => void;
  setMethod: (m: 'manual' | 'auto') => void;
  setCropSize: (s: number) => void;
  setCursorStyle: (c: string) => void;
  setResult: (r: { success: boolean; message: string } | null) => void;
  // Straighten setters
  setStraightenMode: (m: string) => void;
  setStraightenStrength: (s: number) => void;
  setStraightenDirection: (d: string) => void;
  setStraightenGrid: (g: number) => void;
  setManualSkewAngle: (a: number | null) => void;
  setStraightenExpanded: (e: boolean) => void;
  // Handlers
  handleAutoDetect: () => Promise<void>;
  handleReset: () => void;
  handleRectangularize: () => void;
  handleSquarify: () => void;
  handleApply: () => Promise<void>;
  handleStraightenAnalyze: () => Promise<void>;
  handleStraightenPreview: () => Promise<void>;
  handleStraightenUndo: () => void;
  handleZoomIn: () => void;
  handleZoomOut: () => void;
  handleFit: () => void;
  getCropDimensions: () => { width: number; height: number };
}

export interface CropRefs {
  canvasRef: React.RefObject<HTMLCanvasElement>;
  containerRef: React.RefObject<HTMLDivElement>;
  imageRef: React.MutableRefObject<HTMLImageElement | null>;
}

const pointLabels = ['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left'];
export { pointLabels };

export default function useCropEditor(
  batchName: string,
  onDeactivate: () => void,
  onPreviewRefresh: () => void,
) {
  const queryClient = useQueryClient();

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  // Image state
  const [imageData, setImageData] = useState<CropImageData | null>(null);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Crop state
  const [points, setPoints] = useState<Point[]>([]);
  const [currentPointIndex, setCurrentPointIndex] = useState(0);
  const [rotation, setRotation] = useState(0);
  const [isDragging, setIsDragging] = useState<number | null>(null);
  const [isDraggingArea, setIsDraggingArea] = useState(false);
  const [dragStart, setDragStart] = useState<Point | null>(null);
  const [scale, setScale] = useState(1);
  const [method, setMethod] = useState<'manual' | 'auto'>('manual');
  const [cropSize, setCropSize] = useState(2048);
  const [cursorStyle, setCursorStyle] = useState('crosshair');

  // Processing state
  const [processing, setProcessing] = useState<string | null>(null);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  // Straighten state
  const [straightenAnalysis, setStraightenAnalysis] = useState<any>(null);
  const [straightenMode, setStraightenMode] = useState('auto');
  const [straightenStrength, setStraightenStrength] = useState(1.0);
  const [straightenDirection, setStraightenDirection] = useState('both');
  const [straightenGrid, setStraightenGrid] = useState(20);
  const [straightenPreviewData, setStraightenPreviewData] = useState<any>(null);
  const [manualSkewAngle, setManualSkewAngle] = useState<number | null>(null);
  const [straightenExpanded, setStraightenExpanded] = useState(false);
  const [straightenProcessing, setStraightenProcessing] = useState<string | null>(null);

  // Derived
  const scaleRatio = imageData ? imageData.width / imageData.preview_width : 1;

  // Load batch data
  useEffect(() => {
    const loadData = async () => {
      try {
        const res = await getTopImageForCrop(batchName);
        setImageData(res.data);
      } catch (err: any) {
        setLoadError(err.response?.data?.detail || 'Failed to load batch');
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [batchName]);

  // Load image
  useEffect(() => {
    if (!imageData) return;

    setImageLoaded(false);
    setLoadError(null);

    const img = new Image();
    img.onload = () => {
      imageRef.current = img;

      if (containerRef.current) {
        const containerWidth = containerRef.current.clientWidth - 32;
        const containerHeight = containerRef.current.clientHeight - 32;
        const scaleX = containerWidth / img.width;
        const scaleY = containerHeight / img.height;
        setScale(Math.min(scaleX, scaleY, 1));
      }

      const margin = 0.15;
      setPoints([
        { x: imageData.width * margin, y: imageData.height * margin },
        { x: imageData.width * (1 - margin), y: imageData.height * margin },
        { x: imageData.width * (1 - margin), y: imageData.height * (1 - margin) },
        { x: imageData.width * margin, y: imageData.height * (1 - margin) },
      ]);

      setImageLoaded(true);
    };

    img.onerror = () => {
      setLoadError('Failed to load preview image');
    };

    img.src = getFullUrl(imageData.preview_url);
  }, [imageData]);

  // Crop dimensions
  const getCropDimensions = useCallback(() => {
    if (points.length !== 4) return { width: 0, height: 0 };
    const topW = Math.sqrt(Math.pow(points[1].x - points[0].x, 2) + Math.pow(points[1].y - points[0].y, 2));
    const bottomW = Math.sqrt(Math.pow(points[2].x - points[3].x, 2) + Math.pow(points[2].y - points[3].y, 2));
    const leftH = Math.sqrt(Math.pow(points[3].x - points[0].x, 2) + Math.pow(points[3].y - points[0].y, 2));
    const rightH = Math.sqrt(Math.pow(points[2].x - points[1].x, 2) + Math.pow(points[2].y - points[1].y, 2));
    return { width: Math.round((topW + bottomW) / 2), height: Math.round((leftH + rightH) / 2) };
  }, [points]);

  // Actions
  const handleAutoDetect = async () => {
    setProcessing('auto');
    try {
      const res = await autoDetectCrop(batchName, cropSize);
      if (res.data.success && res.data.bbox) {
        const [x1, y1, x2, y2] = res.data.bbox;
        setPoints([
          { x: x1, y: y1 },
          { x: x2, y: y1 },
          { x: x2, y: y2 },
          { x: x1, y: y2 },
        ]);
        setMethod('auto');
      } else {
        setResult({ success: false, message: res.data.error || 'Auto-detect failed' });
      }
    } catch (err: any) {
      setResult({ success: false, message: err.message || 'Auto-detect failed' });
    } finally {
      setProcessing(null);
    }
  };

  const handleReset = () => {
    if (!imageData) return;
    const margin = 0.15;
    setPoints([
      { x: imageData.width * margin, y: imageData.height * margin },
      { x: imageData.width * (1 - margin), y: imageData.height * margin },
      { x: imageData.width * (1 - margin), y: imageData.height * (1 - margin) },
      { x: imageData.width * margin, y: imageData.height * (1 - margin) },
    ]);
    setRotation(0);
    setCurrentPointIndex(0);
    setMethod('manual');
  };

  const handleRectangularize = () => {
    if (points.length !== 4) return;
    const centerX = points.reduce((sum, p) => sum + p.x, 0) / 4;
    const centerY = points.reduce((sum, p) => sum + p.y, 0) / 4;
    const topWidth = Math.sqrt(Math.pow(points[1].x - points[0].x, 2) + Math.pow(points[1].y - points[0].y, 2));
    const bottomWidth = Math.sqrt(Math.pow(points[2].x - points[3].x, 2) + Math.pow(points[2].y - points[3].y, 2));
    const leftHeight = Math.sqrt(Math.pow(points[3].x - points[0].x, 2) + Math.pow(points[3].y - points[0].y, 2));
    const rightHeight = Math.sqrt(Math.pow(points[2].x - points[1].x, 2) + Math.pow(points[2].y - points[1].y, 2));
    const avgWidth = (topWidth + bottomWidth) / 2;
    const avgHeight = (leftHeight + rightHeight) / 2;
    const halfW = avgWidth / 2;
    const halfH = avgHeight / 2;
    setPoints([
      { x: Math.round(centerX - halfW), y: Math.round(centerY - halfH) },
      { x: Math.round(centerX + halfW), y: Math.round(centerY - halfH) },
      { x: Math.round(centerX + halfW), y: Math.round(centerY + halfH) },
      { x: Math.round(centerX - halfW), y: Math.round(centerY + halfH) },
    ]);
    setMethod('manual');
  };

  const handleSquarify = () => {
    if (points.length !== 4) return;
    const centerX = points.reduce((sum, p) => sum + p.x, 0) / 4;
    const centerY = points.reduce((sum, p) => sum + p.y, 0) / 4;
    const topWidth = Math.sqrt(Math.pow(points[1].x - points[0].x, 2) + Math.pow(points[1].y - points[0].y, 2));
    const bottomWidth = Math.sqrt(Math.pow(points[2].x - points[3].x, 2) + Math.pow(points[2].y - points[3].y, 2));
    const leftHeight = Math.sqrt(Math.pow(points[3].x - points[0].x, 2) + Math.pow(points[3].y - points[0].y, 2));
    const rightHeight = Math.sqrt(Math.pow(points[2].x - points[1].x, 2) + Math.pow(points[2].y - points[1].y, 2));
    const avgWidth = (topWidth + bottomWidth) / 2;
    const avgHeight = (leftHeight + rightHeight) / 2;
    const size = (avgWidth + avgHeight) / 2;
    const half = size / 2;
    setPoints([
      { x: Math.round(centerX - half), y: Math.round(centerY - half) },
      { x: Math.round(centerX + half), y: Math.round(centerY - half) },
      { x: Math.round(centerX + half), y: Math.round(centerY + half) },
      { x: Math.round(centerX - half), y: Math.round(centerY + half) },
    ]);
    setMethod('manual');
  };

  const handleApply = async () => {
    if (!imageData) return;
    setProcessing('apply');
    try {
      const transformedPoints = points.map(p => {
        if (rotation === 0) return { x: p.x, y: p.y };
        const centerX = imageData.width / 2;
        const centerY = imageData.height / 2;
        const rad = (-rotation * Math.PI) / 180;
        const cos = Math.cos(rad);
        const sin = Math.sin(rad);
        const dx = p.x - centerX;
        const dy = p.y - centerY;
        return {
          x: Math.round(cos * dx - sin * dy + centerX),
          y: Math.round(sin * dx + cos * dy + centerY),
        };
      });

      const res = await applyCrop(batchName, method, {
        points: transformedPoints,
        rotation,
      });

      if (res.data.success) {
        if (straightenAnalysis) {
          try {
            await straightenApply(batchName, {
              mode: straightenMode,
              strength: straightenStrength,
              direction: straightenDirection,
              grid_divisions: straightenGrid,
              manual_skew_angle: manualSkewAngle,
            });
          } catch (err: any) {
            console.error('Straighten apply failed:', err);
          }
        }

        await updatePhaseParams(batchName, 'crop_align', {
          status: 'completed',
          params: {
            crop_type: method,
            points: transformedPoints,
            rotation,
            crop_size: cropSize,
          },
        });

        setResult({
          success: true,
          message: `Cropped ${res.data.processed}/${res.data.total} images`,
        });

        // Invalidate track query and refresh preview
        queryClient.invalidateQueries({ queryKey: ['process-track', batchName] });
        onPreviewRefresh();

        setTimeout(() => {
          setResult(null);
          onDeactivate();
        }, 1500);
      } else {
        setResult({ success: false, message: 'Crop failed' });
      }
    } catch (err: any) {
      setResult({ success: false, message: err.response?.data?.detail || 'Crop failed' });
    } finally {
      setProcessing(null);
    }
  };

  // Straighten handlers
  const handleStraightenAnalyze = async () => {
    setStraightenProcessing('analyze');
    try {
      const res = await straightenAnalyze(batchName, {
        grid_divisions: straightenGrid,
        direction: straightenDirection,
      });
      setStraightenAnalysis(res.data);
      setStraightenExpanded(true);
    } catch (err: any) {
      setResult({ success: false, message: err.response?.data?.detail || 'Straighten analysis failed' });
    } finally {
      setStraightenProcessing(null);
    }
  };

  const handleStraightenPreview = async () => {
    setStraightenProcessing('preview');
    try {
      const res = await straightenPreview(batchName, {
        mode: straightenMode,
        strength: straightenStrength,
        direction: straightenDirection,
        grid_divisions: straightenGrid,
        manual_skew_angle: manualSkewAngle,
      });
      setStraightenPreviewData(res.data);
    } catch (err: any) {
      setResult({ success: false, message: err.response?.data?.detail || 'Straighten preview failed' });
    } finally {
      setStraightenProcessing(null);
    }
  };

  const handleStraightenUndo = () => {
    setStraightenAnalysis(null);
    setStraightenPreviewData(null);
    setManualSkewAngle(null);
  };

  // Zoom
  const handleZoomIn = () => setScale(s => Math.min(s * 1.2, 3));
  const handleZoomOut = () => setScale(s => Math.max(s / 1.2, 0.1));
  const handleFit = () => {
    if (containerRef.current && imageRef.current) {
      const cw = containerRef.current.clientWidth - 32;
      const ch = containerRef.current.clientHeight - 32;
      setScale(Math.min(cw / imageRef.current.width, ch / imageRef.current.height, 1));
    }
  };

  // Keyboard shortcuts
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        if (!processing && points.length === 4) handleApply();
        return;
      }

      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (e.metaKey || e.ctrlKey) return;

      if (e.key === 'a' || e.key === 'A') {
        e.preventDefault();
        if (!processing) handleAutoDetect();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  });

  const state: CropState = {
    imageData,
    imageLoaded,
    loadError,
    loading,
    points,
    currentPointIndex,
    rotation,
    isDragging,
    isDraggingArea,
    dragStart,
    scale,
    method,
    cropSize,
    cursorStyle,
    processing,
    result,
    scaleRatio,
    straightenAnalysis,
    straightenMode,
    straightenStrength,
    straightenDirection,
    straightenGrid,
    straightenPreviewData,
    manualSkewAngle,
    straightenExpanded,
    straightenProcessing,
  };

  const actions: CropActions = {
    setPoints,
    setCurrentPointIndex,
    setRotation,
    setIsDragging,
    setIsDraggingArea,
    setDragStart,
    setScale,
    setMethod,
    setCropSize,
    setCursorStyle,
    setResult,
    setStraightenMode,
    setStraightenStrength,
    setStraightenDirection,
    setStraightenGrid,
    setManualSkewAngle,
    setStraightenExpanded,
    handleAutoDetect,
    handleReset,
    handleRectangularize,
    handleSquarify,
    handleApply,
    handleStraightenAnalyze,
    handleStraightenPreview,
    handleStraightenUndo,
    handleZoomIn,
    handleZoomOut,
    handleFit,
    getCropDimensions,
  };

  const refs: CropRefs = {
    canvasRef,
    containerRef,
    imageRef,
  };

  return { state, actions, refs };
}
