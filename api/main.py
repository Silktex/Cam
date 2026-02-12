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
from app.routers import health, camera, capture, liveview, websocket, lights, lights_ws, batch_capture, batches, processing
from app.services.camera_service import camera_service
from app.services.light_service import light_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    logger.info("Starting Camera Control API...")
    
    # Startup: Check camera on boot
    try:
        camera_service.startup_check()
    except Exception as e:
        logger.warning(f"Startup camera check failed: {e}")
    
    # Startup: Connect to ESP32 light controller
    try:
        await light_service.connect()
    except Exception as e:
        logger.warning(f"ESP32 light controller connection failed: {e}")
    
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


app = FastAPI(
    title="Camera Control API",
    description="FastAPI backend for Sony A7R III camera control via gphoto2",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - allow frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
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


@app.get("/")
async def root():
    return {"message": "Camera Control API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
