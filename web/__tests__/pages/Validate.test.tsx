import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/processing/tools/validate/[batchName]/page';

vi.mock('@/lib/api', () => ({
  pbrValidateCheck: vi.fn(),
  pbrValidateStats: vi.fn(),
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

vi.mock('@/app/processing/tools/components/HistogramChart', () => ({
  default: () => null,
}));

import { pbrValidateStats } from '@/lib/api';

const mockedPbrValidateStats = pbrValidateStats as ReturnType<typeof vi.fn>;

describe('Validate Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedPbrValidateStats.mockResolvedValue({
      data: {
        success: true,
        maps: {
          albedo: {
            filename: 'albedo.tiff',
            thumbnail_url: '/media/albedo-thumb.jpg',
            histogram: { r: [1, 2, 3], g: [1, 2, 3], b: [1, 2, 3] },
            min: 20,
            max: 230,
            mean: 125,
          },
          normal: {
            filename: 'normal.tiff',
            thumbnail_url: '/media/normal-thumb.jpg',
            histogram: { r: [1, 2, 3], g: [1, 2, 3], b: [1, 2, 3] },
            r_min: 100,
            r_max: 200,
            r_mean: 150,
            g_min: 100,
            g_max: 200,
            g_mean: 150,
            b_min: 100,
            b_max: 200,
            b_mean: 150,
          },
        },
      },
    });
  });

  // PV-01: Mounts and loads PBR stats
  it('PV-01: mounts and calls pbrValidateStats on init', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(mockedPbrValidateStats).toHaveBeenCalledWith('test-batch');
    });
  });

  // PV-02: Validation mode selector present
  it('PV-02: validation mode selector present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Albedo Range')).toBeInTheDocument();
    });
    expect(screen.getByText('Metallic Range')).toBeInTheDocument();
    expect(screen.getByText('Both')).toBeInTheDocument();
  });

  // PV-03: Dark threshold slider present
  it('PV-03: dark threshold slider present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByRole('slider', { name: 'Dark Threshold' })).toBeInTheDocument();
    });
  });

  // PV-04: Validate button present
  it('PV-04: validate button present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByText('Validate')).toBeInTheDocument();
    });
  });

  // PV-05: Show overlay toggle present
  it('PV-05: show overlay toggle present', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Show Overlay' })).toBeInTheDocument();
    });
  });

  // PV-06: ToolLayout rendered
  it('PV-06: ToolLayout rendered', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('tool-layout')).toBeInTheDocument();
    });
  });

  // PV-07: Loading state
  it('PV-07: loading state displayed', () => {
    render(<Page />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  // PV-08: Map grid displayed
  it('PV-08: map grid displayed with map stats', async () => {
    render(<Page />);
    await waitFor(() => {
      // The page renders ParameterCard for each map's stats with title like "Albedo Stats"
      expect(screen.getByTestId('param-card-Albedo Stats')).toBeInTheDocument();
      expect(screen.getByTestId('param-card-Normal Stats')).toBeInTheDocument();
    });
  });

  // PV-09: Error handling
  it('PV-09: error handling on load failure', async () => {
    mockedPbrValidateStats.mockRejectedValue(new Error('Failed'));
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('error')).toBeInTheDocument();
    });
  });

  // PV-10: Tool name in layout
  it('PV-10: tool name in layout', async () => {
    render(<Page />);
    await waitFor(() => {
      expect(screen.getByTestId('tool-name')).toHaveTextContent('PBR Validate');
    });
  });
});
