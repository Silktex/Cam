"""
Health Check Router
"""
from fastapi import APIRouter
from app.services.camera_service import camera_service
from app.models.camera import HealthResponse, CameraStatus

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    System health check endpoint.
    Returns status of all services.
    """
    camera_detected = camera_service.detect_camera()
    camera_connected = camera_service.is_connected
    
    services = {
        "api_server": True,
        "camera_detected": camera_detected,
        "camera_connected": camera_connected,
        "live_view_available": camera_connected,
    }
    
    # Determine overall status
    if camera_connected:
        status = "healthy"
    elif camera_detected:
        status = "degraded"
    else:
        status = "unhealthy"
    
    return HealthResponse(
        status=status,
        services=services,
        camera=CameraStatus(
            connected=camera_connected,
            detected=camera_detected,
            model=camera_service.model,
        )
    )
