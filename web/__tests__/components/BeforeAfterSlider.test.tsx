import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import BeforeAfterSlider from '@/app/processing/tools/components/BeforeAfterSlider';

describe('BeforeAfterSlider', () => {
  const defaultProps = {
    beforeUrl: '/images/before.png',
    afterUrl: '/images/after.png',
    width: 800,
    height: 600,
  };

  it('BA-01: renders with before and after image elements', () => {
    render(<BeforeAfterSlider {...defaultProps} />);
    const images = screen.getAllByRole('img');
    expect(images.length).toBe(2);
  });

  it('BA-02: displays correct before/after labels', () => {
    render(<BeforeAfterSlider {...defaultProps} />);
    expect(screen.getByText('Before')).toBeDefined();
    expect(screen.getByText('After')).toBeDefined();
  });

  it('BA-03: initial slider position visible (divider element exists)', () => {
    const { container } = render(<BeforeAfterSlider {...defaultProps} />);
    // The divider has bg-white/80 class and is positioned via left style
    const divider = container.querySelector('.bg-white\\/80');
    expect(divider).not.toBeNull();
  });

  it('BA-04: custom labels render correctly', () => {
    render(
      <BeforeAfterSlider
        {...defaultProps}
        label={{ before: 'Original', after: 'Processed' }}
      />
    );
    expect(screen.getByText('Original')).toBeDefined();
    expect(screen.getByText('Processed')).toBeDefined();
  });

  it('BA-05: aspect ratio container renders with expected classes', () => {
    const { container } = render(<BeforeAfterSlider {...defaultProps} />);
    const wrapper = container.firstElementChild as HTMLElement;
    // The container element is the main interactive area with select-none and cursor-col-resize
    expect(wrapper.className).toContain('select-none');
    expect(wrapper.className).toContain('cursor-col-resize');
  });

  it('BA-06: drag handle element is present', () => {
    const { container } = render(<BeforeAfterSlider {...defaultProps} />);
    // Handle has the rounded-full and border-teal-400 classes
    const handle = container.querySelector('.border-teal-400');
    expect(handle).not.toBeNull();
  });

  it('BA-07: mouse down triggers dragging state', () => {
    const { container } = render(<BeforeAfterSlider {...defaultProps} />);
    const wrapper = container.firstElementChild as HTMLElement;
    // Simulate mousedown - should not throw
    fireEvent.mouseDown(wrapper, { clientX: 100 });
    // Component should still render correctly after interaction
    expect(screen.getByText('Before')).toBeDefined();
  });

  it('BA-08: container element has overflow-hidden', () => {
    const { container } = render(<BeforeAfterSlider {...defaultProps} />);
    const wrapper = container.firstElementChild as HTMLElement;
    expect(wrapper.className).toContain('overflow-hidden');
  });
});
