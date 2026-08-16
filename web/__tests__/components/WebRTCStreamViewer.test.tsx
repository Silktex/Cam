import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { WebRTCStreamViewer } from '@/components/WebRTCStreamViewer';

// Mock api methods
vi.mock('@/lib/api', () => ({
  getWhepStreamUrl: vi.fn(() => 'http://localhost:8000/stream/whep'),
  setLiveViewSource: vi.fn(() => Promise.resolve({ data: { active_source: 'ptp' } })),
}));

describe('WebRTCStreamViewer Component', () => {
  it('renders viewer container and default HDMI source button', () => {
    render(<WebRTCStreamViewer streamSource="hdmi" />);
    const container = screen.getByTestId('webrtc-stream-viewer');
    expect(container).toBeInTheDocument();

    const sourceBtn = screen.getByRole('button', { name: /MacroSilicon/i });
    expect(sourceBtn).toBeInTheDocument();
  });

  it('renders reticle grid by default and toggles correctly', () => {
    const { rerender } = render(<WebRTCStreamViewer gridVisible={true} />);
    const gridCell = document.querySelector('.border-r.border-b.border-white\\/40');
    expect(gridCell).toBeInTheDocument();

    rerender(<WebRTCStreamViewer gridVisible={false} />);
    const hiddenCell = document.querySelector('.border-r.border-b.border-white\\/40');
    expect(hiddenCell).not.toBeInTheDocument();
  });

  it('renders zebra clipping overlay when active', () => {
    const { rerender } = render(<WebRTCStreamViewer zebraVisible={false} />);
    expect(document.querySelector('.zebra-pattern')).not.toBeInTheDocument();

    rerender(<WebRTCStreamViewer zebraVisible={true} />);
    expect(document.querySelector('.zebra-pattern')).toBeInTheDocument();
  });

  it('applies peaking-glow class when focus peaking is enabled', () => {
    const { rerender } = render(<WebRTCStreamViewer peakingVisible={false} />);
    const container = screen.getByTestId('webrtc-stream-viewer');
    expect(container).not.toHaveClass('peaking-glow');

    rerender(<WebRTCStreamViewer peakingVisible={true} />);
    expect(container).toHaveClass('peaking-glow');
  });

  it('calls onSourceChange when source switcher is clicked', () => {
    const handleSourceChange = vi.fn();
    render(<WebRTCStreamViewer streamSource="hdmi" onSourceChange={handleSourceChange} />);
    const sourceBtn = screen.getByRole('button', { name: /MacroSilicon/i });

    fireEvent.click(sourceBtn);
    expect(handleSourceChange).toHaveBeenCalledWith('ptp');
  });

  it('displays frozen snapshot when isFrozen is true', () => {
    render(<WebRTCStreamViewer isFrozen={true} />);
    const frozenImg = screen.getByTestId('frozen-snapshot-img');
    expect(frozenImg).toBeInTheDocument();
  });
});
