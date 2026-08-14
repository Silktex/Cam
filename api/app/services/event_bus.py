"""
Event Bus - Simple pub/sub for WebSocket notifications
"""
import logging
import asyncio
import json
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
        self._state_lock = Lock()
        self._loop = None
        self._pending_sends = set()
        self._initialized = True

    def attach_loop(self, loop):
        with self._state_lock:
            self._loop = loop

    def detach_loop(self, loop=None):
        with self._state_lock:
            if loop is None or self._loop is loop:
                self._loop = None
    
    def subscribe(self, event_type: EventType, callback: Callable):
        """Subscribe to an event type"""
        with self._state_lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)
    
    def unsubscribe(self, event_type: EventType, callback: Callable):
        """Unsubscribe from an event type"""
        with self._state_lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(callback)
                except ValueError:
                    pass
    
    def publish(self, event_type: EventType, data: Dict[str, Any]):
        """Publish an event"""
        logger.debug(f"Event: {event_type.value} - {data}")
        
        # Call local subscribers
        with self._state_lock:
            subscribers = tuple(self._subscribers.get(event_type, ()))
        for callback in subscribers:
            try:
                callback(event_type, data)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
        
        # Queue for WebSocket broadcast
        self._broadcast_to_ws(event_type, data)
    
    def register_ws(self, ws):
        """Register a WebSocket connection"""
        with self._state_lock:
            self._ws_connections.append(ws)
    
    def unregister_ws(self, ws):
        """Unregister a WebSocket connection"""
        with self._state_lock:
            try:
                self._ws_connections.remove(ws)
            except ValueError:
                pass
    
    def _broadcast_to_ws(self, event_type: EventType, data: Dict[str, Any]):
        """Broadcast event to all WebSocket connections"""
        message = json.dumps({
            "type": event_type.value,
            "data": data
        })
        
        with self._state_lock:
            loop = self._loop
            connections = tuple(self._ws_connections)
        if loop is None or loop.is_closed():
            return
        for ws in connections:
            try:
                loop.call_soon_threadsafe(self._schedule_send, ws, message)
            except RuntimeError:
                logger.debug("Event loop closed before WebSocket send was scheduled")

    def _schedule_send(self, ws, message: str):
        task = asyncio.create_task(self._send_ws(ws, message))
        self._pending_sends.add(task)
        task.add_done_callback(self._pending_sends.discard)

    async def _send_ws(self, ws, message: str):
        try:
            await ws.send_text(message)
        except (RuntimeError, ConnectionError):
            self.unregister_ws(ws)


# Global singleton
event_bus = EventBus()
