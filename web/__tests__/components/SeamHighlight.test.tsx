import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import SeamHighlight from '@/app/processing/tools/components/SeamHighlight';

vi.mock('konva', () => ({
  default: {
    Stage: class {},
  },
}));

describe('SeamHighlight', () => {
  const defaultProps = {
    imageUrl: '/test-image.png',
    imageWidth: 800,
    imageHeight: 600,
    blendWidth: 32,
    containerWidth: 600,
    containerHeight: 400,
  };

  const seamScores = {
    top: 5.2,
    bottom: 25.1,
    left: 8.7,
    right: 45.3,
  };

  it('SH-01: renders konva stage', () => {
    render(<SeamHighlight {...defaultProps} />);
    expect(screen.getByTestId('konva-stage')).toBeDefined();
  });

  it('SH-02: renders 4 edge highlight rectangles', () => {
    render(<SeamHighlight {...defaultProps} />);
    const rects = screen.getAllByTestId('konva-rect');
    expect(rects.length).toBe(4);
  });

  it('SH-03: renders image element', () => {
    // Image loads async, but stage structure should be present
    render(<SeamHighlight {...defaultProps} />);
    expect(screen.getByTestId('konva-layer')).toBeDefined();
  });

  it('SH-04: accepts seamScores prop without crash', () => {
    const { container } = render(
      <SeamHighlight {...defaultProps} seamScores={seamScores} />
    );
    expect(container.firstElementChild).not.toBeNull();
  });

  it('SH-05: renders without seamScores (default colors)', () => {
    const { container } = render(<SeamHighlight {...defaultProps} />);
    expect(container.firstElementChild).not.toBeNull();
    // Score badge texts should not be present without seamScores
    expect(screen.queryAllByTestId('konva-text').length).toBe(0);
  });

  it('SH-06: score badges display when seamScores provided', () => {
    render(<SeamHighlight {...defaultProps} seamScores={seamScores} />);
    const texts = screen.getAllByTestId('konva-text');
    // 4 score badges: top, bottom, left, right
    expect(texts.length).toBe(4);
  });

  it('SH-07: container has correct dimensions', () => {
    render(<SeamHighlight {...defaultProps} />);
    const stage = screen.getByTestId('konva-stage');
    expect(stage.getAttribute('width')).toBe('600');
    expect(stage.getAttribute('height')).toBe('400');
  });
});
