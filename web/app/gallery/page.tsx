'use client';

import { useState, useEffect, useCallback, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  Folder, FileImage, ChevronRight, Home, X, ArrowLeft,
  ZoomIn, ZoomOut, RotateCcw, Download, Loader2, Image as ImageIcon, Trash2,
  RefreshCw, CheckCircle2
} from 'lucide-react';
import { browsePath, getMediaUrl, resolveImageUrl, deleteFolder, deleteFile, reconvertTiff } from '@/lib/api';
import dynamic from 'next/dynamic';

const DashboardHeader = dynamic(() => import('../all/components/DashboardHeader'), {
  ssr: false,
});

interface BreadcrumbItem {
  name: string;
  path: string;
}

interface GalleryItem {
  name: string;
  type: 'folder' | 'file';
  path: string;
  url?: string;
  download_url?: string;
  thumbnail_url?: string;
  size?: number;
  modified: number;
  is_image?: boolean;
  file_count?: number;
}

interface BrowseResponse {
  path: string;
  breadcrumbs: BreadcrumbItem[];
  items: GalleryItem[];
  folder_count: number;
  file_count: number;
}

export default function GalleryPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="flex items-center gap-3 text-slate-400">
          <Loader2 className="w-6 h-6 animate-spin" />
          <span>Loading gallery...</span>
        </div>
      </div>
    }>
      <GalleryContent />
    </Suspense>
  );
}

function GalleryContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const currentPath = searchParams.get('path') || '';

  const [data, setData] = useState<BrowseResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [reconverting, setReconverting] = useState(false);
  const [reconvertResult, setReconvertResult] = useState<{ success: boolean; message: string } | null>(null);
  const [confirmModal, setConfirmModal] = useState<{
    open: boolean;
    type: 'folder' | 'file';
    path: string;
    name: string;
  }>({ open: false, type: 'folder', path: '', name: '' });

  // Image viewer state
  const [viewerOpen, setViewerOpen] = useState(false);
  const [viewerImages, setViewerImages] = useState<GalleryItem[]>([]);
  const [viewerIndex, setViewerIndex] = useState(0);
  const viewerImage = viewerImages[viewerIndex] ?? null;
  const [zoom, setZoom] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await browsePath(currentPath);
      setData(response.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load gallery');
    } finally {
      setLoading(false);
    }
  }, [currentPath]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Keyboard navigation for viewer
  useEffect(() => {
    if (!viewerOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeViewer();
      if (e.key === 'ArrowRight') navigateViewer(1);
      if (e.key === 'ArrowLeft') navigateViewer(-1);
      if (e.key === '+' || e.key === '=') handleZoomIn();
      if (e.key === '-') handleZoomOut();
      if (e.key === '0') handleResetZoom();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [viewerOpen, viewerIndex, viewerImages]);

  // Global navigation shortcuts
  useEffect(() => {
    const handleNavKey = (e: KeyboardEvent) => {
      if (viewerOpen) return;
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      switch (e.key) {
        case 'd':
          router.push('/');
          break;
        case 'p':
          router.push('/processing');
          break;
        case 'g':
          // already on gallery
          break;
      }
    };

    window.addEventListener('keydown', handleNavKey);
    return () => window.removeEventListener('keydown', handleNavKey);
  }, [router, viewerOpen]);

  const navigateTo = (path: string) => {
    router.push(`/gallery${path ? `?path=${encodeURIComponent(path)}` : ''}`);
  };

  const requestDelete = (type: 'folder' | 'file', path: string, name: string) => {
    setConfirmModal({ open: true, type, path, name });
  };

  const handleConfirmDelete = async () => {
    const { type, path } = confirmModal;
    setConfirmModal(m => ({ ...m, open: false }));
    setDeleting(true);
    try {
      if (type === 'folder') {
        await deleteFolder(path);
      } else {
        await deleteFile(path);
      }
      // If we deleted the currently viewed image, close viewer or navigate to next
      if (type === 'file' && viewerOpen && viewerImage?.path === path) {
        const remaining = viewerImages.filter(i => i.path !== path);
        if (remaining.length === 0) {
          closeViewer();
        } else {
          const newIndex = Math.min(viewerIndex, remaining.length - 1);
          setViewerImages(remaining);
          setViewerIndex(newIndex);
          setZoom(1);
          setPosition({ x: 0, y: 0 });
        }
      }
      fetchData();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to delete');
    } finally {
      setDeleting(false);
    }
  };

  const getImageUrl = (item: GalleryItem, preferWebview = true) => {
    // Use item.url which already points to the best display version (from backend)
    if (item.url) {
      if (item.url.startsWith('/api/')) return item.url;
      return item.url.replace('/media/captures/', '');
    }
    return item.path;
  };

  const openViewer = (item: GalleryItem, allImages: GalleryItem[]) => {
    const idx = allImages.findIndex(i => i.path === item.path);
    setViewerImages(allImages);
    setViewerIndex(idx >= 0 ? idx : 0);
    setZoom(1);
    setPosition({ x: 0, y: 0 });
    setViewerOpen(true);
  };

  const navigateViewer = (delta: number) => {
    const newIndex = viewerIndex + delta;
    if (newIndex >= 0 && newIndex < viewerImages.length) {
      setViewerIndex(newIndex);
      setZoom(1);
      setPosition({ x: 0, y: 0 });
    }
  };

  const closeViewer = () => {
    setViewerOpen(false);
    setViewerImages([]);
    setViewerIndex(0);
  };

  const handleZoomIn = () => setZoom(z => Math.min(z * 1.25, 8));
  const handleZoomOut = () => setZoom(z => Math.max(z / 1.25, 0.25));
  const handleResetZoom = () => {
    setZoom(1);
    setPosition({ x: 0, y: 0 });
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (zoom > 1) {
      setIsDragging(true);
      setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y });
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isDragging && zoom > 1) {
      setPosition({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
    }
  };

  const handleMouseUp = () => setIsDragging(false);

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    // Smooth zoom based on scroll delta magnitude
    const delta = e.deltaY;
    const zoomFactor = 1 + Math.min(Math.abs(delta) * 0.003, 0.2);

    if (delta < 0) {
      setZoom(z => Math.min(z * zoomFactor, 8));
    } else {
      setZoom(z => Math.max(z / zoomFactor, 0.25));
    }
  };

  const formatSize = (bytes?: number) => {
    if (!bytes) return '-';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  };

  const handleReconvertTiff = async () => {
    if (!currentPath) return;
    setReconverting(true);
    setReconvertResult(null);
    try {
      const res = await reconvertTiff(currentPath);
      const d = res.data;
      setReconvertResult({
        success: d.success > 0,
        message: `Reconverted ${d.success}/${d.total} files${d.failed > 0 ? ` (${d.failed} failed)` : ''}`,
      });
      fetchData();
    } catch (err: any) {
      setReconvertResult({
        success: false,
        message: err.response?.data?.detail || 'Reconvert failed',
      });
    } finally {
      setReconverting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950">
        <DashboardHeader />
        <div className="flex items-center justify-center py-24">
          <div className="flex items-center gap-3 text-slate-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <span>Loading gallery...</span>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-slate-950">
        <DashboardHeader />
        <div className="flex items-center justify-center py-24">
          <div className="bg-red-500/10 border border-red-500/30 rounded-2xl p-6 max-w-md text-center">
            <p className="text-red-400 mb-4">{error}</p>
            <button
              onClick={fetchData}
              className="px-4 py-2 bg-red-600 text-white rounded-xl hover:bg-red-700"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Hide internal folders (cropped_thumbnail, full_webview) from gallery
  const HIDDEN_FOLDERS = new Set(['cropped_thumbnail', 'full_webview']);
  const visibleItems = data?.items.filter(i =>
    !(i.type === 'folder' && HIDDEN_FOLDERS.has(i.name))
  ) || [];
  const imageItems = visibleItems.filter(i => i.type === 'file' && i.is_image);

  // Show reconvert button when inside a batch folder (has raw/ subfolder)
  const hasRawFolder = data?.items.some(i => i.type === 'folder' && i.name === 'raw') || false;

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* Shared Nav */}
      <div className="sticky top-0 z-10">
        <DashboardHeader />
      </div>

      {/* Gallery sub-header */}
      <div className="border-b border-slate-800 bg-slate-900/60">
        <div className="max-w-7xl mx-auto px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">Gallery</h2>
              <p className="text-sm text-slate-400">
                {visibleItems.filter(i => i.type === 'folder').length} folders, {visibleItems.filter(i => i.type === 'file').length} files
              </p>
            </div>
            <div className="flex items-center gap-2">
              {hasRawFolder && (
                <>
                  <button
                    onClick={handleReconvertTiff}
                    disabled={reconverting}
                    className="px-4 py-2 bg-orange-600 text-white rounded-xl hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-2 text-sm font-medium"
                    title="Re-convert all RAW files to linear sRGB TIFFs"
                  >
                    {reconverting ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <RefreshCw className="w-4 h-4" />
                    )}
                    Reconvert TIFFs
                  </button>
                  {reconvertResult && (
                    <span className={`text-sm ${reconvertResult.success ? 'text-green-400' : 'text-red-400'} inline-flex items-center gap-1`}>
                      {reconvertResult.success ? <CheckCircle2 className="w-4 h-4" /> : null}
                      {reconvertResult.message}
                    </span>
                  )}
                </>
              )}
            </div>
          </div>

          {/* Breadcrumbs */}
          <nav className="flex items-center gap-1 mt-3 text-sm overflow-x-auto pb-1">
            {data?.breadcrumbs.map((crumb, idx) => (
              <div key={crumb.path || 'root'} className="flex items-center gap-1 flex-shrink-0">
                {idx > 0 && <ChevronRight className="w-4 h-4 text-slate-500" />}
                <button
                  onClick={() => navigateTo(crumb.path)}
                  className={`flex items-center gap-1 px-2 py-1 rounded-lg transition-colors ${
                    idx === (data?.breadcrumbs.length || 0) - 1
                      ? 'bg-teal-600/20 text-teal-400 font-medium'
                      : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                  }`}
                >
                  {idx === 0 && <Home className="w-4 h-4" />}
                  <span className="max-w-[150px] truncate">{crumb.name}</span>
                </button>
              </div>
            ))}
          </nav>
        </div>
      </div>

      {/* Content */}
      <main className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        {visibleItems.length === 0 ? (
          <div className="text-center py-16 text-slate-500">
            <Folder className="w-16 h-16 mx-auto mb-4 opacity-30" />
            <p>This folder is empty</p>
            <Link
              href="/"
              className="inline-block mt-4 px-4 py-2 bg-teal-600 text-white rounded-xl hover:bg-teal-700"
            >
              Start Capturing
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
            {visibleItems.map((item) => (
              <div
                key={item.path}
                className="group relative bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden transition-all hover:border-teal-500/50"
              >
                {/* Thumbnail / Icon */}
                <div
                  onClick={() => {
                    if (item.type === 'folder') {
                      navigateTo(item.path);
                    } else if (item.is_image) {
                      openViewer(item, imageItems);
                    }
                  }}
                  className={`aspect-square bg-slate-800/50 flex items-center justify-center overflow-hidden ${
                    item.type === 'folder' || item.is_image ? 'cursor-pointer' : ''
                  }`}
                >
                  {item.type === 'folder' ? (
                    <div className="flex flex-col items-center">
                      <Folder className="w-14 h-14 text-teal-500" />
                      <span className="text-xs text-slate-400 mt-1">{item.file_count} files</span>
                    </div>
                  ) : item.is_image && item.thumbnail_url ? (
                    <img
                      src={`${resolveImageUrl(item.thumbnail_url)}${item.thumbnail_url.includes('?') ? '&' : '?'}t=${item.modified}`}
                      alt={item.name}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform"
                      loading="lazy"
                    />
                  ) : item.is_image ? (
                    <ImageIcon className="w-12 h-12 text-slate-600" />
                  ) : (
                    <FileImage className="w-12 h-12 text-slate-600" />
                  )}
                </div>

                {/* Info */}
                <div className="p-3">
                  <p className="text-sm font-medium text-slate-200 truncate" title={item.name}>
                    {item.name}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {item.type === 'folder' ? '' : formatSize(item.size)}
                  </p>
                </div>

                {/* Delete button */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    requestDelete(
                      item.type === 'folder' ? 'folder' : 'file',
                      item.path,
                      item.name
                    );
                  }}
                  disabled={deleting}
                  className="absolute top-2 right-2 z-10 p-1.5 rounded-lg bg-red-500/80 text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600"
                  title={`Delete ${item.type === 'folder' ? 'folder' : 'file'}`}
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Confirmation Modal */}
      {confirmModal.open && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl shadow-xl max-w-sm w-full mx-4 overflow-hidden">
            <div className="p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 rounded-full bg-red-500/20">
                  <Trash2 className="w-5 h-5 text-red-400" />
                </div>
                <h3 className="text-lg font-semibold text-white">
                  Delete {confirmModal.type === 'folder' ? 'Folder' : 'File'}
                </h3>
              </div>
              <p className="text-slate-300 text-sm">
                {confirmModal.type === 'folder'
                  ? <>Are you sure you want to delete <strong>{confirmModal.name}</strong> and all its contents? This cannot be undone.</>
                  : <>Are you sure you want to delete <strong>{confirmModal.name}</strong>? This cannot be undone.</>
                }
              </p>
            </div>
            <div className="flex border-t border-slate-700">
              <button
                onClick={() => setConfirmModal(m => ({ ...m, open: false }))}
                className="flex-1 px-4 py-3 text-sm font-medium text-slate-300 hover:bg-slate-800 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDelete}
                className="flex-1 px-4 py-3 text-sm font-medium text-white bg-red-600 hover:bg-red-700 transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Image Viewer Modal */}
      {viewerOpen && viewerImage && (
        <div className="fixed inset-0 z-50 bg-black/95 flex flex-col">
          {/* Viewer Header */}
          <div className="flex items-center justify-between px-4 py-3 bg-black/50">
            <div className="text-white min-w-0 flex-1">
              <p className="font-medium truncate">{viewerImage.name}</p>
              <p className="text-sm text-white/60">
                {formatSize(viewerImage.size)}
              </p>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                onClick={handleZoomOut}
                className="p-2 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
                title="Zoom Out (-)"
              >
                <ZoomOut className="w-5 h-5" />
              </button>
              <span className="text-white/80 text-sm min-w-[60px] text-center">
                {Math.round(zoom * 100)}%
              </span>
              <button
                onClick={handleZoomIn}
                className="p-2 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
                title="Zoom In (+)"
              >
                <ZoomIn className="w-5 h-5" />
              </button>
              <button
                onClick={handleResetZoom}
                className="p-2 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
                title="Reset (0)"
              >
                <RotateCcw className="w-5 h-5" />
              </button>
              <a
                href={resolveImageUrl(viewerImage.download_url || `/media/captures/${viewerImage.path}`)}
                download
                className="p-2 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
                title="Download Cropped"
              >
                <Download className="w-5 h-5" />
              </a>
              <button
                onClick={() => {
                  requestDelete('file', viewerImage.path, viewerImage.name);
                }}
                disabled={deleting}
                className="p-2 rounded-lg bg-red-500/80 hover:bg-red-600 text-white transition-colors"
                title="Delete image"
              >
                <Trash2 className="w-5 h-5" />
              </button>
              <button
                onClick={closeViewer}
                className="p-2 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors ml-2"
                title="Close (ESC)"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Navigation arrows */}
          {viewerIndex > 0 && (
            <button
              onClick={() => navigateViewer(-1)}
              className="absolute left-4 top-1/2 -translate-y-1/2 p-3 rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors z-10"
            >
              <ArrowLeft className="w-6 h-6" />
            </button>
          )}
          {viewerIndex < viewerImages.length - 1 && (
            <button
              onClick={() => navigateViewer(1)}
              className="absolute right-4 top-1/2 -translate-y-1/2 p-3 rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors z-10 rotate-180"
            >
              <ArrowLeft className="w-6 h-6" />
            </button>
          )}

          {/* Image Container */}
          <div
            className="flex-1 overflow-hidden flex items-center justify-center"
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            onWheel={handleWheel}
            style={{ cursor: zoom > 1 ? (isDragging ? 'grabbing' : 'grab') : 'default' }}
          >
            <div
              className="flex items-center justify-center"
              style={{
                transform: `translate(${position.x}px, ${position.y}px)`,
                width: '100%',
                height: '100%',
              }}
            >
              <img
                key={viewerImage.path}
                src={(() => {
                  const imgUrl = getImageUrl(viewerImage, true);
                  const base = imgUrl.startsWith('/api/') ? resolveImageUrl(imgUrl) : getMediaUrl(imgUrl);
                  return `${base}${imgUrl.includes('?') ? '&' : '?'}t=${viewerImage.modified}`;
                })()}
                alt={viewerImage.name}
                className="transition-transform select-none object-contain"
                style={{
                  transform: `scale(${zoom})`,
                  transformOrigin: 'center center',
                  maxHeight: '100%',
                  maxWidth: '100%',
                }}
                draggable={false}
                onError={(e) => {
                  const target = e.currentTarget;
                  if (!target.dataset.fallback) {
                    target.dataset.fallback = 'true';
                    // Fallback to original path if cropped version fails
                    const fallbackUrl = viewerImage.url || `/media/captures/${viewerImage.path}`;
                    target.src = `${resolveImageUrl(fallbackUrl)}?t=${viewerImage.modified}`;
                  }
                }}
              />
            </div>
          </div>

          {/* Keyboard hint */}
          <div className="text-center py-2 text-white/40 text-xs">
            Arrow keys: navigate • Scroll: zoom • Drag: pan • ESC: close
          </div>
        </div>
      )}
    </div>
  );
}
