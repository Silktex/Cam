"""
Batch Capture API Router
"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from typing import Optional

from app.models.batch_capture import BatchCaptureRequest, BatchCaptureResult, BatchCaptureProgress
from app.services.batch_capture_service import batch_capture_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/start", response_model=BatchCaptureResult)
async def start_batch_capture(request: BatchCaptureRequest):
    """
    Start a batch capture sequence.
    
    This will:
    1. Turn on Top Light + Side 1 Light, wait for stabilization, capture
    2. Switch to Side 2 Light, wait, capture
    3. Continue through Side 8
    4. Turn off all lights
    
    Returns the complete result after all captures are done.
    """
    if batch_capture_service.is_running:
        raise HTTPException(
            status_code=409,
            detail="Batch capture already in progress"
        )
    
    try:
        result = await batch_capture_service.start_batch_capture(
            folder=request.folder,
            prefix=request.prefix,
            light_stabilize_delay=request.light_stabilize_delay
        )
        return result
    except Exception as e:
        logger.exception(f"Batch capture failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel")
async def cancel_batch_capture():
    """Cancel an ongoing batch capture"""
    result = await batch_capture_service.cancel()
    return result


@router.get("/status")
async def get_batch_status():
    """Get current batch capture status"""
    return batch_capture_service.get_status()


@router.websocket("/ws")
async def batch_capture_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time batch capture progress.
    
    Send a message to start:
    {"action": "start", "folder": "session_1", "prefix": "batch", "light_stabilize_delay": 2.0}
    
    Send to cancel:
    {"action": "cancel"}
    
    Receive progress updates:
    {"type": "progress", "data": {...}}
    {"type": "complete", "data": {...}}
    {"type": "error", "data": {"message": "..."}}
    """
    await websocket.accept()
    logger.info("Batch capture WebSocket connected")
    
    async def progress_callback(progress: BatchCaptureProgress):
        """Send progress updates to WebSocket client"""
        try:
            await websocket.send_json({
                "type": "progress",
                "data": progress.model_dump()
            })
        except Exception as e:
            logger.warning(f"Failed to send progress: {e}")
    
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            
            if action == "start":
                if batch_capture_service.is_running:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "Batch capture already in progress"}
                    })
                    continue
                
                folder = data.get("folder", f"batch_{asyncio.get_event_loop().time():.0f}")
                prefix = data.get("prefix", "batch")
                delay = data.get("light_stabilize_delay", 2.0)
                
                await websocket.send_json({
                    "type": "started",
                    "data": {"folder": folder, "prefix": prefix}
                })
                
                try:
                    result = await batch_capture_service.start_batch_capture(
                        folder=folder,
                        prefix=prefix,
                        light_stabilize_delay=delay,
                        progress_callback=progress_callback
                    )
                    
                    await websocket.send_json({
                        "type": "complete",
                        "data": result.model_dump()
                    })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": str(e)}
                    })
            
            elif action == "cancel":
                result = await batch_capture_service.cancel()
                await websocket.send_json({
                    "type": "cancelled",
                    "data": result
                })
            
            elif action == "status":
                status = batch_capture_service.get_status()
                await websocket.send_json({
                    "type": "status",
                    "data": status
                })
            
            else:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"Unknown action: {action}"}
                })
                
    except WebSocketDisconnect:
        logger.info("Batch capture WebSocket disconnected")
    except Exception as e:
        logger.error(f"Batch capture WebSocket error: {e}")
