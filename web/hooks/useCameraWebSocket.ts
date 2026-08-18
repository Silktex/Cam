import { useEffect, useRef, useState, useCallback } from 'react';
import { getWebSocketBaseUrl } from '@/lib/urlHelpers';
import { getCameraStatus } from '@/lib/api';

interface CameraWsStatus {
  connected: boolean;
  model: string | null;
}

interface WebSocketMessage {
  type: 'connected' | 'camera_connected' | 'camera_disconnected' | 'setting_changed' | 'health_update' | 'capture_complete' | 'error' | 'pong';
  data: Record<string, any>;
}

/**
 * Subscribes to the backend's existing /api/ws/events broadcast (camera
 * connect/disconnect, worker-recovery errors) instead of polling
 * /api/camera/status on an interval (#3). Mirrors useLightsWebSocket's
 * connect/reconnect shape for consistency with the other realtime hook.
 */
export function useCameraWebSocket() {
  const [status, setStatus] = useState<CameraWsStatus | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const connect = useCallback(() => {
    const wsUrl = getWebSocketBaseUrl();

    try {
      wsRef.current = new WebSocket(`${wsUrl}/api/ws/events`);

      wsRef.current.onopen = () => {
        setWsConnected(true);

        pingIntervalRef.current = setInterval(() => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'ping' }));
          }
        }, 30000);
      };

      wsRef.current.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);

          switch (message.type) {
            case 'connected':
              setStatus({
                connected: !!message.data.camera_connected,
                model: message.data.model ?? null,
              });
              break;

            case 'camera_connected':
              setStatus({ connected: true, model: message.data?.model ?? null });
              break;

            case 'camera_disconnected':
              setStatus({ connected: false, model: null });
              break;

            case 'error':
              console.error('Camera event error:', message.data?.message);
              setLastError(message.data?.message ?? 'Camera error');
              break;
          }
        } catch (e) {
          console.error('Failed to parse camera WebSocket message:', e);
        }
      };

      wsRef.current.onclose = () => {
        setWsConnected(false);

        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
        }

        reconnectTimeoutRef.current = setTimeout(connect, 3000);
      };

      wsRef.current.onerror = (error) => {
        console.error('Camera WebSocket error:', error);
      };
    } catch (e) {
      console.error('Failed to connect camera WebSocket:', e);
      reconnectTimeoutRef.current = setTimeout(connect, 3000);
    }
  }, []);

  useEffect(() => {
    // One-shot initial fetch, not a poll: seeds state immediately in case the
    // WS handshake is slow or unreachable (proxy/deployment quirk); the WS
    // message stream above takes over for every update after that (#3).
    getCameraStatus()
      .then((res) => setStatus((prev) => prev ?? { connected: res.data.connected, model: res.data.model ?? null }))
      .catch(() => {});

    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return { status, wsConnected, lastError };
}
