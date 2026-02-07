"""
Camera Router - Connect, disconnect, troubleshoot, settings
"""
from typing import List
from fastapi import APIRouter, HTTPException

from app.services.camera_service import camera_service
from app.models.camera import (
    CameraStatus,
    TroubleshootResult,
    SettingValue,
    SetSettingRequest,
)

router = APIRouter()


@router.get("/status", response_model=CameraStatus)
async def get_camera_status():
    """Get current camera connection status"""
    detected = camera_service.detect_camera()
    return CameraStatus(
        connected=camera_service.is_connected,
        detected=detected,
        model=camera_service.model,
    )


@router.post("/connect")
async def connect_camera():
    """Connect to camera"""
    result = camera_service.connect()
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/disconnect")
async def disconnect_camera():
    """Disconnect from camera"""
    return camera_service.disconnect()


@router.post("/troubleshoot", response_model=TroubleshootResult)
async def troubleshoot_camera():
    """
    Kill PTP processes that grab the camera and check detection.
    Use this to reset camera connection when it gets stuck.
    """
    result = camera_service.troubleshoot()
    return TroubleshootResult(
        success=result["success"],
        killed_processes=result["killed_processes"],
        camera_detected=result["camera_detected"],
        message=result["message"],
    )


@router.get("/settings")
async def get_camera_settings():
    """Get all camera settings"""
    try:
        settings = camera_service.get_settings()
        return settings  # Return raw list without validation
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings")
async def set_camera_setting(request: SetSettingRequest):
    """Set a camera setting"""
    try:
        result = camera_service.set_setting(request.name, request.value)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/settings/{name}", response_model=SettingValue)
async def get_camera_setting(name: str):
    """Get a specific camera setting"""
    try:
        settings = camera_service.get_settings()
        for s in settings:
            if s["name"] == name:
                return SettingValue(**s)
        raise HTTPException(status_code=404, detail=f"Setting '{name}' not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
