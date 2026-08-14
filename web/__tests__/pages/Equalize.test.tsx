import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/processing/tools/equalize/[batchName]/page';

vi.mock('@/lib/api', () => ({
  getToolImage: vi.fn(),
  equalizePreview: vi.fn(),
  equalizeApply: vi.fn(),
  getFullUrl: (p: string) => `http://localhost:8000${p}`,
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
    React.createElement('button', { onClick, disabled: disabled || btnLoading, 'data-testid': `action-btn` }, btnLoading ? 'Processing...' : children);
  return { default: ToolLayout, ActionButton };
});

vi.mock('@/app/processing/tools/components/ParameterCard', () => {
  const React = require('react');
  const ParameterCard = ({ title, description, children }: any) =>
    React.createElement('div', { 'data-testid': `param-card-${title}` }, children);
  const SliderControl = ({ label, value, min, max, step, onChange }: any) =>
    React.createElement('input', { type: 'range', 'aria-label': label, value, min, max, step, onChange: (e: any) => onChange(parseFloat(e.target.value)) });
  const SelectControl = ({ label, value, options, onChange }: any) =>
    React.createElement('select', { 'aria-label': label, value, onChange: (e: any) => onChange(e.target.value) },
      options.map((o: any) => React.createElement('option', { key: o.value, value: o.value }, o.label))
    );
  return { default: ParameterCard, SliderControl, SelectControl };
});

vi.mock('@/app/processing/tools/components/BeforeAfterSlider', () => ({
  default: () => null,
}));

vi.mock('@/app/processing/tools/components/HistogramChart', () => ({
  default: () => null,
}));

import { getToolImage, equalizePreview, equalizeApply } from '@/lib/api';

const mockedGetToolImage = getToolImage as ReturnType<typeof vi.fn>;
const mockedEqualizePreview = equalizePreview as ReturnType<typeof vi.fn>;
const mockedEqualizeApply = equalizeApply as ReturnType<typeof vi.fn>;

describe('Equalize Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetToolImage.mockResolvedValue({
      data: {
        images: ['img001.tiff', 'img002.tiff'],
        preview_url: '/media/preview.jpg',
        image_count: 2,
      },
    });
    mockedEqualizePreview.mockResolvedValue({
      data: { success: true, before_url: '/before.jpg', after_url: '/after.jpg', before_histogram: {}, after_histogram: {} },
    });
    mockedEqualizeApply.mockResolvedValue({
      data: { success: true, processed: 2, total: 2 },
    });
  });

  // PE-01: Mounts and calls getToolImage on init
  it('PE-01: mounts and calls getToolImage on init', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(mockedGetToolImage).toHaveBeenCalledWith('test-batch', 'equalize');
    });
  });

  // PE-02: Shows loading state
  it('PE-02: shows loading state', () => {
    render(<Page />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  // PE-03: Method selector renders with 3 options (CLAHE, histogram_match, exposure_match)
  it('PE-03: method selector renders with 3 options', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('CLAHE (Adaptive)')).toBeInTheDocument();
    });
    expect(screen.getByText('Histogram Match')).toBeInTheDocument();
    expect(screen.getByText('Exposure Match')).toBeInTheDocument();
  });

  // PE-04: CLAHE clip limit slider visible when clahe selected
  it('PE-04: CLAHE clip limit slider visible when clahe selected', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByRole('slider', { name: 'Clip Limit' })).toBeInTheDocument();
    });
  });

  // PE-05: Preview button present
  it('PE-05: preview button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Preview')).toBeInTheDocument();
    });
  });

  // PE-06: Apply button present
  it('PE-06: apply button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Apply to All')).toBeInTheDocument();
    });
  });

  // PE-07: Error display on getToolImage failure
  it('PE-07: error display on getToolImage failure', async () => {
    mockedGetToolImage.mockRejectedValue(new Error('Network error'));
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('error')).toBeInTheDocument();
    });
  });

  // PE-08: Component renders ToolLayout wrapper
  it('PE-08: component renders ToolLayout wrapper', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('tool-layout')).toBeInTheDocument();
    });
  });

  // PE-09: Clip limit slider has correct range
  it('PE-09: clip limit slider has correct range', async () => {
    render(<Page />);
    await waitFor(() => {
      const slider = screen.getByRole('slider', { name: 'Clip Limit' });
      expect(slider).toHaveAttribute('min', '0.5');
      expect(slider).toHaveAttribute('max', '10');
    });
  });

  // PE-10: Apply button initially in correct state (disabled since no previewData)
  it('PE-10: apply button initially disabled', async () => {
    render(<Page />);
    await waitFor(() => {
      const buttons = screen.getAllByTestId('action-btn');
      // Second button is Apply to All, should be disabled (no previewData yet)
      const applyBtn = buttons.find(b => b.textContent === 'Apply to All');
      expect(applyBtn).toBeDisabled();
    });
  });

  // PE-11: Tool name appears in layout
  it('PE-11: tool name appears in layout', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('tool-name')).toHaveTextContent('Equalize');
    });
  });
});
