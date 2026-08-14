"""
Auto Exposure API router.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models.exposure import (
    ExposureConfigResponse,
    ExposureStatusResponse,
    FrameQaResponse,
    PreflightLightResult,
    PreflightResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/config", response_model=ExposureConfigResponse)
async def get_exposure_config():
    """Return the current auto-exposure configuration."""
    cfg = settings.auto_exposure_config()
    return ExposureConfigResponse(
        enabled=cfg.enabled,
        mode=cfg.mode,
        iso=cfg.iso,
        aperture=cfg.aperture,
        target_percentile=cfg.target_percentile,
        target_normalized=cfg.target_normalized,
        acceptable_low=cfg.acceptable_low,
        acceptable_high=cfg.acceptable_high,
        near_clip_threshold=cfg.near_clip_threshold,
        hard_clip_threshold=cfg.hard_clip_threshold,
        max_hard_clip_fraction=cfg.max_hard_clip_fraction,
        max_near_clip_fraction=cfg.max_near_clip_fraction,
        retake_limit=cfg.retake_limit,
        minimum_p95_normalized=cfg.minimum_p95_normalized,
    )


@router.get("/status", response_model=ExposureStatusResponse)
async def get_exposure_status():
    """Return the camera's current exposure state."""
    from app.services.exposure.controller import CameraExposureController

    try:
        from app.services.camera_service import camera_service
    except ImportError:
        return ExposureStatusResponse(connected=False)

    controller = CameraExposureController(config=settings.auto_exposure_config())
    exposure = controller.get_current_exposure() if camera_service.is_connected else None
    return ExposureStatusResponse(
        connected=camera_service.is_connected,
        iso=exposure.iso if exposure else None,
        aperture=exposure.aperture if exposure else None,
        shutter_seconds=exposure.shutter_seconds if exposure else None,
        shutter_label=exposure.shutter_label if exposure else None,
        camera_mode=exposure.camera_mode if exposure else None,
    )


@router.post("/preflight", response_model=PreflightResponse)
async def run_exposure_preflight():
    """Run exposure preflight and select one locked shutter for the sequence."""
    cfg = settings.auto_exposure_config()
    if not cfg.enabled:
        raise HTTPException(status_code=400, detail="Auto exposure is disabled")

    from app.services.camera_service import camera_service
    from app.services.exposure.service import build_services, run_preflight

    if not camera_service.is_connected:
        raise HTTPException(status_code=409, detail="Camera not connected")

    try:
        services = build_services(cfg)
        result = run_preflight(services)
    except Exception as e:
        logger.exception("Preflight failed")
        raise HTTPException(status_code=500, detail=str(e))

    lights = [
        PreflightLightResult(
            name=name,
            status=result.light_results[name].status,
            limiting_channel=result.light_results[name].limiting_channel,
            measured_normalized=result.light_results[name].measured_normalized,
            clipped_fraction=result.light_results[name].clipped_fraction,
        )
        for name in result.light_results
    ]
    return PreflightResponse(
        status=result.status,
        selected_shutter_seconds=result.selected_shutter_seconds,
        selected_shutter_label=result.selected_shutter_label,
        iso=result.iso,
        aperture=result.aperture,
        limiting_light=result.limiting_light,
        limiting_channel=result.limiting_channel,
        predicted_peak=result.predicted_peak,
        headroom_ev=result.headroom_ev,
        iterations=result.iterations,
        lights=lights,
        errors=result.errors,
        warnings=result.warnings,
    )


@router.post("/qa/{folder}/{filename}", response_model=FrameQaResponse)
async def qa_frame(folder: str, filename: str):
    """Analyze a captured RAW and return its per-frame exposure QA verdict."""
    from pathlib import Path

    from app.services.exposure.service import build_services

    cfg = settings.auto_exposure_config()
    raw_path = settings.CAPTURES_DIR / folder / "raw" / filename
    if not raw_path.exists():
        raise HTTPException(status_code=404, detail=f"RAW not found: {filename}")

    services = build_services(cfg)
    analysis = services.analyzer.analyze_file(raw_path)
    locked = services.controller.get_current_exposure()
    qa = services.qa.evaluate(analysis, locked)
    return FrameQaResponse(
        status=qa.status.value,
        reason=qa.reason,
        p99_9={n: m.p999 for n, m in analysis.channel_metrics.items()},
        limiting_channel=analysis.limiting_channel,
        measured_normalized=analysis.measured_normalized,
        hard_clip_fraction=analysis.clipped_fraction,
        near_clip_fraction=analysis.near_clipped_fraction,
        headroom_ev=analysis.headroom_ev,
    )
