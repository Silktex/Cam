'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getCaptureFolders, getFolderContents, deleteFolder, type FolderInfo } from '@/lib/api';
import { Images, Folder, Trash2, ArrowLeft, Loader2, Download, Image as ImageIcon } from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function GalleryPage() {
  const queryClient = useQueryClient();
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);

  const { data: foldersData, isLoading: loadingFolders } = useQuery({
    queryKey: ['captures', 'folders'],
    queryFn: () => getCaptureFolders().then(res => res.data),
  });

  const { data: folderContents, isLoading: loadingContents } = useQuery({
    queryKey: ['captures', 'folder', selectedFolder],
    queryFn: () => getFolderContents(selectedFolder!).then(res => res.data),
    enabled: !!selectedFolder,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteFolder,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['captures'] });
      setSelectedFolder(null);
    },
  });

  const folders = foldersData?.folders ?? [];
  const totalCaptures = foldersData?.total_captures ?? 0;

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Link href="/" className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
                <ArrowLeft className="w-5 h-5 text-gray-600" />
              </Link>
              <Images className="w-8 h-8 text-blue-500" />
              <div>
                <h1 className="text-2xl font-bold text-gray-900">Gallery</h1>
                <p className="text-sm text-gray-500">
                  {totalCaptures} captures in {folders.length} folders
                </p>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        {selectedFolder ? (
          // Folder contents view
          <div>
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setSelectedFolder(null)}
                  className="p-2 hover:bg-gray-200 rounded-lg transition-colors"
                >
                  <ArrowLeft className="w-5 h-5" />
                </button>
                <Folder className="w-6 h-6 text-blue-500" />
                <h2 className="text-xl font-semibold">{selectedFolder}</h2>
              </div>
              
              <button
                onClick={() => {
                  if (confirm(`Delete folder "${selectedFolder}" and all its contents?`)) {
                    deleteMutation.mutate(selectedFolder);
                  }
                }}
                disabled={deleteMutation.isPending}
                className="flex items-center gap-1 px-3 py-1 bg-red-100 text-red-700 rounded hover:bg-red-200 transition-colors"
              >
                {deleteMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Trash2 className="w-4 h-4" />
                )}
                Delete Folder
              </button>
            </div>

            {loadingContents ? (
              <div className="flex justify-center py-12">
                <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
              </div>
            ) : folderContents?.files?.length === 0 ? (
              <div className="text-center py-12 text-gray-500">
                <ImageIcon className="w-12 h-12 mx-auto mb-2 opacity-50" />
                <p>No files in this folder</p>
              </div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {folderContents?.files?.map((file: any) => (
                  <div
                    key={file.name}
                    className="bg-white rounded-lg shadow overflow-hidden group"
                  >
                    <div className="aspect-square bg-gray-200 relative">
                      {/* For RAW files, show placeholder */}
                      {file.name.toLowerCase().endsWith('.arw') || 
                       file.name.toLowerCase().endsWith('.raw') ? (
                        <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-400">
                          <ImageIcon className="w-12 h-12 mb-1" />
                          <span className="text-xs">RAW</span>
                        </div>
                      ) : (
                        <img
                          src={`${API_BASE}${file.url}`}
                          alt={file.name}
                          className="w-full h-full object-cover"
                        />
                      )}
                      
                      {/* Download overlay */}
                      <a
                        href={`${API_BASE}${file.url}`}
                        download={file.name}
                        className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity"
                      >
                        <Download className="w-8 h-8 text-white" />
                      </a>
                    </div>
                    <div className="p-2">
                      <p className="text-xs font-medium truncate">{file.name}</p>
                      <p className="text-xs text-gray-500">
                        {(file.size / 1024 / 1024).toFixed(1)} MB
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          // Folders list view
          <div>
            {loadingFolders ? (
              <div className="flex justify-center py-12">
                <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
              </div>
            ) : folders.length === 0 ? (
              <div className="text-center py-12 text-gray-500">
                <Folder className="w-12 h-12 mx-auto mb-2 opacity-50" />
                <p>No captures yet</p>
                <Link
                  href="/"
                  className="inline-block mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
                >
                  Start Capturing
                </Link>
              </div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {folders.map((folder: FolderInfo) => (
                  <button
                    key={folder.name}
                    onClick={() => setSelectedFolder(folder.name)}
                    className="bg-white rounded-lg shadow p-4 text-left hover:shadow-md transition-shadow"
                  >
                    <div className="flex items-center gap-3 mb-2">
                      <Folder className="w-10 h-10 text-blue-500" />
                      <div>
                        <h3 className="font-medium truncate">{folder.name}</h3>
                        <p className="text-sm text-gray-500">
                          {folder.file_count} files
                        </p>
                      </div>
                    </div>
                    <p className="text-xs text-gray-400">
                      {(folder.total_size / 1024 / 1024).toFixed(1)} MB
                    </p>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
