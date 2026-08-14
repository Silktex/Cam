'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, createContext, useContext, useEffect, useRef, ReactNode } from 'react';

// WebSocket Context
type WSStatus = 'connecting' | 'connected' | 'disconnected';

interface WSContextType {
  status: WSStatus;
  lastMessage: any;
}

const WSContext = createContext<WSContextType>({
  status: 'disconnected',
  lastMessage: null,
});

export function useWebSocket() {
  return useContext(WSContext);
}

// Providers Component
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: 2,
      },
    },
  }));
  
  const [wsStatus, setWsStatus] = useState<WSStatus>('disconnected');
  const [lastMessage, setLastMessage] = useState<any>(null);
  const wsRef = useRef<WebSocket | null>(null);
  
  useEffect(() => {
    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const WS_URL = API_URL.replace('http', 'ws') + '/api/ws/events';
    
    function connect() {
      setWsStatus('connecting');
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      
      ws.onopen = () => {
        setWsStatus('connected');
        console.log('WebSocket connected');
      };
      
      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          setLastMessage(message);
          
          // Invalidate queries based on event type
          if (message.type === 'capture_complete') {
            queryClient.invalidateQueries({ queryKey: ['captures'] });
          } else if (message.type === 'camera_connected' || message.type === 'camera_disconnected') {
            queryClient.invalidateQueries({ queryKey: ['camera'] });
            queryClient.invalidateQueries({ queryKey: ['health'] });
          } else if (message.type === 'setting_changed') {
            queryClient.invalidateQueries({ queryKey: ['settings'] });
          }
        } catch (e) {
          console.error('WS message parse error:', e);
        }
      };
      
      ws.onclose = () => {
        setWsStatus('disconnected');
        console.log('WebSocket disconnected, reconnecting in 3s...');
        setTimeout(connect, 3000);
      };
      
      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        ws.close();
      };
    }
    
    connect();
    
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [queryClient]);
  
  return (
    <WSContext.Provider value={{ status: wsStatus, lastMessage }}>
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    </WSContext.Provider>
  );
}
