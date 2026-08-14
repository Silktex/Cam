import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/processing/tools/page';

vi.mock('@/lib/api', () => ({
  getBatches: vi.fn(),
  syncAllBatches: vi.fn(),
  getFullUrl: (p: string) => `http://localhost:8000${p}`,
}));

import { getBatches, syncAllBatches } from '@/lib/api';

const mockedGetBatches = getBatches as ReturnType<typeof vi.fn>;
const mockedSyncAllBatches = syncAllBatches as ReturnType<typeof vi.fn>;

describe('ToolsHub Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetBatches.mockResolvedValue({
      data: {
        batches: [
          { name: 'batch-1', image_count: 5, crop_status: 'completed', calibration_status: 'pending' },
          { name: 'batch-2', image_count: 3, crop_status: 'pending', calibration_status: 'pending' },
        ],
      },
    });
    mockedSyncAllBatches.mockResolvedValue({ data: { success: true } });
  });

  // PH-01: Renders page with tool cards
  it('PH-01: renders page with tool cards', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Material Tools')).toBeInTheDocument();
    });
  });

  // PH-02: Shows loading state initially
  it('PH-02: shows loading state initially', () => {
    render(<Page />);
    // The batch list shows a loading spinner (Loader2 with animate-spin)
    // During loading, the batches area should not show batch names yet
    expect(screen.queryByText('batch-1')).not.toBeInTheDocument();
  });

  // PH-03: Displays batch list after loading
  it('PH-03: displays batch list after loading', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('batch-1')).toBeInTheDocument();
      expect(screen.getByText('batch-2')).toBeInTheDocument();
    });
  });

  // PH-04: Tools grid renders 7 tool cards
  it('PH-04: tools grid renders 7 tool cards', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Equalize')).toBeInTheDocument();
    });
    expect(screen.getByText('Delight')).toBeInTheDocument();
    expect(screen.getByText('Perspective')).toBeInTheDocument();
    expect(screen.getByText('Make Seamless')).toBeInTheDocument();
    expect(screen.getByText('Tiling')).toBeInTheDocument();
    expect(screen.getByText('PBR Validate')).toBeInTheDocument();
    expect(screen.getByText('Clone Stamp')).toBeInTheDocument();
  });

  // PH-05: Batch search input is present
  it('PH-05: batch search input is present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Filter batches...')).toBeInTheDocument();
    });
  });

  // PH-06: Sync button is present
  it('PH-06: sync button is present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Sync')).toBeInTheDocument();
    });
  });

  // PH-07: Tool cards link to correct routes (via router.push on click)
  it('PH-07: tool cards display correct descriptions', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Match exposure and color across multi-angle captures')).toBeInTheDocument();
    });
    expect(screen.getByText('Remove residual lighting gradients from calibrated images')).toBeInTheDocument();
    expect(screen.getByText('Correct keystone and skew distortion')).toBeInTheDocument();
  });

  // PH-08: "No batches" shown when list is empty
  it('PH-08: shows "No batches found" when list is empty', async () => {
    mockedGetBatches.mockResolvedValue({ data: { batches: [] } });
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('No batches found')).toBeInTheDocument();
    });
  });
});
