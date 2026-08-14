import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/processing/tools/delight/[batchName]/page';

vi.mock('@/lib/api', () => ({
  getToolImage: vi.fn(),
  delightPreview: vi.fn(),
  delightApply: vi.fn(),
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
    React.createElement('button', { onClick, disabled: disabled || btnLoading, 'data-testid': 'action-btn' }, btnLoading ? 'Processing...' : children);
  return { default: ToolLayout, ActionButton };
});

vi.mock('@/app/processing/tools/components/ParameterCard', () => {
  const React = require('react');
  const ParameterCard = ({ title, children }: any) =>
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

import { getToolImage, delightPreview, delightApply } from '@/lib/api';

const mockedGetToolImage = getToolImage as ReturnType<typeof vi.fn>;

describe('Delight Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetToolImage.mockResolvedValue({
      data: {
        preview_url: '/media/preview.jpg',
        image_count: 4,
      },
    });
  });

  // PD-01: Mounts and loads image
  it('PD-01: mounts and calls getToolImage on init', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(mockedGetToolImage).toHaveBeenCalledWith('test-batch', 'delight');
    });
  });

  // PD-02: Method selector has 2 options
  it('PD-02: method selector has 2 options', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Gaussian (Fast)')).toBeInTheDocument();
    });
    expect(screen.getByText('Frequency Separation')).toBeInTheDocument();
  });

  // PD-03: Strength slider present with range 0-100
  it('PD-03: strength slider present with range 0-100', async () => {
    render(<Page />);
    await waitFor(() => {
      const slider = screen.getByRole('slider', { name: 'Strength' });
      expect(slider).toBeInTheDocument();
      expect(slider).toHaveAttribute('min', '0');
      expect(slider).toHaveAttribute('max', '100');
    });
  });

  // PD-04: Blur radius slider present
  it('PD-04: blur radius slider present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByRole('slider', { name: 'Blur Radius' })).toBeInTheDocument();
    });
  });

  // PD-05: Preview button present
  it('PD-05: preview button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Preview')).toBeInTheDocument();
    });
  });

  // PD-06: Apply button present
  it('PD-06: apply button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Apply to All')).toBeInTheDocument();
    });
  });

  // PD-07: ToolLayout rendered
  it('PD-07: ToolLayout rendered', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('tool-layout')).toBeInTheDocument();
    });
  });

  // PD-08: Loading state displayed
  it('PD-08: loading state displayed', () => {
    render(<Page />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  // PD-09: Tool name in layout
  it('PD-09: tool name in layout', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('tool-name')).toHaveTextContent('Delight');
    });
  });

  // PD-10: Error handling on load failure
  it('PD-10: error handling on load failure', async () => {
    mockedGetToolImage.mockRejectedValue(new Error('Failed'));
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('error')).toBeInTheDocument();
    });
  });
});
