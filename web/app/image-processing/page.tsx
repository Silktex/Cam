'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getImageProcessingBatches, type PipelineBatch } from '@/lib/api';
import dynamic from 'next/dynamic';
import BatchListView from './components/BatchListView';
import EditorLayout from './components/EditorLayout';

const DashboardHeader = dynamic(
  () => import('@/app/all/components/DashboardHeader'),
  { ssr: false }
);

export default function ImageProcessingPage() {
  const [selectedBatch, setSelectedBatch] = useState<string | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['image-processing', 'batches'],
    queryFn: () => getImageProcessingBatches().then((res) => res.data.batches),
  });

  const batches = data || [];

  if (selectedBatch) {
    return (
      <EditorLayout
        batchName={selectedBatch}
        onBack={() => setSelectedBatch(null)}
      />
    );
  }

  return (
    <div className="min-h-screen bg-slate-950">
      <DashboardHeader />
      <BatchListView
        batches={batches}
        isLoading={isLoading}
        onSelect={(name) => setSelectedBatch(name)}
        onSync={() => refetch()}
      />
    </div>
  );
}
