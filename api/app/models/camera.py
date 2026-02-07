"""
Camera-related Pydantic models
"""
from typing import Optional, List, Any, Dict
from pydantic import BaseModel


class CameraStatus(BaseModel):
    """Camera connection status"""
    connected: bool
    detected: bool
    model: Optional[str] = None
    error: Optional[str] = None


class CameraInfo(BaseModel):
    """Detailed camera information"""
    model: str
    serial: Optional[str] = None
    manufacturer: Optional[str] = None


class TroubleshootResult(BaseModel):
    """Result from troubleshoot/kill processes"""
    success: bool
    killed_processes: List[str]
    camera_detected: bool
    message: str


class SettingValue(BaseModel):
    """Camera setting value"""
    name: str
    label: str
    value: Any
    type: str  # text, radio, menu, toggle, range
    readonly: bool = False
    choices: Optional[List[str]] = None
    range: Optional[Any] = None  # [min, max, step] tuple from gphoto2


class CameraSettings(BaseModel):
    """Camera settings tree"""
    settings: List[SettingValue]


class SetSettingRequest(BaseModel):
    """Request to set a camera setting"""
    name: str
    value: Any


class HealthResponse(BaseModel):
    """System health status"""
    status: str  # healthy, degraded, unhealthy
    services: Dict[str, bool]
    camera: CameraStatus
