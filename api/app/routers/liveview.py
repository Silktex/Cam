"""
Live View Router - MJPEG streaming
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.services.camera_service import camera_service

router = APIRouter()


def generate_mjpeg():
    """Generate MJPEG stream from camera preview"""
    try:
        for frame in camera_service.start_live_view():
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
    except Exception as e:
        # Stream ended
        pass


@router.get("/stream")
async def live_view_stream():
    """
    MJPEG live view stream.
    Connect to this endpoint from an <img> tag or video player.
    """
    if not camera_service.is_connected:
        # Try to connect first
        result = camera_service.connect()
        if not result["success"]:
            raise HTTPException(
                status_code=503,
                detail="Camera not connected. Please connect first."
            )
    
    return StreamingResponse(
        generate_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


@router.post("/stop")
async def stop_live_view():
    """Stop the live view stream"""
    camera_service.stop_live_view()
    return {"success": True, "message": "Live view stopped"}


@router.get("/status")
async def live_view_status():
    """Get live view status"""
    return {
        "available": camera_service.is_connected,
        "active": camera_service._live_view_active,
        "model": camera_service.model,
    }
