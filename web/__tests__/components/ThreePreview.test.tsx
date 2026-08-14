import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ThreePreview from '@/app/processing/tools/components/ThreePreview';

// Mock three.js module
vi.mock('three', () => ({
  TextureLoader: class {},
  RepeatWrapping: 1000,
  DoubleSide: 2,
  Mesh: class {},
  Texture: class {},
}));

describe('ThreePreview', () => {
  const defaultProps = {
    textureUrl: '/textures/albedo.png',
  };

  it('TP-01: component mounts without crashing', () => {
    const { container } = render(<ThreePreview {...defaultProps} />);
    expect(container.firstElementChild).not.toBeNull();
  });

  it('TP-02: canvas element present in DOM', () => {
    render(<ThreePreview {...defaultProps} />);
    expect(screen.getByTestId('r3f-canvas')).toBeDefined();
  });

  it('TP-03: accepts all optional map URL props', () => {
    const { container } = render(
      <ThreePreview
        {...defaultProps}
        normalMapUrl="/textures/normal.png"
        roughnessMapUrl="/textures/roughness.png"
        heightMapUrl="/textures/height.png"
      />
    );
    expect(container.firstElementChild).not.toBeNull();
  });

  it('TP-04: geometry prop accepted (plane/cylinder)', () => {
    const { rerender, container } = render(
      <ThreePreview {...defaultProps} geometry="plane" />
    );
    expect(container.firstElementChild).not.toBeNull();

    rerender(<ThreePreview {...defaultProps} geometry="cylinder" />);
    expect(container.firstElementChild).not.toBeNull();
  });
});
