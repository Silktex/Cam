"""
Pydantic models for Light Controller
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class LightState(BaseModel):
    """Individual light state"""
    id: int = Field(..., description="Light ID (0-8)")
    name: str = Field(..., description="Light name")
    pin: int = Field(..., description="GPIO pin number")
    on: bool = Field(default=False, description="Light on/off state")
    brightness: int = Field(default=100, ge=0, le=100, description="Brightness 0-100%")


class LightUpdateRequest(BaseModel):
    """Request to update a light"""
    on: bool = Field(..., description="Turn light on or off")
    brightness: Optional[int] = Field(default=None, ge=0, le=100, description="Brightness 0-100%")


class AllLightsRequest(BaseModel):
    """Request to update all lights"""
    on: bool = Field(..., description="Turn all lights on or off")
    brightness: Optional[int] = Field(default=None, ge=0, le=100, description="Brightness 0-100%")


class LightsResponse(BaseModel):
    """Response with all light states"""
    lights: List[LightState]
    connected: bool = Field(..., description="Connected to ESP32")
    host: str = Field(..., description="ESP32 host address")


class LightHealthResponse(BaseModel):
    """Health check response for lights"""
    status: str = Field(..., description="Health status: ok or error")
    connected: bool = Field(..., description="Connected to ESP32")
    host: str = Field(..., description="ESP32 host address")
    port: int = Field(..., description="ESP32 port")
    total_lights: int = Field(..., description="Total number of lights")
    message: Optional[str] = Field(default=None, description="Additional message")


class WebSocketMessage(BaseModel):
    """WebSocket message format"""
    type: str = Field(..., description="Message type: state_update, health, error")
    data: dict = Field(..., description="Message data")
