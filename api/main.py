#!/usr/bin/env python3
"""
Camera Control FastAPI Backend
Main application entry point for Sony A7R III via gphoto2
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import health, camera, capture, liveview, websocket, lights, lights_ws, batch_capture, batches, processing, colorchecker, image_processing, exposure
from app.services.camera_service import camera_service
from app.services.event_bus import event_bus
from app.services.light_service import light_service

# Configure structured logging — MUST be before app creation
from app.logging_setup import setup_logging
from app.request_id_middleware import RequestIdMiddleware

setup_logging(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    import asyncio

    application_loop = asyncio.get_running_loop()
    event_bus.attach_loop(application_loop)
    logger.info("Starting Camera Control API...")

    # ── Camera detection ──
    camera_info = {"detected": False}
    try:
        camera_info = camera_service.startup_check()
    except Exception as e:
        logger.warning(f"Startup camera check failed: {e}")

    # ── ESP32 light controller ──
    esp_info = {"host": settings.ESP32_HOST, "connected": False}
    try:
        esp_info = await light_service.connect()
    except Exception as e:
        logger.warning(f"ESP32 light controller connection failed: {e}")

    # ── Startup summary ──
    logger.info("=" * 60)
    logger.info("  STARTUP DEVICE STATUS")
    logger.info("-" * 60)

    if camera_info.get("detected"):
        logger.info(f"  Camera : DETECTED")
        logger.info(f"           Model -> {camera_info.get('model', 'unknown')}")
        logger.info(f"           Port  -> {camera_info.get('port', 'unknown')}")
    else:
        logger.warning(f"  Camera : NOT DETECTED — no USB camera found")
        if camera_info.get("error"):
            logger.warning(f"           Error -> {camera_info['error']}")

    esp_host = esp_info.get("host", settings.ESP32_HOST)
    if esp_info.get("connected"):
        logger.info(f"  ESP32  : CONNECTED at http://{esp_host}")
        logger.info(f"           Lights -> {esp_info.get('lights', '?')} configured")
    else:
        logger.warning(f"  ESP32  : NOT REACHABLE at http://{esp_host}")
        if esp_info.get("http_status"):
            logger.warning(f"           HTTP status -> {esp_info['http_status']}")
        elif esp_info.get("error"):
            logger.warning(f"           Error -> {esp_info['error']}")
        logger.warning(f"           Running in simulation mode (lights tracked locally)")

    logger.info(f"  Queue  : READY (calibrate + crop)")

    logger.info("=" * 60)

    yield
    
    # Shutdown: Disconnect camera
    logger.info("Shutting down Camera Control API...")
    try:
        camera_service.disconnect()
    except Exception:
        pass
    
    # Shutdown: Disconnect light controller
    try:
        await light_service.disconnect()
    except Exception:
        pass
    finally:
        event_bus.detach_loop(application_loop)


app = FastAPI(
    title="Camera Control API",
    description="FastAPI backend for Sony A7R III camera control via gphoto2",
    version="1.0.0",
    lifespan=lifespan,
)

# Request ID middleware — binds request_id to contextvars for structured logs
app.add_middleware(RequestIdMiddleware)

# CORS - allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount media folder for serving captured images
app.mount("/media", StaticFiles(directory=settings.MEDIA_DIR), name="media")

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(camera.router, prefix="/api/camera", tags=["Camera"])
app.include_router(capture.router, prefix="/api/capture", tags=["Capture"])
app.include_router(liveview.router, prefix="/api/liveview", tags=["Live View"])
app.include_router(websocket.router, prefix="/api/ws", tags=["WebSocket"])
app.include_router(lights.router, prefix="/api/lights", tags=["Lights"])
app.include_router(lights_ws.router, prefix="/ws", tags=["Lights WebSocket"])
app.include_router(batch_capture.router, prefix="/api/batch", tags=["Batch Capture"])
app.include_router(batches.router, prefix="/api/batches", tags=["Batches"])
app.include_router(processing.router, prefix="/api/processing", tags=["Processing"])
app.include_router(colorchecker.router, prefix="/api/colorchecker", tags=["ColorChecker"])
app.include_router(image_processing.router, prefix="/api/image-processing", tags=["Image Processing"])
app.include_router(exposure.router, prefix="/api/exposure", tags=["Exposure"])


@app.get("/")
async def root():
    return {"message": "Camera Control API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    # NOTE: if running via entrypoint.sh, ensure it doesn't override log config
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_config=None,
    )
