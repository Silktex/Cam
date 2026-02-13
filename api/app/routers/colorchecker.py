"""
ColorChecker Router - Color checker detection and calibration workflow.
Endpoints for capturing, detecting, adjusting, and saving ColorChecker profiles.
"""
import uuid
import logging
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import settings
from app.services.camera_service import camera_service

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory cache for current detection session
_detection_cache: Dict[str, dict] = {}


# ─── Pydantic Models ───

class CaptureResponse(BaseModel):
    success: bool
    image_path: str
    image_url: str
    filename: str


class DetectRequest(BaseModel):
    image_path: str


class DetectResponse(BaseModel):
    success: bool
    detection_id: str
    swatches_detected: int
    source_image: str
    overlay_url: str
    flip_h: bool = False
    flip_v: bool = False
    rotation: int = 0


class FlipRequest(BaseModel):
    detection_id: str
    axis: str  # 'horizontal' or 'vertical'


class RotateRequest(BaseModel):
    detection_id: str
    degrees: int  # 90, 180, 270


class SaveProfileRequest(BaseModel):
    detection_id: str
    profile_name: str


class ProfileResponse(BaseModel):
    name: str
    path: str
    created_at: str
    source_image: str
    checker_type: str


# ─── Endpoints ───

@router.post("/capture", response_model=CaptureResponse)
async def capture_colorchecker():
    """
    Capture a ColorChecker image from the connected camera.
    Saves to media/colorchecker/captures/ folder.
    Returns TIFF file path for detection (not RAW).
    """
    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"colorchecker_{timestamp}"

    # Capture image using camera service (saves RAW + converts to TIFF)
    result = camera_service.capture_image(
        folder="colorchecker/captures",
        prefix=filename
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to capture image")
        )

    # Use TIFF file for detection instead of RAW
    raw_filepath = Path(result["filepath"])
    tiff_filepath = raw_filepath.parent.parent / "tiff" / f"{raw_filepath.stem}.tiff"

    # Fallback to full_webview JPEG if TIFF doesn't exist
    if not tiff_filepath.exists():
        jpeg_filepath = raw_filepath.parent.parent / "full_webview" / f"{raw_filepath.stem}.jpg"
        if jpeg_filepath.exists():
            tiff_filepath = jpeg_filepath
        else:
            # Use the original filepath as last resort
            tiff_filepath = raw_filepath

    # Build URL for the TIFF/JPEG file
    rel_path = tiff_filepath.relative_to(settings.MEDIA_DIR)
    file_url = f"/media/{rel_path}"

    logger.info(f"ColorChecker captured: RAW={raw_filepath.name}, using={tiff_filepath.name}")

    return CaptureResponse(
        success=True,
        image_path=str(tiff_filepath),
        image_url=file_url,
        filename=tiff_filepath.name,
    )


