import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ToolLayout, { ActionButton } from '@/app/processing/tools/components/ToolLayout';

describe('ToolLayout', () => {
  const defaultProps = {
    batchName: 'test-batch',
    toolName: 'Equalize',
    children: <div>Main Content</div>,
    sidebar: <div>Sidebar Content</div>,
  };

  it('TL-01: renders breadcrumb with Processing > Tools > toolName', () => {
    const { container } = render(<ToolLayout {...defaultProps} />);
    // The breadcrumb area contains Processing, /, Tools, /, and toolName.
    // next/link mock returns children directly (no anchor), so text nodes
    // are bare inside parent divs. Verify breadcrumb content via container text.
    const breadcrumbArea = container.querySelector('.flex.items-center.gap-3');
    expect(breadcrumbArea).not.toBeNull();
    expect(breadcrumbArea!.textContent).toContain('Processing');
    expect(breadcrumbArea!.textContent).toContain('Tools');
    expect(breadcrumbArea!.textContent).toContain('Equalize');
  });

  it('TL-02: shows loading spinner when loading=true', () => {
    const { container } = render(<ToolLayout {...defaultProps} loading={true} />);
    // The Loader2 icon renders with animate-spin class
    const spinner = container.querySelector('.animate-spin');
    expect(spinner).not.toBeNull();
    // Main content should not be visible
    expect(screen.queryByText('Main Content')).toBeNull();
  });

  it('TL-03: shows error message when error is set', () => {
    render(<ToolLayout {...defaultProps} error="Something went wrong" />);
    expect(screen.getByText('Something went wrong')).toBeDefined();
    expect(screen.getByText('Back to Processing')).toBeDefined();
  });

  it('TL-04: renders children in main area', () => {
    render(<ToolLayout {...defaultProps} />);
    expect(screen.getByText('Main Content')).toBeDefined();
  });

  it('TL-05: renders sidebar content', () => {
    render(<ToolLayout {...defaultProps} />);
    expect(screen.getByText('Sidebar Content')).toBeDefined();
  });

  it('TL-06: action bar renders when provided', () => {
    render(<ToolLayout {...defaultProps} actionBar={<button>Apply</button>} />);
    expect(screen.getByText('Apply')).toBeDefined();
  });

  it('TL-07: batch name displayed decoded from URL encoding', () => {
    render(<ToolLayout {...defaultProps} batchName="my%20batch%20name" />);
    expect(screen.getByText('my batch name')).toBeDefined();
  });

  it('TL-08: ActionButton shows Processing text when loading=true', () => {
    render(<ActionButton onClick={() => {}} loading={true}>Apply</ActionButton>);
    expect(screen.getByText('Processing...')).toBeDefined();
    expect(screen.queryByText('Apply')).toBeNull();
  });

  it('TL-09: ActionButton disabled when disabled=true', () => {
    render(<ActionButton onClick={() => {}} disabled={true}>Apply</ActionButton>);
    const button = screen.getByRole('button');
    expect(button).toBeDisabled();
  });
});
