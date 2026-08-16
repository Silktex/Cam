"""
Devices Router - Enumerate connected video and hardware capture devices
"""
from typing import Any, Dict, List
from fastapi import APIRouter

from app.services.video_device_service import video_device_service

router = APIRouter()


@router.get("/video", response_model=List[Dict[str, Any]])
async def list_video_devices():
    """
    List all connected V4L2 video capture devices, supported formats,
    resolutions, and hardware acceleration endpoints.
    """
    return video_device_service.get_devices(refresh=True)


@router.get("/video/primary")
async def get_primary_video_device():
    """
    Get primary video capture card (e.g. MacroSilicon USB 3.0 HDMI Capture Card).
    """
    dev = video_device_service.get_primary_capture_card()
    return {"device": dev}
