import { useEffect, useRef, useState, useCallback } from 'react';
import { getWebSocketBaseUrl } from '@/lib/urlHelpers';

interface LightState {
  id: number;
  name: string;
  pin: number;
  on: boolean;
  brightness: number;
}

interface LightsData {
  lights: LightState[];
  connected: boolean;
  host: string;
}

interface HealthData {
  status: string;
  connected: boolean;
  host: string;
  port: number;
  total_lights: number;
  message?: string;
}

interface WebSocketMessage {
  type: 'state_update' | 'health' | 'pong' | 'error';
  data: LightsData | HealthData | { message: string };
}

export function useLightsWebSocket() {
  const [lights, setLights] = useState<LightState[]>([]);
  const [connected, setConnected] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [esp32Host, setEsp32Host] = useState('');
  const [health, setHealth] = useState<HealthData | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const connect = useCallback(() => {
    const wsUrl = getWebSocketBaseUrl();
    
    try {
      wsRef.current = new WebSocket(`${wsUrl}/ws/lights`);

      wsRef.current.onopen = () => {
        console.log('WebSocket connected');
        setWsConnected(true);
        
        // Start ping interval
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
            case 'state_update':
              const stateData = message.data as LightsData;
              setLights(stateData.lights);
              setConnected(stateData.connected);
              setEsp32Host(stateData.host);
              break;
              
            case 'health':
              setHealth(message.data as HealthData);
              break;
              
            case 'error':
              console.error('WebSocket error:', (message.data as { message: string }).message);
              break;
              
            case 'pong':
              // Keep-alive response
              break;
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };

      wsRef.current.onclose = () => {
        console.log('WebSocket disconnected');
        setWsConnected(false);
        
        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
        }
        
        // Reconnect after 3 seconds
        reconnectTimeoutRef.current = setTimeout(connect, 3000);
      };

      wsRef.current.onerror = (error) => {
        console.error('WebSocket error:', error);
      };
    } catch (e) {
      console.error('Failed to connect WebSocket:', e);
      // Retry after 3 seconds
      reconnectTimeoutRef.current = setTimeout(connect, 3000);
    }
  }, []);

  useEffect(() => {
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

  const setLight = useCallback((id: number, on: boolean, brightness?: number) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'set_light',
        data: { id, on, brightness }
      }));
    }
  }, []);

  const setAllLights = useCallback((on: boolean, brightness?: number) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'set_all',
        data: { on, brightness }
      }));
    }
  }, []);

  const requestState = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'get_state' }));
    }
  }, []);

  const requestHealth = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'get_health' }));
    }
  }, []);

  return {
    lights,
    connected,
    wsConnected,
    esp32Host,
    health,
    setLight,
    setAllLights,
    requestState,
    requestHealth
  };
}
