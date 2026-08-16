/**
 * Dynamic URL helpers for API and WebSocket connections.
 * Resolves URLs dynamically based on the current window location in the browser
 * to ensure seamless compatibility with reverse proxies, local LAN, and HTTPS/WSS.
 */

export function getApiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    const envUrl = process.env.NEXT_PUBLIC_API_URL;
    // If env var is explicitly configured with a custom domain, respect it;
    // otherwise default to relative path "" so calls route through the current origin/gateway.
    if (envUrl && !envUrl.includes('localhost') && !envUrl.includes('124.123.100.86') && envUrl.trim() !== '') {
      return envUrl;
    }
    // If accessed directly on port 3000 (Next.js standalone without gateway), point API requests to FastAPI port 8000
    if (window.location.port === '3000') {
      return `${window.location.protocol}//${window.location.hostname}:8000`;
    }
    return '';
  }
  return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
}

export function getWebSocketBaseUrl(): string {
  if (typeof window !== 'undefined') {
    const envUrl = process.env.NEXT_PUBLIC_WS_URL;
    if (envUrl && !envUrl.includes('localhost') && !envUrl.includes('124.123.100.86') && envUrl.trim() !== '') {
      return envUrl;
    }
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // If accessed directly on port 3000, connect WebSocket to FastAPI port 8000
    if (window.location.port === '3000') {
      return `${proto}//${window.location.hostname}:8000`;
    }
    return `${proto}//${window.location.host}`;
  }
  return process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
}
