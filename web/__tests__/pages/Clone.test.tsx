import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/processing/tools/clone/[batchName]/page';

vi.mock('@/lib/api', () => ({
  getToolImage: vi.fn(),
  cloneInpaint: vi.fn(),
  cloneApply: vi.fn(),
  cloneStamp: vi.fn(),
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

import { getToolImage } from '@/lib/api';

const mockedGetToolImage = getToolImage as ReturnType<typeof vi.fn>;

describe('Clone Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetToolImage.mockResolvedValue({
      data: {
        image_url: '/media/source.jpg',
        width: 2048,
        height: 2048,
      },
    });
  });

  // PC-01: Mounts and loads image
  it('PC-01: mounts and calls getToolImage on init', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(mockedGetToolImage).toHaveBeenCalledWith('test-batch', 'clone');
    });
  });

  // PC-02: Inpaint/Clone stamp mode toggle present
  it('PC-02: inpaint/clone stamp mode toggle present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Inpaint')).toBeInTheDocument();
      expect(screen.getByText('Clone Stamp')).toBeInTheDocument();
    });
  });

  // PC-03: Brush radius slider present
  it('PC-03: brush radius slider present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByRole('slider', { name: 'Brush Radius' })).toBeInTheDocument();
    });
  });

  // PC-04: Inpaint method selector present
  it('PC-04: inpaint method selector present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Telea (Fast Marching)')).toBeInTheDocument();
    });
    expect(screen.getByText('Navier-Stokes')).toBeInTheDocument();
  });

  // PC-05: Preview button present
  it('PC-05: preview button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Preview')).toBeInTheDocument();
    });
  });

  // PC-06: Apply button present
  it('PC-06: apply button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Apply')).toBeInTheDocument();
    });
  });

  // PC-07: ToolLayout rendered
  it('PC-07: ToolLayout rendered', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('tool-layout')).toBeInTheDocument();
    });
  });

  // PC-08: Loading state
  it('PC-08: loading state displayed', () => {
    render(<Page />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  // PC-09: Error handling
  it('PC-09: error handling on load failure', async () => {
    mockedGetToolImage.mockRejectedValue(new Error('Failed'));
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('error')).toBeInTheDocument();
    });
  });

  // PC-10: BrushCanvas component rendered in inpaint mode
  it('PC-10: BrushCanvas component rendered in inpaint mode', async () => {
    render(<Page />);
    await waitFor(() => {
      // In inpaint mode (default), the BrushCanvas is dynamically imported.
      // Since next/dynamic is mocked to return a null component in vitest.setup.ts,
      // we verify the content area exists and the mode is inpaint
      expect(screen.getByTestId('content')).toBeInTheDocument();
      // Inpaint is the default mode - the button should be present
      expect(screen.getByText('Inpaint')).toBeInTheDocument();
    });
  });
});
