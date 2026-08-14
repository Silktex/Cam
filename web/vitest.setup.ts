import '@testing-library/jest-dom';
import { vi } from 'vitest';

// ── Mock ResizeObserver (not available in jsdom) ──
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
} as any;

// ── Mock window.matchMedia ──
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// ── Mock HTMLCanvasElement.getContext ──
HTMLCanvasElement.prototype.getContext = ((originalGetContext) => {
  return function (this: HTMLCanvasElement, type: string, ...args: any[]) {
    if (type === '2d') {
      return {
        fillRect: () => {},
        clearRect: () => {},
        getImageData: (x: number, y: number, w: number, h: number) => ({
          data: new Array(w * h * 4).fill(0),
        }),
        putImageData: () => {},
        createImageData: () => [],
        setTransform: () => {},
        drawImage: () => {},
        save: () => {},
        restore: () => {},
        fillText: () => {},
        measureText: () => ({ width: 0 }),
        beginPath: () => {},
        moveTo: () => {},
        lineTo: () => {},
        closePath: () => {},
        stroke: () => {},
        fill: () => {},
        arc: () => {},
        translate: () => {},
        scale: () => {},
        rotate: () => {},
        rect: () => {},
        clip: () => {},
        canvas: this,
        createLinearGradient: () => ({ addColorStop: () => {} }),
        createRadialGradient: () => ({ addColorStop: () => {} }),
        createPattern: () => null,
        globalAlpha: 1,
        globalCompositeOperation: 'source-over',
        lineWidth: 1,
        lineCap: 'butt',
        lineJoin: 'miter',
        strokeStyle: '#000',
        fillStyle: '#000',
        font: '10px sans-serif',
        textAlign: 'start',
        textBaseline: 'alphabetic',
        shadowBlur: 0,
        shadowColor: 'rgba(0,0,0,0)',
        shadowOffsetX: 0,
        shadowOffsetY: 0,
        toDataURL: () => '',
      } as any;
    }
    if (type === 'webgl' || type === 'webgl2') {
      return null; // WebGL not available in test
    }
    return null;
  };
})(HTMLCanvasElement.prototype.getContext);

// ── Mock Image loading ──
Object.defineProperty(global, 'Image', {
  writable: true,
  value: class MockImage {
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    src: string = '';
    width: number = 100;
    height: number = 100;
    naturalWidth: number = 100;
    naturalHeight: number = 100;

    constructor() {
      setTimeout(() => {
        if (this.onload) this.onload();
      }, 0);
    }
  },
});

// ── Mock next/navigation ──
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    prefetch: vi.fn(),
    refresh: vi.fn(),
  }),
  useParams: () => ({
    batchName: 'test-batch',
  }),
  usePathname: () => '/processing/tools',
  useSearchParams: () => new URLSearchParams(),
}));

// ── Mock next/link ──
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => {
    return children;
  },
}));

// ── Mock next/dynamic ──
vi.mock('next/dynamic', () => ({
  default: (loader: () => Promise<any>) => {
    const Component = (props: any) => null;
    Component.displayName = 'DynamicComponent';
    return Component;
  },
}));

// ── Mock react-konva ──
vi.mock('react-konva', () => {
  const React = require('react');
  return {
    Stage: React.forwardRef(({ children, ...props }: any, ref: any) =>
      React.createElement('div', { 'data-testid': 'konva-stage', ref, ...props }, children)
    ),
    Layer: ({ children, ...props }: any) =>
      React.createElement('div', { 'data-testid': 'konva-layer', ...props }, children),
    Image: (props: any) =>
      React.createElement('div', { 'data-testid': 'konva-image', ...props }),
    Circle: (props: any) =>
      React.createElement('div', { 'data-testid': 'konva-circle', ...props }),
    Line: (props: any) =>
      React.createElement('div', { 'data-testid': 'konva-line', ...props }),
    Rect: (props: any) =>
      React.createElement('div', { 'data-testid': 'konva-rect', ...props }),
    Text: (props: any) =>
      React.createElement('div', { 'data-testid': 'konva-text', ...props }),
    Group: ({ children, ...props }: any) =>
      React.createElement('div', { 'data-testid': 'konva-group', ...props }, children),
  };
});

// ── Mock @react-three/fiber ──
vi.mock('@react-three/fiber', () => {
  const React = require('react');
  return {
    Canvas: ({ children, ...props }: any) =>
      React.createElement('div', { 'data-testid': 'r3f-canvas', ...props }, children),
    useFrame: () => {},
    useThree: () => ({ size: { width: 800, height: 600 } }),
    useLoader: () => ({
      wrapS: 0,
      wrapT: 0,
      repeat: { set: () => {} },
    }),
  };
});

// ── Mock @react-three/drei ──
vi.mock('@react-three/drei', () => {
  const React = require('react');
  return {
    OrbitControls: (props: any) =>
      React.createElement('div', { 'data-testid': 'orbit-controls', ...props }),
    Environment: (props: any) =>
      React.createElement('div', { 'data-testid': 'environment', ...props }),
  };
});

// ── Mock axios ──
vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: vi.fn().mockResolvedValue({ data: {} }),
      post: vi.fn().mockResolvedValue({ data: {} }),
      put: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn().mockResolvedValue({ data: {} }),
      interceptors: {
        request: { use: vi.fn() },
        response: { use: vi.fn() },
      },
    }),
  },
}));
