"""
Batch Capture API Router
"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from typing import Optional

from app.models.batch_capture import BatchCaptureRequest, BatchCaptureResult, BatchCaptureProgress
from app.services.batch_capture_service import batch_capture_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Limit concurrent on-demand renders (each uses ~500-800MB RAM)
_render_semaphore = asyncio.Semaphore(2)


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


# ── Post-capture processing (calibrate + crop) ──

from app.services.post_capture_service import post_capture_service


@router.post("/process/{folder}")
async def queue_processing(
    folder: str,
    profile: str = "CHECKER-17FEB.npz",
    crop_size: int = 3200,
):
    """Manually queue calibrate+crop for a batch folder."""
    try:
        job = post_capture_service.queue(folder, profile=profile, crop_size=crop_size)
        return {"success": True, "batch": folder, "status": job.status}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/process/{folder}")
async def get_processing_status(folder: str):
    """Get calibrate+crop processing status for a batch."""
    job = post_capture_service.get_status(folder)
    if job is None:
        return {"batch": folder, "status": "none"}
    return {
        "batch": folder,
        "status": job.status,
        "current_step": job.current_step,
        "calibrated_count": job.calibrated_count,
        "cropped_count": job.cropped_count,
        "error": job.error,
        "queued_at": job.queued_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


@router.get("/process")
async def list_processing_jobs():
    """List all post-capture processing jobs."""
    return post_capture_service.list_jobs()


# ── On-demand render (lazy calibrate+crop) ──

from app.services.post_capture_service import render_image, load_calibration


@router.get("/render/{folder}/{filename}")
async def render_batch_image(
    folder: str,
    filename: str,
    fmt: str = Query("jpg", alias="format", regex="^(jpg|tiff)$"),
    crop: bool = Query(True),
):
    """
    Render a calibrated (and optionally cropped) image on demand.

    Uses stored calibration.json parameters — same math as the eager pipeline.
    Returns JPG (8-bit) or TIFF (16-bit).
    """
    async with _render_semaphore:
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None, render_image, folder, filename, fmt, crop
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            logger.exception(f"Render failed: {folder}/{filename}")
            raise HTTPException(status_code=500, detail=str(e))

    media_type = "image/tiff" if fmt == "tiff" else "image/jpeg"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/calibration/{folder}")
async def get_calibration(folder: str):
    """Return the stored calibration.json for a batch."""
    try:
        return load_calibration(folder)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
