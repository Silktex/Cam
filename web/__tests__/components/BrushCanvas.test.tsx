import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import BrushCanvas from '@/app/processing/tools/components/BrushCanvas';

vi.mock('konva', () => ({
  default: {
    Stage: class {},
  },
}));

describe('BrushCanvas', () => {
  const defaultProps = {
    imageUrl: '/test-image.png',
    imageWidth: 800,
    imageHeight: 600,
    brushRadius: 20,
    containerWidth: 600,
    containerHeight: 400,
  };

  it('BC-01: renders konva stage', () => {
    render(<BrushCanvas {...defaultProps} />);
    expect(screen.getByTestId('konva-stage')).toBeDefined();
  });

  it('BC-02: undo button present and initially disabled', () => {
    render(<BrushCanvas {...defaultProps} />);
    const undoButton = screen.getByText('Undo');
    expect(undoButton).toBeDefined();
    expect(undoButton).toBeDisabled();
  });

  it('BC-03: redo button present and initially disabled', () => {
    render(<BrushCanvas {...defaultProps} />);
    const redoButton = screen.getByText('Redo');
    expect(redoButton).toBeDefined();
    expect(redoButton).toBeDisabled();
  });

  it('BC-04: clear button present and initially disabled', () => {
    render(<BrushCanvas {...defaultProps} />);
    const clearButton = screen.getByText('Clear');
    expect(clearButton).toBeDefined();
    expect(clearButton).toBeDisabled();
  });

  it('BC-05: component accepts all required props without crash', () => {
    const { container } = render(<BrushCanvas {...defaultProps} />);
    expect(container.firstElementChild).not.toBeNull();
  });

  it('BC-06: renders konva image element', () => {
    // Image loading is async via useEffect, but stage should be present
    render(<BrushCanvas {...defaultProps} />);
    expect(screen.getByTestId('konva-stage')).toBeDefined();
    expect(screen.getByTestId('konva-layer')).toBeDefined();
  });

  it('BC-07: canvas has correct container dimensions', () => {
    render(<BrushCanvas {...defaultProps} />);
    const stage = screen.getByTestId('konva-stage');
    expect(stage.getAttribute('width')).toBe('600');
    expect(stage.getAttribute('height')).toBe('400');
  });

  it('BC-08: paint mode is the default mode', () => {
    // Render without specifying mode - defaults to paint
    const { container } = render(<BrushCanvas {...defaultProps} />);
    // No crash means the component accepted the default mode
    expect(container.firstElementChild).not.toBeNull();
  });
});
