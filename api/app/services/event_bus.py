"""
Event Bus - Simple pub/sub for WebSocket notifications
"""
import logging
from enum import Enum
from typing import Callable, Dict, List, Any
from threading import Lock

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    CAMERA_CONNECTED = "camera_connected"
    CAMERA_DISCONNECTED = "camera_disconnected"
    CAPTURE_COMPLETE = "capture_complete"
    SETTING_CHANGED = "setting_changed"
    HEALTH_UPDATE = "health_update"
    ERROR = "error"


class EventBus:
    """Simple event bus for internal pub/sub"""
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._ws_connections: List[Any] = []
        self._initialized = True
    
    def subscribe(self, event_type: EventType, callback: Callable):
        """Subscribe to an event type"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
    
    def unsubscribe(self, event_type: EventType, callback: Callable):
        """Unsubscribe from an event type"""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(callback)
            except ValueError:
                pass
    
    def publish(self, event_type: EventType, data: Dict[str, Any]):
        """Publish an event"""
        logger.debug(f"Event: {event_type.value} - {data}")
        
        # Call local subscribers
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    callback(event_type, data)
                except Exception as e:
                    logger.error(f"Event handler error: {e}")
        
        # Queue for WebSocket broadcast
        self._broadcast_to_ws(event_type, data)
    
    def register_ws(self, ws):
        """Register a WebSocket connection"""
        self._ws_connections.append(ws)
    
    def unregister_ws(self, ws):
        """Unregister a WebSocket connection"""
        try:
            self._ws_connections.remove(ws)
        except ValueError:
            pass
    
    def _broadcast_to_ws(self, event_type: EventType, data: Dict[str, Any]):
        """Broadcast event to all WebSocket connections"""
        import asyncio
        import json
        
        message = json.dumps({
            "type": event_type.value,
            "data": data
        })
        
        dead_connections = []
        for ws in self._ws_connections:
            try:
                # Use asyncio to send if we're in async context
                asyncio.create_task(ws.send_text(message))
            except Exception:
                dead_connections.append(ws)
        
        # Clean up dead connections
        for ws in dead_connections:
            self.unregister_ws(ws)


# Global singleton
event_bus = EventBus()
