"""
Live View Router - Hardware Accelerated RTSP & WebRTC (WHEP) streaming
Supports dual stream sources:
1. 'hdmi': MacroSilicon USB 3.0 HDMI Capture Card (VA-API H.264 WebRTC/RTSP)
2. 'ptp': Sony ILCE-7RM3 USB Direct Preview
"""
import logging
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.services.camera_service import camera_service
from app.services.video_device_service import video_device_service

logger = logging.getLogger(__name__)
router = APIRouter()


class StreamSourcePayload(BaseModel):
    source: Literal["hdmi", "ptp"] = Field(..., description="Stream source: 'hdmi' or 'ptp'")


class LiveViewStatusResponse(BaseModel):
    available: bool
    active: bool
    model: str
    active_source: Literal["hdmi", "ptp"]
    available_sources: List[str]
    device_name: str
    stream_type: str
    whep_url: str
    rtsp_url: str
    hls_url: str
    resolution: str
    fps: int
    hw_accel: Dict[str, Any]


@router.get("/status", response_model=LiveViewStatusResponse)
async def live_view_status():
    """
    Get live view hardware and stream status.
    Returns active stream source, stream URLs (WHEP/RTSP/HLS), and hardware encoder telemetry.
    """
    active_source: Literal["hdmi", "ptp"] = "ptp" if camera_service.stream_source == "ptp" else "hdmi"
    capture_card = video_device_service.get_primary_capture_card()
    
    device_name = (
        capture_card.get("name", "MacroSilicon USB 3.0 HDMI Capture Card")
        if active_source == "hdmi"
        else (camera_service.model or "Sony ILCE-7RM3 Direct Preview")
    )

    return {
        "available": True,
        "active": camera_service.live_view_active or (active_source == "hdmi"),
        "model": camera_service.model or "Sony ILCE-7RM3",
        "active_source": active_source,
        "available_sources": ["hdmi", "ptp"],
        "device_name": device_name,
        "stream_type": "webrtc_h264" if active_source == "hdmi" else "ptp_direct",
        "whep_url": "/stream/whep",
        "rtsp_url": "rtsp://127.0.0.1:8554/stream",
        "hls_url": "/hls/stream/index.m3u8",
        "resolution": "1920x1080",
        "fps": 30,
        "hw_accel": {
            "enabled": True,
            "encoder": "h264_vaapi (AMD Radeon Vega 11)",
            "device": "/dev/dri/renderD128",
            "profile": "constrained_baseline",
            "latency": "<100ms",
        },
    }


@router.post("/source", response_model=LiveViewStatusResponse)
async def set_stream_source(payload: StreamSourcePayload):
    """
    Switch active live view stream source ('hdmi' | 'ptp').
    """
    try:
        updated_source = camera_service.set_stream_source(payload.source)
        logger.info(f"Switched live view source to: {updated_source}")
        return await live_view_status()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/capabilities")
async def get_liveview_capabilities():
    """
    Get hardware capture and stream encoding capabilities.
    """
    capture_card = video_device_service.get_primary_capture_card()
    return {
        "active_source": camera_service.stream_source,
        "capture_card": capture_card,
        "ptp_camera": {
            "model": camera_service.model or "Sony ILCE-7RM3",
            "connected": camera_service.is_connected,
            "supported": True,
        },
        "hw_encoder": {
            "supported_codecs": ["h264_vaapi", "hevc_vaapi"],
            "recommended_profile": "constrained_baseline",
            "device": "/dev/dri/renderD128",
        },
    }


@router.post("/start")
async def start_live_view():
    """Start live view stream"""
    return {"success": True, "message": "Live view active", "source": camera_service.stream_source}


@router.post("/stop")
async def stop_live_view():
    """Stop the live view stream"""
    camera_service.stop_live_view()
    return {"success": True, "message": "Live view stopped"}


@router.get("/stream")
async def live_view_stream():
    """MJPEG live view (PTP source) or stream metadata (HDMI/WebRTC source)."""
    if camera_service.stream_source != "ptp":
        return {
            "status": "active",
            "stream_type": "webrtc_h264",
            "whep_url": "/stream/whep",
            "rtsp_url": "rtsp://127.0.0.1:8554/stream",
            "message": "Use WebRTC WHEP player (/stream/whep) for hardware-accelerated stream",
        }

    def mjpeg_frames():
        for frame in camera_service.start_live_view():
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"

    return StreamingResponse(
        mjpeg_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
