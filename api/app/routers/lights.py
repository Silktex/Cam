"""
Light Controller REST API Router
"""
import logging
from fastapi import APIRouter, HTTPException

from app.models.light import (
    LightState,
    LightUpdateRequest,
    AllLightsRequest,
    LightsResponse,
    LightHealthResponse
)
from app.services.light_service import light_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=LightsResponse, include_in_schema=False)
@router.get("/", response_model=LightsResponse)
async def get_all_lights():
    """Get the state of all lights."""
    return LightsResponse(
        lights=light_service.get_all_states(),
        connected=light_service.connected,
        host=light_service.get_health()["host"]
    )


@router.get("/health", response_model=LightHealthResponse)
async def get_light_health():
    """Get health status of the light controller."""
    health = light_service.get_health()
    return LightHealthResponse(**health)


@router.get("/{light_id}", response_model=LightState)
async def get_light(light_id: int):
    """Get the state of a specific light."""
    if light_id < 0 or light_id >= len(light_service.lights):
        raise HTTPException(status_code=404, detail=f"Light {light_id} not found")
    return light_service.lights[light_id]


@router.post("/{light_id}", response_model=LightState)
async def update_light(light_id: int, request: LightUpdateRequest):
    """Update a specific light's state."""
    try:
        result = await light_service.set_light(
            light_id=light_id,
            on=request.on,
            brightness=request.brightness
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update light {light_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update light")


@router.post("/all/on", response_model=LightsResponse)
async def turn_all_on(brightness: int = 100):
    """Turn all lights on with optional brightness."""
    lights = await light_service.set_all_lights(on=True, brightness=brightness)
    return LightsResponse(
        lights=lights,
        connected=light_service.connected,
        host=light_service.get_health()["host"]
    )


@router.post("/all/off", response_model=LightsResponse)
async def turn_all_off():
    """Turn all lights off."""
    lights = await light_service.set_all_lights(on=False)
    return LightsResponse(
        lights=lights,
        connected=light_service.connected,
        host=light_service.get_health()["host"]
    )


@router.post("/all", response_model=LightsResponse)
async def update_all_lights(request: AllLightsRequest):
    """Update all lights at once."""
    try:
        lights = await light_service.set_all_lights(
            on=request.on,
            brightness=request.brightness
        )
        return LightsResponse(
            lights=lights,
            connected=light_service.connected,
            host=light_service.get_health()["host"]
        )
    except Exception as e:
        logger.error(f"Failed to update all lights: {e}")
        raise HTTPException(status_code=500, detail="Failed to update lights")


@router.post("/reconnect")
async def reconnect_esp32():
    """Attempt to reconnect to ESP32."""
    try:
        await light_service.disconnect()
        success = await light_service.connect()
        return {
            "success": success,
            "connected": light_service.connected,
            "message": "Connected to ESP32" if success else "Failed to connect, running in simulation mode"
        }
    except Exception as e:
        logger.error(f"Failed to reconnect: {e}")
        raise HTTPException(status_code=500, detail=str(e))
