"""
Light Controller WebSocket Router
Provides real-time state updates for lights.
"""
import asyncio
import logging
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.services.light_service import light_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/lights")
async def lights_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time light state updates.
    
    Messages sent to client:
    - type: "state_update" - Full state of all lights
    - type: "health" - Health status updates
    
    Messages from client:
    - type: "ping" - Keep-alive ping, responds with pong
    - type: "get_state" - Request current state
    - type: "set_light" - Set a specific light: {"id": 0, "on": true, "brightness": 100}
    - type: "set_all" - Set all lights: {"on": true, "brightness": 100}
    """
    await websocket.accept()
    session_id = uuid.uuid4().hex[:8]
    bind_contextvars(session_id=session_id, ws_type="lights")
    await light_service.register_websocket(websocket)
    
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_json()
            msg_type = data.get("type", "")
            
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                
            elif msg_type == "get_state":
                # Force poll ESP32 and send fresh state
                if light_service.connected:
                    await light_service._poll_esp32_states()
                await websocket.send_json({
                    "type": "state_update",
                    "data": {
                        "lights": [light.model_dump() for light in light_service.get_all_states()],
                        "connected": light_service.connected,
                        "host": light_service.get_health()["host"]
                    }
                })
                
            elif msg_type == "get_health":
                await websocket.send_json({
                    "type": "health",
                    "data": light_service.get_health()
                })
                
            elif msg_type == "set_light":
                payload = data.get("data", {})
                light_id = payload.get("id")
                on = payload.get("on", False)
                brightness = payload.get("brightness")
                
                if light_id is not None:
                    try:
                        await light_service.set_light(light_id, on, brightness)
                    except ValueError as e:
                        await websocket.send_json({
                            "type": "error",
                            "data": {"message": str(e)}
                        })
                        
            elif msg_type == "set_all":
                payload = data.get("data", {})
                on = payload.get("on", False)
                brightness = payload.get("brightness")
                await light_service.set_all_lights(on, brightness)
                
            else:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"Unknown message type: {msg_type}"}
                })
                
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected normally")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await light_service.unregister_websocket(websocket)
        clear_contextvars()
