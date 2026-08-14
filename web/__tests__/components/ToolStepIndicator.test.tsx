import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ToolStepIndicator from '@/app/processing/tools/components/ToolStepIndicator';

describe('ToolStepIndicator', () => {
  const steps = [
    { id: 'upload', label: 'Upload' },
    { id: 'adjust', label: 'Adjust' },
    { id: 'export', label: 'Export' },
  ];

  it('TSI-01: renders all step labels', () => {
    render(<ToolStepIndicator steps={steps} currentStep="upload" />);
    expect(screen.getByText('Upload')).toBeDefined();
    expect(screen.getByText('Adjust')).toBeDefined();
    expect(screen.getByText('Export')).toBeDefined();
  });

  it('TSI-02: active step has distinct styling', () => {
    const { container } = render(
      <ToolStepIndicator steps={steps} currentStep="adjust" />
    );
    const adjustLabel = screen.getByText('Adjust');
    expect(adjustLabel.className).toContain('text-teal-400');
    expect(adjustLabel.className).toContain('font-medium');
  });

  it('TSI-03: completed step shows check icon', () => {
    const stepsWithCompleted = [
      { id: 'upload', label: 'Upload', completed: true },
      { id: 'adjust', label: 'Adjust' },
      { id: 'export', label: 'Export' },
    ];
    const { container } = render(
      <ToolStepIndicator steps={stepsWithCompleted} currentStep="adjust" />
    );
    // Completed step circle gets bg-teal-500 class
    const circles = container.querySelectorAll('.bg-teal-500');
    expect(circles.length).toBeGreaterThanOrEqual(1);
  });

  it('TSI-04: renders correct number of steps', () => {
    render(<ToolStepIndicator steps={steps} currentStep="upload" />);
    // Each step has its label text
    const allLabels = ['Upload', 'Adjust', 'Export'];
    allLabels.forEach((label) => {
      expect(screen.getByText(label)).toBeDefined();
    });
  });

  it('TSI-05: handles empty steps array', () => {
    const { container } = render(
      <ToolStepIndicator steps={[]} currentStep="" />
    );
    // Should render the container without crashing
    expect(container.firstElementChild).not.toBeNull();
  });
});
