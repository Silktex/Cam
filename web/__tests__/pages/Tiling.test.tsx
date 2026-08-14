import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/processing/tools/tiling/[batchName]/page';

vi.mock('@/lib/api', () => ({
  getToolImage: vi.fn(),
  tileApply: vi.fn(),
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

describe('Tiling Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetToolImage.mockResolvedValue({
      data: {
        image_url: '/media/tile-source.jpg',
        width: 2048,
        height: 2048,
      },
    });
  });

  // PT-01: Mounts and loads image
  it('PT-01: mounts and calls getToolImage on init', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(mockedGetToolImage).toHaveBeenCalledWith('test-batch', 'tile');
    });
  });

  // PT-02: 2D/3D view toggle buttons present
  it('PT-02: 2D/3D view toggle buttons present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('2D Grid')).toBeInTheDocument();
      expect(screen.getByText('3D Preview')).toBeInTheDocument();
    });
  });

  // PT-03: Tile X/Y sliders present
  it('PT-03: tile X/Y sliders present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByRole('slider', { name: 'Tiles X' })).toBeInTheDocument();
      expect(screen.getByRole('slider', { name: 'Tiles Y' })).toBeInTheDocument();
    });
  });

  // PT-04: Scale slider present
  it('PT-04: scale slider present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByRole('slider', { name: 'Scale' })).toBeInTheDocument();
    });
  });

  // PT-05: Export button present
  it('PT-05: export button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Export Tiled Texture')).toBeInTheDocument();
    });
  });

  // PT-06: ToolLayout rendered
  it('PT-06: ToolLayout rendered', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('tool-layout')).toBeInTheDocument();
    });
  });

  // PT-07: Loading state
  it('PT-07: loading state displayed', () => {
    render(<Page />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  // PT-08: Resolution selector present
  it('PT-08: resolution selector present', async () => {
    render(<Page />);
    await waitFor(() => {
      const select = screen.getByRole('combobox', { name: 'Output Resolution' });
      expect(select).toBeInTheDocument();
    });
    expect(screen.getByText('1024 \u00d7 1024')).toBeInTheDocument();
    expect(screen.getByText('2048 \u00d7 2048')).toBeInTheDocument();
    expect(screen.getByText('4096 \u00d7 4096')).toBeInTheDocument();
  });

  // PT-09: Half-drop toggle present
  it('PT-09: half-drop toggle present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Half Drop' })).toBeInTheDocument();
    });
  });

  // PT-10: Error handling
  it('PT-10: error handling on load failure', async () => {
    mockedGetToolImage.mockRejectedValue(new Error('Failed'));
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('error')).toBeInTheDocument();
    });
  });
});
