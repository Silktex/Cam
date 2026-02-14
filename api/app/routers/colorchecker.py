"""
ColorChecker Router - Color checker detection and calibration workflow.
Endpoints for capturing, detecting, adjusting, and saving ColorChecker profiles.
"""
import uuid
import logging
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File
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
    wb_source_batch: Optional[str] = None


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

@router.get("/available-images")
async def list_available_images():
    """
    List all image files available in the colorchecker captures directory tree.
    Returns TIFF, JPEG, PNG, and RAW files that can be used for detection.
    Scans both MEDIA_DIR/colorchecker/captures and CAPTURES_DIR/colorchecker/captures.
    """
    image_extensions = {'.tiff', '.tif', '.jpg', '.jpeg', '.png', '.arw', '.cr2', '.nef', '.dng'}
    images = []
    seen_paths = set()

    # Scan directories for colorchecker captures
    scan_dirs = [
        settings.MEDIA_DIR / "colorchecker" / "captures",
        settings.CAPTURES_DIR / "colorchecker" / "captures",
    ]

    for base_dir in scan_dirs:
        if not base_dir.exists():
            continue
        for path in sorted(base_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in image_extensions:
                real_path = str(path.resolve())
                if real_path in seen_paths:
                    continue
                seen_paths.add(real_path)

                # Build URL relative to MEDIA_DIR if possible
                try:
                    rel = path.relative_to(settings.MEDIA_DIR)
                    url = f"/media/{rel}"
                except ValueError:
                    url = ""

                images.append({
                    "name": path.name,
                    "path": str(path),
                    "url": url,
                    "folder": path.parent.name,
                    "size": path.stat().st_size,
                })

    return {"images": images}


@router.get("/batches-with-raw")
async def list_batches_with_raw():
    """
    List capture batches that have RAW files available.
    Used by the UI for WB source batch selection.
    """
    from scripts.processing.raw_utils import is_raw_file

    batches = []
    if settings.CAPTURES_DIR.exists():
        for d in sorted(settings.CAPTURES_DIR.iterdir()):
            if d.is_dir() and (d / "raw").exists():
                raw_count = len([f for f in (d / "raw").iterdir() if is_raw_file(f)])
                if raw_count > 0:
                    batches.append({"name": d.name, "raw_count": raw_count})

    return {"batches": batches}


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


@router.post("/upload", response_model=CaptureResponse)
async def upload_colorchecker(file: UploadFile = File(...)):
    """
    Upload a ColorChecker image file instead of capturing from camera.
    Accepts common image formats (JPEG, PNG, TIFF).
    Saves to media/colorchecker/captures/ folder.
    """
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp'}
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(allowed_extensions))}"
        )

    # Create upload directory
    upload_dir = settings.MEDIA_DIR / "colorchecker" / "captures" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Save with timestamp to avoid collisions
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = Path(file.filename).stem.replace(" ", "_")
    dest_filename = f"colorchecker_upload_{timestamp}_{safe_name}{ext}"
    dest_path = upload_dir / dest_filename

    try:
        contents = await file.read()
        dest_path.write_bytes(contents)
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")

    rel_path = dest_path.relative_to(settings.MEDIA_DIR)
    file_url = f"/media/{rel_path}"

    logger.info(f"ColorChecker uploaded: {dest_filename} ({len(contents)} bytes)")

    return CaptureResponse(
        success=True,
        image_path=str(dest_path),
        image_url=file_url,
        filename=dest_filename,
    )


@router.post("/detect", response_model=DetectResponse)
async def detect_colorchecker(request: DetectRequest):
    """
    Detect ColorChecker in an image.
    Returns detection ID and overlay image URL for preview.

    When wb_source_batch is provided and the image is a RAW file, the checker RAW
    is re-processed using the subject batch's WB multipliers so that checker and
    subject share identical white balance before polynomial calibration.
    """
    from scripts.processing.calibration_service import CalibrationService, COLOUR_AVAILABLE
    from scripts.processing.raw_utils import extract_wb, load_raw_with_fixed_wb, is_raw_file
    import numpy as np

    if not COLOUR_AVAILABLE:
        raise HTTPException(
            status_code=500,
            detail="colour-science library not installed. Run: pip install colour-science colour-checker-detection"
        )

    image_path = Path(request.image_path)
    logger.info(f"Detect request for image: {request.image_path}")
    if request.wb_source_batch:
        logger.info(f"  WB source batch: {request.wb_source_batch}")

    # Handle relative paths - prepend media directory if needed
    if not image_path.is_absolute():
        image_path = settings.MEDIA_DIR / request.image_path
        logger.info(f"Resolved to absolute path: {image_path}")

    raw_extensions = {'.arw', '.cr2', '.nef', '.dng', '.raf', '.orf', '.rw2'}
    is_raw = image_path.suffix.lower() in raw_extensions
    image_override = None

    # WB-matched detection: re-process checker RAW with subject's WB
    if request.wb_source_batch and is_raw:
        if not image_path.exists():
            raise HTTPException(status_code=404, detail=f"Checker RAW not found: {image_path}")

        # Find first RAW in the subject batch
        subject_raw_dir = settings.CAPTURES_DIR / request.wb_source_batch / "raw"
        if not subject_raw_dir.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Subject batch raw folder not found: {subject_raw_dir}"
            )

        subject_raw = None
        for f in sorted(subject_raw_dir.iterdir()):
            if is_raw_file(f):
                subject_raw = f
                break

        if not subject_raw:
            raise HTTPException(
                status_code=404,
                detail=f"No RAW files found in {request.wb_source_batch}/raw"
            )

        # Extract WB from subject
        subject_wb = extract_wb(subject_raw)
        if not subject_wb:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to extract WB from {subject_raw.name}"
            )
        logger.info(f"  Subject WB from {subject_raw.name}: {subject_wb}")

        # Also log checker's own WB for comparison
        checker_wb = extract_wb(image_path)
        if checker_wb:
            logger.info(f"  Checker WB (original): {checker_wb}")

        # Re-process checker RAW with subject's WB
        rgb_16 = load_raw_with_fixed_wb(image_path, subject_wb)
        if rgb_16 is None:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process checker RAW with subject WB"
            )

        image_override = rgb_16.astype(np.float32) / 65535.0
        logger.info(f"  WB-matched image: shape={image_override.shape} range=[{image_override.min():.4f}, {image_override.max():.4f}]")

    elif is_raw and not request.wb_source_batch:
        # RAW file without WB source — find corresponding TIFF or JPEG
        logger.info(f"RAW file detected, looking for TIFF/JPEG alternative")
        tiff_path = image_path.parent.parent / "tiff" / f"{image_path.stem}.tiff"
        if tiff_path.exists():
            image_path = tiff_path
            logger.info(f"Using TIFF: {tiff_path}")
        else:
            jpeg_path = image_path.parent.parent / "full_webview" / f"{image_path.stem}.jpg"
            if jpeg_path.exists():
                image_path = jpeg_path
                logger.info(f"Using JPEG: {jpeg_path}")

    if image_override is None and not image_path.exists():
        logger.error(f"Image not found at: {image_path}")
        raise HTTPException(status_code=404, detail=f"Image not found: {request.image_path}")

    if image_override is None:
        logger.info(f"Image exists, size: {image_path.stat().st_size} bytes")

    try:
        calibration_service = CalibrationService()
        checker_data = calibration_service.detect_colorchecker(
            str(image_path),
            image_override=image_override,
        )

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
