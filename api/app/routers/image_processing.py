"""
Image Processing Router - Per-batch photometric PBR pipeline.

Mounted at /api/image-processing in main.py.
Manages process_track.json per batch and provides preview/save endpoints
for the 6-phase pipeline.
"""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from pathlib import Path
import logging

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

IMAGE_EXTENSIONS = {'.tiff', '.tif', '.png', '.jpg', '.jpeg', '.arw', '.cr2', '.nef', '.dng'}


def _get_batch_path(batch_name: str) -> Path:
    """Resolve batch folder path with path traversal protection."""
    batch_path = settings.CAPTURES_DIR / batch_name
    try:
        batch_path.resolve().relative_to(settings.CAPTURES_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid batch name")
    if not batch_path.exists():
        raise HTTPException(status_code=404, detail=f"Batch '{batch_name}' not found")
    return batch_path


def _count_images(batch_path: Path) -> int:
    """Count images in the best available source folder."""
    for folder_name in ['tiff', 'raw', 'cropped', 'color_calibrated']:
        folder = batch_path / folder_name
        if folder.exists():
            count = sum(
                1 for f in folder.iterdir()
                if f.suffix.lower() in IMAGE_EXTENSIONS
            )
            if count > 0:
                return count
    return 0


# ─── Pydantic Models ───

class PhaseUpdateRequest(BaseModel):
    status: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


class SaveRequest(BaseModel):
    save_through: str = "validate_export"


# ─── Endpoints ───

@router.get("/batches")
async def list_batches():
    """List all batches with their process_track phase statuses."""
    from scripts.processing.process_track_service import get_track, count_completed_phases, PHASES

    captures_dir = settings.CAPTURES_DIR
    if not captures_dir.exists():
        return {"batches": []}

    batches = []
    for folder in sorted(captures_dir.iterdir()):
        if not folder.is_dir():
            continue
        # Skip hidden/system folders
        if folder.name.startswith('.') or folder.name.startswith('_'):
            continue

        batch_name = folder.name
        image_count = _count_images(folder)

        # Load or infer track
        track = get_track(folder)
        if track:
            completed = count_completed_phases(track)
            phase_statuses = {
                name: track["phases"][name]["status"] for name in PHASES
            }
        else:
            completed = 0
            phase_statuses = {name: "pending" for name in PHASES}

        batches.append({
            "name": batch_name,
            "image_count": image_count,
            "completed_phases": completed,
            "total_phases": len(PHASES),
            "has_track": track is not None,
            "phase_statuses": phase_statuses,
        })

    return {"batches": batches}


@router.get("/track/{batch_name}")
async def get_track_endpoint(batch_name: str):
    """Get process_track.json for a batch."""
    from scripts.processing.process_track_service import get_track

    batch_path = _get_batch_path(batch_name)
    track = get_track(batch_path)
    if track is None:
        raise HTTPException(status_code=404, detail="No process track found. POST to create one.")
    return track


@router.post("/track/{batch_name}")
async def create_track(batch_name: str):
    """Initialize process_track.json for a batch, scanning existing folders for status."""
    from scripts.processing.process_track_service import (
        get_track, create_default_track, save_track, scan_existing_folders
    )

    batch_path = _get_batch_path(batch_name)

    # Check if track already exists
    existing = get_track(batch_path)
    if existing:
        return {"created": False, "message": "Track already exists", "track": existing}

    # Create default track
    track = create_default_track(batch_name)

    # Scan existing folders to infer statuses
    scanned = scan_existing_folders(batch_path)
    for phase_name, status in scanned.items():
        track["phases"][phase_name]["status"] = status

    save_track(batch_path, track)
    return {"created": True, "track": track}


@router.put("/track/{batch_name}/{phase}")
async def update_phase_endpoint(batch_name: str, phase: str, request: PhaseUpdateRequest):
    """Update a phase's params and/or status. Writes to JSON only, no processing."""
    from scripts.processing.process_track_service import update_phase

    batch_path = _get_batch_path(batch_name)

    try:
        track = update_phase(
            batch_path,
            phase,
            status=request.status,
            params=request.params,
        )
        return {"success": True, "track": track}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/preview/{batch_name}/{phase}")
async def preview_phase(batch_name: str, phase: str):
    """
    Generate JPEG preview by chaining all phases up to this one (top image only).
    Returns preview URL.
    """
    from scripts.processing.process_track_service import get_track, PHASES
    from scripts.processing.pipeline_renderer import render_preview, render_pbr_preview

    batch_path = _get_batch_path(batch_name)

    if phase not in PHASES:
        raise HTTPException(status_code=400, detail=f"Unknown phase '{phase}'")

    track = get_track(batch_path)
    if track is None:
        raise HTTPException(status_code=404, detail="No process track found")

    # PBR preview is special (needs all 9 images)
    # Run in thread to avoid blocking the async event loop
    if phase == "pbr":
        result = await asyncio.to_thread(render_pbr_preview, batch_path, track)
    else:
        result = await asyncio.to_thread(render_preview, batch_path, phase, track)

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Preview failed"))

    return result


@router.post("/save/{batch_name}")
async def save_full_pipeline(batch_name: str):
    """Run full pipeline from source -> save final output for ALL images."""
    from scripts.processing.process_track_service import get_track
    from scripts.processing.pipeline_renderer import render_and_save

    batch_path = _get_batch_path(batch_name)

    track = get_track(batch_path)
    if track is None:
        raise HTTPException(status_code=404, detail="No process track found")

    result = await asyncio.to_thread(render_and_save, batch_path, track)

    if not result.get("success") and result.get("errors"):
        # Partial success is OK, return with errors
        pass

    return result


@router.post("/save/{batch_name}/{phase}")
async def save_through_phase(batch_name: str, phase: str):
    """Save output through a specific phase (checkpoint save)."""
    from scripts.processing.process_track_service import get_track, PHASES
    from scripts.processing.pipeline_renderer import render_and_save

    batch_path = _get_batch_path(batch_name)

    if phase not in PHASES:
        raise HTTPException(status_code=400, detail=f"Unknown phase '{phase}'")

    track = get_track(batch_path)
    if track is None:
        raise HTTPException(status_code=404, detail="No process track found")

    result = await asyncio.to_thread(render_and_save, batch_path, track, phase)
    return result


# ─── Calibration: extract profile data into track ───

class ApplyProfileToTrackRequest(BaseModel):
    profile_name: str


@router.post("/apply-profile/{batch_name}")
async def apply_profile_to_track(batch_name: str, request: ApplyProfileToTrackRequest):
    """
    Load a calibration profile NPZ and compute matrix_3x3, checker_wb, checker_raw_path.
    Writes them into the process track's color phase so the pipeline renderer can
    re-demosaic RAW files with the correct fixed WB and apply color correction.
    """
    import numpy as np
    from scripts.processing.process_track_service import update_phase
    from scripts.processing.calibration_service import CalibrationService

    batch_path = _get_batch_path(batch_name)
    cal_service = CalibrationService()

    # Resolve profile NPZ path
    profile_path = cal_service.profiles_dir / f"{request.profile_name}.npz"
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail=f"Profile '{request.profile_name}' not found")

    try:
        npz = np.load(str(profile_path), allow_pickle=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load profile: {e}")

    params: Dict[str, Any] = {"profile_name": request.profile_name}

    # Compute 3x3 color correction matrix from detected/reference swatches
    # Same algorithm as calibrate_and_crop.py and post_capture_service.py
    detected = npz['detected_swatches'].astype(np.float64)
    reference = npz['reference_swatches'].astype(np.float64)

    NEUTRAL_INDICES = list(range(18, 24))
    NEUTRAL_WEIGHT = 10.0
    RIDGE_LAMBDA = 0.30
    HUBER_DELTA = 0.03
    HUBER_ITERATIONS = 3

    det_white = detected[18]
    ref_white = reference[18]
    safe_ref = np.where(ref_white > 1e-6, ref_white, 1e-6)
    wp_scale = det_white / safe_ref
    adapted_ref = reference * wp_scale

    D = detected
    I3 = np.eye(3)
    base_weights = np.ones(24)
    base_weights[NEUTRAL_INDICES] = NEUTRAL_WEIGHT
    weights = base_weights.copy()
    M = None

    for iteration in range(max(1, HUBER_ITERATIONS)):
        W = np.diag(weights)
        DtWD = D.T @ W @ D + RIDGE_LAMBDA * I3
        M = np.zeros((3, 3))
        for c in range(3):
            r_c = adapted_ref[:, c]
            e_c = I3[:, c]
            M[c, :] = np.linalg.solve(DtWD, D.T @ W @ r_c + RIDGE_LAMBDA * e_c)
        corrected = (M @ D.T).T
        if iteration < HUBER_ITERATIONS - 1:
            for i in range(24):
                r = np.sqrt(np.sum((corrected[i] - adapted_ref[i]) ** 2))
                huber_w = 1.0 if r <= HUBER_DELTA else HUBER_DELTA / r
                weights[i] = base_weights[i] * huber_w

    for c in range(3):
        rs = M[c, :].sum()
        if abs(rs) > 1e-6:
            M[c, :] /= rs

    params["matrix_3x3"] = M.tolist()
    logger.info(f"Computed 3x3 matrix diagonal: [{M[0,0]:.4f}, {M[1,1]:.4f}, {M[2,2]:.4f}]")

    # Read checker_wb directly from NPZ (saved at profile creation time).
    # checker_wb is a property of the lighting rig + sensor — constant across batches.
    # The checker_raw_path stored in the NPZ is an absolute path from when the
    # profile was created and may no longer exist, so we don't rely on it at runtime.
    checker_wb_arr = npz.get('checker_wb', None)
    if checker_wb_arr is not None and len(checker_wb_arr) > 0:
        params["checker_wb"] = checker_wb_arr.tolist()
        logger.info(f"Loaded checker WB from profile: {params['checker_wb']}")
    else:
        # Fallback: try extracting from checker_raw_path (may not exist)
        checker_raw_path = str(npz.get('checker_raw_path', ''))
        if checker_raw_path:
            try:
                from scripts.processing.raw_utils import extract_wb
                from pathlib import Path as _Path
                if _Path(checker_raw_path).exists():
                    wb = extract_wb(checker_raw_path)
                    if wb:
                        params["checker_wb"] = wb
                        logger.info(f"Extracted checker WB from RAW: {wb}")
                else:
                    logger.warning(
                        f"Checker RAW not found at {checker_raw_path}. "
                        f"Re-save the profile to embed checker_wb directly."
                    )
            except Exception as e:
                logger.warning(f"Could not extract WB: {e}")

    try:
        track = update_phase(batch_path, "color", status="completed", params=params)
        return {"success": True, "params_saved": list(params.keys()), "track": track}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Exposure / Roughness preview endpoints ───

class ExposurePreviewRequest(BaseModel):
    offset: float = 0.0
    method: str = "exposure_match"


class RoughnessPreviewRequest(BaseModel):
    scale: float = 1.0
    pbr_mode: str = "grayscale"


@router.post("/exposure/preview/{batch_name}")
async def exposure_preview(batch_name: str, request: ExposurePreviewRequest):
    """Preview exposure adjustment on the top image."""
    from scripts.processing.exposure_service import preview_exposure

    batch_path = _get_batch_path(batch_name)
    result = preview_exposure(str(batch_path), offset=request.offset, method=request.method)

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@router.post("/roughness/preview/{batch_name}")
async def roughness_preview(batch_name: str, request: RoughnessPreviewRequest):
    """Preview roughness scale adjustment."""
    from scripts.processing.exposure_service import preview_roughness_scale

    batch_path = _get_batch_path(batch_name)
    result = preview_roughness_scale(str(batch_path), scale=request.scale, pbr_mode=request.pbr_mode)

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result
