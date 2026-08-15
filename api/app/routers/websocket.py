"""
WebSocket Router - Real-time events
"""
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.services.event_bus import event_bus

router = APIRouter()


@router.websocket("/events")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time camera events.
    
    Events:
    - camera_connected: Camera connected
    - camera_disconnected: Camera disconnected
    - capture_complete: Image captured
    - setting_changed: Camera setting changed
    - health_update: Health status changed
    - error: Error occurred
    """
    await websocket.accept()
    session_id = uuid.uuid4().hex[:8]
    bind_contextvars(session_id=session_id, ws_type="events")
    event_bus.register_ws(websocket)
    
    try:
        # Send initial status
        from app.services.camera_service import camera_service
        await websocket.send_json({
            "type": "connected",
            "data": {
                "camera_connected": camera_service.is_connected,
                "model": camera_service.model,
            }
        })
        
        # Keep connection alive and wait for messages
        while True:
            try:
                # Receive messages (ping/pong or commands)
                data = await websocket.receive_text()
                message = json.loads(data)
                
                # Handle ping
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                
            except json.JSONDecodeError:
                pass
                
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unregister_ws(websocket)
        clear_contextvars()
