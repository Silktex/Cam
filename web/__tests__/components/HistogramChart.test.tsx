import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import HistogramChart from '@/app/processing/tools/components/HistogramChart';

describe('HistogramChart', () => {
  const sampleData = {
    r: [0, 10, 50, 100, 50, 10, 0],
    g: [5, 20, 60, 80, 40, 15, 2],
    b: [10, 30, 40, 70, 60, 20, 5],
  };

  it('HC-01: renders SVG element', () => {
    const { container } = render(<HistogramChart data={sampleData} />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
  });

  it('HC-02: renders polygon for each visible channel', () => {
    const { container } = render(
      <HistogramChart data={sampleData} showChannels={['r', 'g', 'b']} />
    );
    const polygons = container.querySelectorAll('polygon');
    expect(polygons.length).toBe(3);
  });

  it('HC-03: channel legend shows correct color indicators', () => {
    render(<HistogramChart data={sampleData} showChannels={['r', 'g', 'b']} />);
    expect(screen.getByText('r')).toBeDefined();
    expect(screen.getByText('g')).toBeDefined();
    expect(screen.getByText('b')).toBeDefined();
  });

  it('HC-04: shows luminance channel when included', () => {
    const dataWithLuminance = {
      ...sampleData,
      luminance: [5, 15, 45, 85, 50, 12, 3],
    };
    const { container } = render(
      <HistogramChart data={dataWithLuminance} showChannels={['r', 'g', 'b', 'luminance']} />
    );
    expect(screen.getByText('luminance')).toBeDefined();
    const polygons = container.querySelectorAll('polygon');
    expect(polygons.length).toBe(4);
  });

  it('HC-05: handles empty/missing data gracefully', () => {
    const emptyData = { r: [], g: [], b: [] };
    const { container } = render(<HistogramChart data={emptyData} />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    const polygons = container.querySelectorAll('polygon');
    expect(polygons.length).toBe(0);
  });

  it('HC-06: uses default dimensions 256x80', () => {
    const { container } = render(<HistogramChart data={sampleData} />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg!.getAttribute('viewBox')).toBe('0 0 256 80');
  });
});
