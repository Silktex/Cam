import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { WebRTCStreamViewer } from '@/components/WebRTCStreamViewer';

// Mock api methods
vi.mock('@/lib/api', () => ({
  getWhepStreamUrl: vi.fn(() => 'http://localhost:8000/stream/whep'),
  getLiveViewUrl: vi.fn(() => 'http://localhost:8000/api/liveview/stream'),
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

describe('WebRTCStreamViewer unmount cleanup', () => {
  class MockRTCRtpTransceiver {
    stop = vi.fn();
  }

  function installWebRtcGlobals() {
    const instances: MockRTCPeerConnection[] = [];
    class MockRTCPeerConnection {
      connectionState: RTCPeerConnectionState = 'new';
      ontrack: ((event: unknown) => void) | null = null;
      onconnectionstatechange: (() => void) | null = null;
      transceivers = [new MockRTCRtpTransceiver(), new MockRTCRtpTransceiver()];
      addTransceiver = vi.fn(() => this.transceivers[0]);
      createOffer = vi.fn(async () => ({ type: 'offer' as const, sdp: 'offer-sdp' }));
      setLocalDescription = vi.fn(async () => {});
      setRemoteDescription = vi.fn(async () => {});
      getTransceivers = vi.fn(() => this.transceivers);
      close = vi.fn(() => {
        this.connectionState = 'closed';
      });
      constructor() {
        instances.push(this);
      }
    }
    vi.stubGlobal('RTCPeerConnection', MockRTCPeerConnection);
    vi.stubGlobal(
      'RTCSessionDescription',
      class {
        type: string;
        sdp: string;
        constructor(init: { type: string; sdp: string }) {
          this.type = init.type;
          this.sdp = init.sdp;
        }
      }
    );
    return instances;
  }

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('stops transceivers, closes peer connection and cancels pending retry timer on unmount', async () => {
    vi.useFakeTimers();
    const instances = installWebRtcGlobals();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        headers: { get: () => null },
        text: async () => 'answer-sdp',
      }))
    );

    const { unmount } = render(<WebRTCStreamViewer streamSource="hdmi" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(instances).toHaveLength(1);
    const pc = instances[0];
    expect(pc.close).not.toHaveBeenCalled();

    // Simulate connection failure -> component schedules a 4s retry timer
    act(() => {
      pc.connectionState = 'failed';
      pc.onconnectionstatechange?.();
    });

    unmount();

    // Hard teardown on unmount: transceivers stopped, pc closed
    for (const transceiver of pc.getTransceivers()) {
      expect(transceiver.stop).toHaveBeenCalled();
    }
    expect(pc.close).toHaveBeenCalledTimes(1);

    // Retry timer cleared: no reconnect attempt fires after unmount
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(instances).toHaveLength(1);
  });

  it('does not schedule a retry or reconnect when an in-flight WHEP attempt fails after unmount', async () => {
    vi.useFakeTimers();
    const instances = installWebRtcGlobals();
    let rejectFetch: (err: Error) => void = () => {};
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise((_resolve, reject) => {
            rejectFetch = reject;
          })
      )
    );

    const { unmount } = render(<WebRTCStreamViewer streamSource="hdmi" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(instances).toHaveLength(1);
    const pc = instances[0];
    expect(pc.close).not.toHaveBeenCalled();

    unmount();
    expect(pc.close).toHaveBeenCalledTimes(1);

    // In-flight signaling fails after unmount -> no 5s retry timer may be scheduled
    await act(async () => {
      rejectFetch(new Error('signaling gone'));
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(instances).toHaveLength(1);
  });
});
