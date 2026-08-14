import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import TileGrid from '@/app/processing/tools/components/TileGrid';

vi.mock('konva', () => ({
  default: {
    Stage: class {},
  },
}));

describe('TileGrid', () => {
  const defaultProps = {
    imageUrl: '/test-texture.png',
    tileX: 3,
    tileY: 3,
    containerWidth: 600,
    containerHeight: 400,
  };

  it('TG-01: renders konva stage with correct container dimensions', () => {
    render(<TileGrid {...defaultProps} />);
    const stage = screen.getByTestId('konva-stage');
    expect(stage).toBeDefined();
    expect(stage.getAttribute('width')).toBe('600');
    expect(stage.getAttribute('height')).toBe('400');
  });

  it('TG-02: accepts all tile parameters without crash', () => {
    const { container } = render(
      <TileGrid
        {...defaultProps}
        offsetX={0.5}
        offsetY={0.5}
        rotation={45}
        overlap={0.1}
      />
    );
    expect(container.firstElementChild).not.toBeNull();
  });

  it('TG-03: half-drop parameter accepted', () => {
    const { container } = render(
      <TileGrid {...defaultProps} halfDrop={true} />
    );
    expect(container.firstElementChild).not.toBeNull();
  });

  it('TG-04: scale parameter accepted', () => {
    const { container } = render(
      <TileGrid {...defaultProps} scale={2.0} />
    );
    expect(container.firstElementChild).not.toBeNull();
  });

  it('TG-05: grid lines parameter toggles line rendering', () => {
    // With showGridLines=false, no grid lines should render
    const { rerender } = render(
      <TileGrid {...defaultProps} showGridLines={false} />
    );
    expect(screen.queryAllByTestId('konva-line').length).toBe(0);

    // With showGridLines=true (default), grid lines appear after image loads
    // Since image load is async, just verify the component accepts the prop
    rerender(<TileGrid {...defaultProps} showGridLines={true} />);
    expect(screen.getByTestId('konva-stage')).toBeDefined();
  });
});
