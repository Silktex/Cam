import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/processing/tools/seamless/[batchName]/page';

vi.mock('@/lib/api', () => ({
  getToolImage: vi.fn(),
  seamlessAnalyze: vi.fn(),
  seamlessPreview: vi.fn(),
  seamlessApply: vi.fn(),
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
  const ToggleControl = ({ label, value, onChange }: any) =>
    React.createElement('button', { 'aria-label': label, role: 'switch', 'aria-checked': value, onClick: () => onChange(!value) }, label);
  return { default: ParameterCard, SliderControl, SelectControl, ToggleControl };
});

vi.mock('@/app/processing/tools/components/SeamHighlight', () => {
  const React = require('react');
  return {
    default: () => React.createElement('div', { 'data-testid': 'seam-highlight' }),
  };
});

import { getToolImage } from '@/lib/api';

const mockedGetToolImage = getToolImage as ReturnType<typeof vi.fn>;

describe('Seamless Page', () => {
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

  // PS-01: Mounts and loads image
  it('PS-01: mounts and calls getToolImage on init', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(mockedGetToolImage).toHaveBeenCalledWith('test-batch', 'seamless');
    });
  });

  // PS-02: Method selector has 3 options
  it('PS-02: method selector has 3 options', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Overlay (Shifted blend)')).toBeInTheDocument();
    });
    expect(screen.getByText('Mirror (Edge fold)')).toBeInTheDocument();
    expect(screen.getByText('Poisson (Gradient domain)')).toBeInTheDocument();
  });

  // PS-03: Blend width slider present
  it('PS-03: blend width slider present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByRole('slider', { name: 'Blend Width' })).toBeInTheDocument();
    });
  });

  // PS-04: Spots removal toggle present
  it('PS-04: spots removal toggle present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Spots Removal' })).toBeInTheDocument();
    });
  });

  // PS-05: Analyze seams button present
  it('PS-05: analyze seams button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Analyze Seams')).toBeInTheDocument();
    });
  });

  // PS-06: Preview button present
  it('PS-06: preview button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Generate Preview')).toBeInTheDocument();
    });
  });

  // PS-07: Apply button present
  it('PS-07: apply button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Apply to All Images')).toBeInTheDocument();
    });
  });

  // PS-08: ToolLayout rendered
  it('PS-08: ToolLayout rendered', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('tool-layout')).toBeInTheDocument();
    });
  });

  // PS-09: Loading state
  it('PS-09: loading state displayed', () => {
    render(<Page />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  // PS-10: Error handling
  it('PS-10: error handling on load failure', async () => {
    mockedGetToolImage.mockRejectedValue({ response: { data: { detail: 'Not found' } } });
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('error')).toBeInTheDocument();
    });
  });
});