@router.post("/detect", response_model=DetectResponse)
async def detect_colorchecker(request: DetectRequest):
    """
    Detect ColorChecker in an image.
    Returns detection ID and overlay image URL for preview.
    """
    from scripts.processing.calibration_service import CalibrationService, COLOUR_AVAILABLE

    if not COLOUR_AVAILABLE:
        raise HTTPException(
            status_code=500,
            detail="colour-science library not installed. Run: pip install colour-science colour-checker-detection"
        )

    image_path = Path(request.image_path)
    logger.info(f"Detect request for image: {request.image_path}")

    # Handle relative paths - prepend media directory if needed
    if not image_path.is_absolute():
        image_path = settings.MEDIA_DIR / request.image_path
        logger.info(f"Resolved to absolute path: {image_path}")

    # If RAW file, find corresponding TIFF or JPEG
    raw_extensions = {'.arw', '.cr2', '.nef', '.dng', '.raf', '.orf', '.rw2'}
    if image_path.suffix.lower() in raw_extensions:
        logger.info(f"RAW file detected, looking for TIFF/JPEG alternative")
        # Try TIFF first
        tiff_path = image_path.parent.parent / "tiff" / f"{image_path.stem}.tiff"
        if tiff_path.exists():
            image_path = tiff_path
            logger.info(f"Using TIFF: {tiff_path}")
        else:
            # Try full_webview JPEG
            jpeg_path = image_path.parent.parent / "full_webview" / f"{image_path.stem}.jpg"
            if jpeg_path.exists():
                image_path = jpeg_path
                logger.info(f"Using JPEG: {jpeg_path}")

    if not image_path.exists():
        logger.error(f"Image not found at: {image_path}")
        raise HTTPException(status_code=404, detail=f"Image not found: {request.image_path}")

    logger.info(f"Image exists, size: {image_path.stat().st_size} bytes")

    try:
        calibration_service = CalibrationService()
        checker_data = calibration_service.detect_colorchecker(str(image_path))

        if not checker_data:
            raise HTTPException(status_code=404, detail="No ColorChecker detected in image")

        # Generate unique detection ID
        detection_id = f"det_{uuid.uuid4().hex[:8]}"

        # Cache detection data
        _detection_cache[detection_id] = {
            "data": checker_data,
            "service": calibration_service,
            "created_at": datetime.now().isoformat(),
        }

        # Generate overlay URL (will be fetched via /overlay/{id})
        overlay_url = f"/api/colorchecker/overlay/{detection_id}"

        return DetectResponse(
            success=True,
            detection_id=detection_id,
            swatches_detected=len(checker_data.detected_swatches),
            source_image=str(image_path),
            overlay_url=overlay_url,
            flip_h=checker_data.flip_h,
            flip_v=checker_data.flip_v,
            rotation=checker_data.rotation,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ColorChecker detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overlay/{detection_id}")
async def get_overlay_image(detection_id: str):
    """
    Get overlay image with swatch boxes for a detection.
    Returns PNG image.
    """
    if detection_id not in _detection_cache:
        raise HTTPException(status_code=404, detail="Detection not found or expired")

    cached = _detection_cache[detection_id]
    checker_data = cached["data"]
    service = cached["service"]

    try:
        png_bytes = service.generate_overlay_image(checker_data)
        return Response(content=png_bytes, media_type="image/png")

    except Exception as e:
        logger.error(f"Failed to generate overlay: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flip", response_model=DetectResponse)
async def flip_detection(request: FlipRequest):
    """
    Apply flip transformation to detected swatches.
    Updates the detection in cache and returns updated overlay.
    """
    if request.detection_id not in _detection_cache:
        raise HTTPException(status_code=404, detail="Detection not found or expired")

    if request.axis not in ('horizontal', 'vertical'):
        raise HTTPException(status_code=400, detail="axis must be 'horizontal' or 'vertical'")

    cached = _detection_cache[request.detection_id]
    checker_data = cached["data"]
    service = cached["service"]

    try:
        # Apply flip
        new_data = service.apply_flip(checker_data, request.axis)

        # Update cache
        _detection_cache[request.detection_id]["data"] = new_data

        return DetectResponse(
            success=True,
            detection_id=request.detection_id,
            swatches_detected=len(new_data.detected_swatches),
            source_image=new_data.source_image,
            overlay_url=f"/api/colorchecker/overlay/{request.detection_id}",
            flip_h=new_data.flip_h,
            flip_v=new_data.flip_v,
            rotation=new_data.rotation,
        )

    except Exception as e:
        logger.error(f"Flip failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rotate", response_model=DetectResponse)
async def rotate_detection(request: RotateRequest):
    """
    Apply rotation to detected swatches.
    Updates the detection in cache and returns updated overlay.
    """
    if request.detection_id not in _detection_cache:
        raise HTTPException(status_code=404, detail="Detection not found or expired")

    if request.degrees not in (90, 180, 270, -90):
        raise HTTPException(status_code=400, detail="degrees must be 90, 180, 270, or -90")

    cached = _detection_cache[request.detection_id]
    checker_data = cached["data"]
    service = cached["service"]

    try:
        # Apply rotation
        new_data = service.apply_rotation(checker_data, request.degrees)

        # Update cache
        _detection_cache[request.detection_id]["data"] = new_data

        return DetectResponse(
            success=True,
            detection_id=request.detection_id,
            swatches_detected=len(new_data.detected_swatches),
            source_image=new_data.source_image,
            overlay_url=f"/api/colorchecker/overlay/{request.detection_id}",
            flip_h=new_data.flip_h,
            flip_v=new_data.flip_v,
            rotation=new_data.rotation,
        )

    except Exception as e:
        logger.error(f"Rotation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save")
async def save_profile(request: SaveProfileRequest):
    """
    Save current detection as a calibration profile.
    Saves as NPZ file in media/colorchecker/profiles/.
    """
    if request.detection_id not in _detection_cache:
        raise HTTPException(status_code=404, detail="Detection not found or expired")

    if not request.profile_name:
        raise HTTPException(status_code=400, detail="Profile name is required")

    cached = _detection_cache[request.detection_id]
    checker_data = cached["data"]
    service = cached["service"]

    try:
        profile_path = service.save_profile(checker_data, request.profile_name)

        return {
            "success": True,
            "profile_name": request.profile_name,
            "profile_path": profile_path,
            "message": f"Profile '{request.profile_name}' saved successfully",
        }

    except Exception as e:
        logger.error(f"Failed to save profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profiles")
async def list_profiles():
    """
    List all saved ColorChecker profiles.
    """
    from scripts.processing.calibration_service import CalibrationService, COLOUR_AVAILABLE

    if not COLOUR_AVAILABLE:
        return {"profiles": [], "warning": "colour-science library not installed"}

    try:
        service = CalibrationService()
        profiles = service.list_profiles()
        return {"profiles": profiles}

    except Exception as e:
        logger.error(f"Failed to list profiles: {e}")
        return {"profiles": [], "error": str(e)}


@router.get("/profiles/{name}")
async def get_profile(name: str):
    """
    Get details of a saved profile.
    """
    from scripts.processing.calibration_service import CalibrationService, COLOUR_AVAILABLE

    if not COLOUR_AVAILABLE:
        raise HTTPException(status_code=500, detail="colour-science not available")

    try:
        service = CalibrationService()
        profile_data = service.load_profile(name)

        if not profile_data:
            raise HTTPException(status_code=404, detail=f"Profile not found: {name}")

        return {
            "name": name,
            "source_image": profile_data.source_image,
            "flip_h": profile_data.flip_h,
            "flip_v": profile_data.flip_v,
            "rotation": profile_data.rotation,
            "swatches_count": len(profile_data.detected_swatches),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/profiles/{name}")
async def delete_profile(name: str):
    """
    Delete a saved profile.
    """
    from scripts.processing.calibration_service import CalibrationService

    try:
        service = CalibrationService()
        success = service.delete_profile(name)

        if not success:
            raise HTTPException(status_code=404, detail=f"Profile not found: {name}")

        return {"success": True, "message": f"Profile '{name}' deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reference-swatches")
async def get_reference_swatches():
    """
    Get the reference ColorChecker24 swatch values.
    Returns RGB values (0-1 range) for all 24 swatches.
    """
    from scripts.processing.calibration_service import COLOUR_AVAILABLE

    if not COLOUR_AVAILABLE:
        raise HTTPException(status_code=500, detail="colour-science not available")

    try:
        import colour
        from colour.characterisation import ColourChecker

        # Get ColorChecker24 reference
        reference = colour.CCS_COLOURCHECKERS['ColorChecker24 - After November 2014']

        # Convert to sRGB
        reference_rgb = colour.XYZ_to_RGB(
            colour.xyY_to_XYZ(list(reference.data.values())),
            'sRGB',
            reference.illuminant
        )

        # Build response with swatch names and RGB values
        swatch_names = list(reference.data.keys())
        swatches = []

        for i, name in enumerate(swatch_names):
            rgb = reference_rgb[i]
            swatches.append({
                "name": name,
                "index": i,
                "r": float(rgb[0]),
                "g": float(rgb[1]),
                "b": float(rgb[2]),
                "hex": "#{:02x}{:02x}{:02x}".format(
                    int(max(0, min(255, rgb[0] * 255))),
                    int(max(0, min(255, rgb[1] * 255))),
                    int(max(0, min(255, rgb[2] * 255))),
                ),
            })

        return {
            "checker_type": "ColorChecker24 - After November 2014",
            "rows": reference.rows,
            "columns": reference.columns,
            "swatches": swatches,
        }

    except Exception as e:
        logger.error(f"Failed to get reference swatches: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/detected-swatches/{detection_id}")
async def get_detected_swatches(detection_id: str):
    """
    Get detected swatch values for comparison with reference.
    """
    if detection_id not in _detection_cache:
        raise HTTPException(status_code=404, detail="Detection not found or expired")

    cached = _detection_cache[detection_id]
    checker_data = cached["data"]

    swatches = []
    swatch_labels = list('ABCDEFGHIJKLMNOPQRSTUVWX')

    for i, rgb in enumerate(checker_data.detected_swatches):
        swatches.append({
            "name": swatch_labels[i] if i < 24 else f"S{i}",
            "index": i,
            "r": float(rgb[0]),
            "g": float(rgb[1]),
            "b": float(rgb[2]),
            "hex": "#{:02x}{:02x}{:02x}".format(
                int(max(0, min(255, rgb[0] * 255))),
                int(max(0, min(255, rgb[1] * 255))),
                int(max(0, min(255, rgb[2] * 255))),
            ),
        })

    return {
        "detection_id": detection_id,
        "swatches": swatches,
        "flip_h": checker_data.flip_h,
        "flip_v": checker_data.flip_v,
        "rotation": checker_data.rotation,
    }
