import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/processing/tools/perspective/[batchName]/page';

vi.mock('@/lib/api', () => ({
  getToolImage: vi.fn(),
  perspectiveDetectLines: vi.fn(),
  perspectivePreview: vi.fn(),
  perspectiveApply: vi.fn(),
  getFullUrl: (p: string) => `http://localhost:8000${p}`,
  CropPoint: undefined,
}));

vi.mock('@/app/processing/tools/components/ToolLayout', () => {
  const React = require('react');
  const ToolLayout = ({ children, sidebar, actionBar, loading, error, toolName }: any) => {
    if (loading) return React.createElement('div', { 'data-testid': 'tool-layout' }, 'Loading...');
    if (error) return React.createElement('div', { 'data-testid': 'tool-layout' }, React.createElement('div', { 'data-testid': 'error' }, error));
    return React.createElement('div', { 'data-testid': 'tool-layout' },
      React.createElement('span', { 'data-testid': 'tool-name' }, toolName),
      React.createElement('div', { 'data-testid': 'sidebar' }, sidebar),
      React.createElement('div', { 'data-testid': 'action-bar' }, actionBar),
      React.createElement('div', { 'data-testid': 'content' }, children),
    );
  };
  ToolLayout.displayName = 'ToolLayout';
  const ActionButton = ({ children, onClick, disabled, loading: btnLoading }: any) =>
    React.createElement('button', { onClick, disabled: disabled || btnLoading, 'data-testid': 'action-btn' }, btnLoading ? 'Processing...' : children);
  return { default: ToolLayout, ActionButton };
});

vi.mock('@/app/processing/tools/components/ParameterCard', () => {
  const React = require('react');
  const ParameterCard = ({ title, children }: any) =>
    React.createElement('div', { 'data-testid': `param-card-${title}` }, children);
  return { default: ParameterCard };
});

vi.mock('@/app/processing/tools/components/DraggableCorners', () => {
  const React = require('react');
  return {
    default: (props: any) => React.createElement('div', { 'data-testid': 'draggable-corners' }),
  };
});

vi.mock('@/app/processing/tools/components/BeforeAfterSlider', () => ({
  default: () => null,
}));

import { getToolImage } from '@/lib/api';

const mockedGetToolImage = getToolImage as ReturnType<typeof vi.fn>;

describe('Perspective Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetToolImage.mockResolvedValue({
      data: {
        preview_url: '/media/preview.jpg',
        width: 2048,
        height: 2048,
      },
    });
  });

  // PP-01: Mounts and loads image
  it('PP-01: mounts and calls getToolImage on init', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(mockedGetToolImage).toHaveBeenCalledWith('test-batch', 'perspective');
    });
  });

  // PP-02: Auto-detect lines button present
  it('PP-02: auto-detect lines button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Auto-detect Lines')).toBeInTheDocument();
    });
  });

  // PP-03: Preview button present
  it('PP-03: preview button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Preview')).toBeInTheDocument();
    });
  });

  // PP-04: Apply button present
  it('PP-04: apply button present', async () => {
    render(<Page />);
    await waitFor(() => {
      // The apply button wraps text in a span with "Apply to All Images"
      expect(screen.getByText('Apply to All Images')).toBeInTheDocument();
    });
  });

  // PP-05: ToolLayout rendered
  it('PP-05: ToolLayout rendered', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('tool-layout')).toBeInTheDocument();
    });
  });

  // PP-06: Loading state displayed
  it('PP-06: loading state displayed', () => {
    render(<Page />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  // PP-07: Corner coordinates display in sidebar
  it('PP-07: corner coordinates display in sidebar', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Top-Left')).toBeInTheDocument();
      expect(screen.getByText('Top-Right')).toBeInTheDocument();
      expect(screen.getByText('Bottom-Right')).toBeInTheDocument();
      expect(screen.getByText('Bottom-Left')).toBeInTheDocument();
    });
  });

  // PP-08: DraggableCorners component rendered
  it('PP-08: DraggableCorners component rendered', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('draggable-corners')).toBeInTheDocument();
    });
  });

  // PP-09: Tool name in layout
  it('PP-09: tool name in layout', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('tool-name')).toHaveTextContent('Perspective Correction');
    });
  });

  // PP-10: Error handling on load failure
  it('PP-10: error handling on load failure', async () => {
    mockedGetToolImage.mockRejectedValue({ response: { data: { detail: 'Not found' } } });
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('error')).toBeInTheDocument();
    });
  });
});
