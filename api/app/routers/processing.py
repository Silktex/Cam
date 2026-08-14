"""
Processing Router - Image processing pipeline endpoints
Handles crop, color calibration, and PBR map generation
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path
import logging

from app.config import settings
from app.services.database import get_batch, update_batch_status, sync_batch

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Pydantic Models ───

class ManualCropRequest(BaseModel):
    batch_name: str
    bbox: List[int]  # [x1, y1, x2, y2]
    apply_to_all: bool = True
    specific_images: Optional[List[str]] = None


class AutoCropRequest(BaseModel):
    batch_name: str
    prompt: str = "fabric sample"
    crop_size: int = 3200


class ReconvertTiffRequest(BaseModel):
    path: str  # Relative path under captures dir (e.g. "colorchecker/captures")
    checker_raw_path: Optional[str] = None  # Use this RAW's WB for all conversions


class CalibrateRequest(BaseModel):
    batch_name: str
    profile_name: Optional[str] = None  # Use saved profile
    colorchecker_image: Optional[str] = None  # Detect from image
    checker_raw_path: Optional[str] = None  # RAW path for fixed WB calibration


class DetectColorCheckerRequest(BaseModel):
    image_path: str
    save_profile: bool = False
    profile_name: Optional[str] = None


class PBRRequest(BaseModel):
    batch_name: str
    mode: str = "grayscale"  # grayscale, colored, both
    selected_images: Optional[List[str]] = None  # None = all images


# ─── Material Tools Pydantic Models ───

class EqualizePreviewRequest(BaseModel):
    batch_name: str
    method: str = "clahe"  # clahe, histogram_match, exposure_match
    reference_image: Optional[str] = None
    clip_limit: float = 2.0


class EqualizeApplyRequest(BaseModel):
    batch_name: str
    method: str = "clahe"
    reference_image: Optional[str] = None
    clip_limit: float = 2.0
    apply_to_all: bool = True


class DelightPreviewRequest(BaseModel):
    batch_name: str
    blur_radius: int = 200
    strength: float = 1.0
    method: str = "gaussian"  # gaussian, frequency_separation


class DelightApplyRequest(BaseModel):
    batch_name: str
    blur_radius: int = 200
    strength: float = 1.0
    method: str = "gaussian"
    apply_to_all: bool = True


class FlattenPreviewRequest(BaseModel):
    batch_name: str
    strength: float = 1.0
    smoothing_radius: int = 0
    pbr_mode: str = "grayscale"  # grayscale or color


class FlattenApplyRequest(BaseModel):
    batch_name: str
    strength: float = 1.0
    smoothing_radius: int = 0
    pbr_mode: str = "grayscale"
    apply_to_all: bool = True


class PerspectivePoint(BaseModel):
    x: float
    y: float


class PerspectiveDetectRequest(BaseModel):
    batch_name: str


class PerspectivePreviewRequest(BaseModel):
    batch_name: str
    source_points: List[PerspectivePoint]
    dest_points: Optional[List[PerspectivePoint]] = None


class PerspectiveApplyRequest(BaseModel):
    batch_name: str
    source_points: List[PerspectivePoint]
    dest_points: Optional[List[PerspectivePoint]] = None
    apply_to_all: bool = True


class SeamlessAnalyzeRequest(BaseModel):
    batch_name: str
    blend_width: Optional[int] = None


class SeamlessPreviewRequest(BaseModel):
    batch_name: str
    method: str = "overlay"  # overlay, mirror, poisson
    blend_width: int = 64
    spots_removal: bool = False
    color_equalizer: int = 0
    tile_count: int = 2


class SeamlessApplyRequest(BaseModel):
    batch_name: str
    method: str = "overlay"  # overlay, mirror, poisson
    blend_width: int = 64
    spots_removal: bool = False
    color_equalizer: int = 0


class TilePreviewRequest(BaseModel):
    batch_name: str
    tile_x: int = 2
    tile_y: int = 2
    offset_x: float = 0.0
    offset_y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    overlap: float = 0.0
    half_drop: bool = False


class TileApplyRequest(BaseModel):
    batch_name: str
    tile_x: int = 2
    tile_y: int = 2
    offset_x: float = 0.0
    offset_y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    overlap: float = 0.0
    half_drop: bool = False
    output_resolution: Optional[List[int]] = None


class ValidateCheckRequest(BaseModel):
    batch_name: str
    mode: str = "grayscale"
    albedo_dark_threshold: float = 30.0
    metal_range: Optional[List[float]] = None


class CloneInpaintRequest(BaseModel):
    batch_name: str
    mask_data: str  # base64 mask
    method: str = "telea"
    radius: int = 5


class CloneStampRequest(BaseModel):
    batch_name: str
    source_pos: PerspectivePoint
    target_pos: PerspectivePoint
    radius: int = 50
    fade: float = 1.0
    blur_mask: float = 0.0
    mirror: bool = False


class CloneApplyRequest(BaseModel):
    batch_name: str
    operations: List[dict]


class StraightenAnalyzeRequest(BaseModel):
    batch_name: str
    grid_divisions: int = 20
    direction: str = 'both'  # both, warp, weft


class StraightenPreviewRequest(BaseModel):
    batch_name: str
    mode: str = 'auto'  # auto, skew, bow
    strength: float = 1.0
    direction: str = 'both'
    grid_divisions: int = 20
    manual_skew_angle: Optional[float] = None


class StraightenApplyRequest(BaseModel):
    batch_name: str
    mode: str = 'auto'
    strength: float = 1.0
    direction: str = 'both'
    grid_divisions: int = 20
    manual_skew_angle: Optional[float] = None


# ─── Helper Functions ───

def get_batch_path(batch_name: str) -> Path:
    """Get full path to batch folder"""
    return settings.CAPTURES_DIR / batch_name


def validate_batch(batch_name: str) -> dict:
    """Validate batch exists"""
    batch = get_batch(batch_name)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_name}")

    batch_path = get_batch_path(batch_name)
    if not batch_path.exists():
        raise HTTPException(status_code=404, detail=f"Batch folder not found: {batch_path}")

    return batch


def _find_top_image_for_tool(batch_path: Path, tool: str) -> Path:
    """Resolve the top image path for a given tool using source folder priority."""
    source_priority = {
        'perspective': ['cropped', 'tiff'],
        'flatten': ['equalized', 'color_calibrated', 'cropped', 'tiff'],
        'straighten': ['perspective_corrected', 'color_calibrated', 'cropped', 'tiff', 'raw'],
        'seamless': ['delighted', 'flattened', 'equalized', 'color_calibrated', 'cropped', 'tiff'],
    }
    image_exts = {'.tiff', '.tif', '.png', '.jpg', '.jpeg', '.arw', '.cr2', '.nef', '.dng'}
    for folder_name in source_priority.get(tool, ['cropped', 'tiff']):
        folder = batch_path / folder_name
        if folder.exists() and any(folder.iterdir()):
            images = sorted(f for f in folder.iterdir() if f.suffix.lower() in image_exts)
            if images:
                for img in images:
                    if '_top' in img.name.lower() or img.name.lower().startswith('top'):
                        return img
                return images[0]
    raise HTTPException(status_code=404, detail="No source images found for this tool")


# ─── Crop Endpoints (Interactive Workflow) ───

class CropPoint(BaseModel):
    x: float
    y: float


class CropApplyRequest(BaseModel):
    batch_name: str
    bbox: Optional[List[int]] = None  # [x1, y1, x2, y2] - legacy simple crop
    crop_type: str = "manual"  # "manual" or "auto"
    points: Optional[List[CropPoint]] = None  # 4-point perspective crop
    rotation: float = 0  # Rotation angle in degrees


class PreviewCropRequest(BaseModel):
    batch_name: str
    bbox: List[int]  # [x1, y1, x2, y2]


@router.get("/crop/top-image/{batch_name}")
async def get_top_image_for_crop(batch_name: str):
    """
    Step 1: Get top image for crop interface.
    Returns image dimensions and thumbnail URL for the crop selector.
    """
    validate_batch(batch_name)
    batch_path = get_batch_path(batch_name)

    from scripts.processing.crop_service import CropService

    try:
        crop_service = CropService()
        result = crop_service.get_top_image_for_crop(str(batch_path))

        if not result:
            raise HTTPException(status_code=404, detail="No images found in batch")

        return result

    except Exception as e:
        logger.error(f"Get top image failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/crop/auto-detect")
async def auto_detect_crop(request: AutoCropRequest):
    """
    Step 2a: Auto-detect crop boundary on TOP image only.
    Returns detected bbox and preview without saving anything.
    User can accept or reject, then call /crop/apply.
    """
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.crop_service import CropService

    try:
        crop_service = CropService(use_gpu=settings.USE_GPU)
        result = crop_service.auto_detect_crop(str(batch_path), crop_size=request.crop_size)

        return result

    except Exception as e:
        logger.error(f"Auto-detect crop failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/crop/preview-manual")
async def preview_manual_crop(request: PreviewCropRequest):
    """
    Step 2b: Preview manual crop on TOP image without saving.
    User draws bbox, we show preview. If accepted, call /crop/apply.
    """
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.crop_service import CropService

    try:
        crop_service = CropService()
        result = crop_service.preview_manual_crop(str(batch_path), request.bbox)

        return result

    except Exception as e:
        logger.error(f"Preview manual crop failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/crop/apply")
async def apply_crop(request: CropApplyRequest, background_tasks: BackgroundTasks):
    """
    Step 3: Apply confirmed crop to ALL images in batch.
    Supports both simple bbox crop and 4-point perspective transform with rotation.
    """
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.crop_service import CropService

    try:
        crop_service = CropService()

        # Update status to in_progress
        update_batch_status(request.batch_name, 'crop', 'in_progress', crop_type=request.crop_type)

        # Convert points to dict format if provided
        points_dict = None
        if request.points and len(request.points) == 4:
            points_dict = [{'x': p.x, 'y': p.y} for p in request.points]

        results = crop_service.apply_crop_to_all(
            batch_path=str(batch_path),
            bbox=request.bbox,
            crop_type=request.crop_type,
            points=points_dict,
            rotation=request.rotation,
        )

        # Count successes
        success_count = sum(1 for r in results if r.success)
        total_count = len(results)

        # Update status based on results
        if success_count > 0:
            update_batch_status(request.batch_name, 'crop', 'completed', crop_type=request.crop_type)
        else:
            update_batch_status(request.batch_name, 'crop', 'pending', crop_type=request.crop_type)

        # Sync batch to update file counts
        background_tasks.add_task(sync_batch, request.batch_name)

        return {
            "success": success_count > 0,
            "batch_name": request.batch_name,
            "crop_type": request.crop_type,
            "rotation": request.rotation,
            "processed": success_count,
            "total": total_count,
            "results": [
                {
                    "source": r.source_path,
                    "output": r.output_path,
                    "success": r.success,
                    "error": r.error,
                }
                for r in results
            ]
        }

    except Exception as e:
        logger.error(f"Apply crop failed: {e}")
        update_batch_status(request.batch_name, 'crop', 'pending')
        raise HTTPException(status_code=500, detail=str(e))


# ─── Legacy Crop Endpoints (backward compatibility) ───

@router.post("/crop/manual")
async def manual_crop(request: ManualCropRequest, background_tasks: BackgroundTasks):
    """Legacy: Direct manual crop. Use /crop/apply instead."""
    apply_request = CropApplyRequest(
        batch_name=request.batch_name,
        bbox=request.bbox,
        crop_type="manual"
    )
    return await apply_crop(apply_request, background_tasks)


@router.post("/crop/auto")
async def auto_crop(request: AutoCropRequest, background_tasks: BackgroundTasks):
    """Legacy: Direct auto crop. Use /crop/auto-detect then /crop/apply."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.crop_service import CropService

    try:
        crop_service = CropService(use_gpu=settings.USE_GPU)

        # Auto-detect first
        detect_result = crop_service.auto_detect_crop(str(batch_path), crop_size=request.crop_size)

        if not detect_result.get("success"):
            return {
                "success": False,
                "batch_name": request.batch_name,
                "processed": 0,
                "total": 0,
                "error": detect_result.get("error", "Auto-detect failed"),
                "results": []
            }

        # Apply to all
        update_batch_status(request.batch_name, 'crop', 'in_progress', crop_type='auto')

        results = crop_service.apply_crop_to_all(
            batch_path=str(batch_path),
            bbox=detect_result["bbox"],
            crop_type="auto"
        )

        success_count = sum(1 for r in results if r.success)
        total_count = len(results)

        if success_count > 0:
            update_batch_status(request.batch_name, 'crop', 'completed', crop_type='auto')
        else:
            update_batch_status(request.batch_name, 'crop', 'pending', crop_type='auto')

        background_tasks.add_task(sync_batch, request.batch_name)

        return {
            "success": success_count > 0,
            "batch_name": request.batch_name,
            "processed": success_count,
            "total": total_count,
            "bbox": detect_result["bbox"],
            "results": [
                {
                    "source": r.source_path,
                    "output": r.output_path,
                    "success": r.success,
                    "error": r.error,
                    "bbox": r.bbox
                }
                for r in results
            ]
        }

    except Exception as e:
        logger.error(f"Auto crop failed: {e}")
        update_batch_status(request.batch_name, 'crop', 'pending')
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/crop/preview/{batch_name}")
async def get_crop_preview(batch_name: str):
    """Legacy: Get preview. Use /crop/top-image/{batch_name} instead."""
    return await get_top_image_for_crop(batch_name)


# ─── TIFF Re-conversion Endpoint ───

@router.post("/reconvert-tiff")
async def reconvert_tiff(request: ReconvertTiffRequest):
    """
    Re-convert all RAW files to TIFF using standardized linear sRGB settings.

    Accepts a relative path under the captures directory (e.g. "colorchecker/captures").
    Looks for raw/ subfolder at that path, outputs TIFFs to tiff/ subfolder.
    Optionally accepts a checker_raw_path to use that file's WB for all conversions.
    """
    # Resolve path relative to captures dir — prevent path traversal
    rel = Path(request.path)
    if '..' in rel.parts:
        raise HTTPException(status_code=400, detail="Invalid path")
    batch_path = settings.CAPTURES_DIR / rel

    if not batch_path.exists() or not batch_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Folder not found: {request.path}")

    raw_dir = batch_path / "raw"
    if not raw_dir.exists():
        raise HTTPException(status_code=404, detail=f"No raw/ folder in {request.path}")

    tiff_dir = batch_path / "tiff"
    tiff_dir.mkdir(exist_ok=True)

    from scripts.processing.raw_utils import (
        is_raw_file, extract_wb, load_raw, load_raw_with_fixed_wb, save_tiff
    )

    # Extract fixed WB if checker RAW path provided
    fixed_wb = None
    if request and request.checker_raw_path:
        checker_path = Path(request.checker_raw_path)
        if not checker_path.exists():
            raise HTTPException(status_code=404, detail=f"Checker RAW not found: {request.checker_raw_path}")
        fixed_wb = extract_wb(checker_path)
        if not fixed_wb:
            raise HTTPException(status_code=500, detail=f"Could not extract WB from {request.checker_raw_path}")
        logger.info(f"Using fixed WB from {checker_path.name}: {fixed_wb}")

    results = {"success": 0, "failed": 0, "total": 0, "files": []}

    for raw_file in sorted(raw_dir.iterdir()):
        if not is_raw_file(raw_file):
            continue

        results["total"] += 1
        tiff_path = tiff_dir / f"{raw_file.stem}.tiff"

        try:
            if fixed_wb:
                rgb = load_raw_with_fixed_wb(raw_file, fixed_wb)
            else:
                rgb = load_raw(raw_file)

            if rgb is None:
                raise ValueError("RAW loading returned None")

            if not save_tiff(rgb, tiff_path, compression='lzw'):
                raise ValueError("TIFF save failed")

            results["success"] += 1
            results["files"].append({"name": raw_file.name, "status": "ok"})
            logger.info(f"Re-converted: {raw_file.name} -> {tiff_path.name}")

        except Exception as e:
            results["failed"] += 1
            results["files"].append({"name": raw_file.name, "status": "error", "error": str(e)})
            logger.error(f"Failed to re-convert {raw_file.name}: {e}")

    return {
        "path": request.path,
        "fixed_wb": fixed_wb,
        **results,
    }


# ─── Color Calibration Endpoints ───

@router.post("/colorchecker/detect")
async def detect_colorchecker(request: DetectColorCheckerRequest):
    """
    Detect ColorChecker in an image and optionally save as profile.
    """
    image_path = Path(request.image_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail=f"Image not found: {request.image_path}")

    from scripts.processing.calibration_service import CalibrationService, COLOUR_AVAILABLE

    if not COLOUR_AVAILABLE:
        raise HTTPException(
            status_code=500,
            detail="colour-science library not installed. Run: pip install colour-science colour-checker-detection"
        )

    try:
        calibration_service = CalibrationService()
        checker_data = calibration_service.detect_colorchecker(str(image_path))

        if not checker_data:
            raise HTTPException(status_code=404, detail="No ColorChecker detected in image")

        result = {
            "success": True,
            "source_image": checker_data.source_image,
            "swatches_detected": len(checker_data.detected_swatches),
        }

        if request.save_profile and request.profile_name:
            profile_path = calibration_service.save_colorchecker_profile(
                checker_data,
                request.profile_name
            )
            result["profile_saved"] = True
            result["profile_path"] = profile_path

        return result

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"CalibrationService not available: {e}")
    except Exception as e:
        logger.error(f"ColorChecker detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/colorchecker/profiles")
async def list_colorchecker_profiles():
    """List all saved ColorChecker profiles"""
    from scripts.processing.calibration_service import CalibrationService, COLOUR_AVAILABLE

    if not COLOUR_AVAILABLE:
        return {"profiles": [], "warning": "colour-science library not installed"}

    try:
        calibration_service = CalibrationService()
        profiles = calibration_service.list_profiles()
        return {"profiles": profiles}

    except Exception as e:
        logger.error(f"List profiles failed: {e}")
        return {"profiles": [], "error": str(e)}


@router.post("/calibrate")
async def calibrate_batch(request: CalibrateRequest, background_tasks: BackgroundTasks):
    """
    Apply color calibration to batch images.
    Either provide a saved profile name or an image to detect ColorChecker from.
    """
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.calibration_service import CalibrationService, COLOUR_AVAILABLE

    if not COLOUR_AVAILABLE:
        raise HTTPException(
            status_code=500,
            detail="colour-science library not installed"
        )

    try:
        calibration_service = CalibrationService()

        checker_data = None

        if request.profile_name:
            checker_data = calibration_service.load_colorchecker_profile(request.profile_name)
            if not checker_data:
                raise HTTPException(
                    status_code=404,
                    detail=f"Profile not found: {request.profile_name}"
                )
        elif request.colorchecker_image:
            image_path = Path(request.colorchecker_image)
            if not image_path.exists():
                raise HTTPException(
                    status_code=404,
                    detail=f"ColorChecker image not found: {request.colorchecker_image}"
                )
            checker_data = calibration_service.detect_colorchecker(str(image_path))
            if not checker_data:
                raise HTTPException(
                    status_code=400,
                    detail="No ColorChecker detected in provided image"
                )
        else:
            raise HTTPException(
                status_code=400,
                detail="Must provide either profile_name or colorchecker_image"
            )

        update_batch_status(request.batch_name, 'calibration', 'in_progress')

        results = calibration_service.calibrate_batch(
            batch_path=str(batch_path),
            checker_data=checker_data,
            checker_raw_path=request.checker_raw_path,
        )

        success_count = sum(1 for r in results if r.success)
        total_count = len(results)

        if success_count > 0:
            update_batch_status(request.batch_name, 'calibration', 'completed')
        else:
            update_batch_status(request.batch_name, 'calibration', 'pending')

        background_tasks.add_task(sync_batch, request.batch_name)

        return {
            "success": success_count > 0,
            "batch_name": request.batch_name,
            "processed": success_count,
            "total": total_count,
            "results": [
                {
                    "source": r.source_path,
                    "output": r.output_path,
                    "success": r.success,
                    "error": r.error,
                }
                for r in results
            ]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Calibration failed: {e}")
        update_batch_status(request.batch_name, 'calibration', 'pending')
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calibrate/preview/{batch_name}")
async def get_calibration_preview(batch_name: str):
    """Get before/after comparison for calibration preview"""
    validate_batch(batch_name)
    batch_path = get_batch_path(batch_name)

    from scripts.processing.calibration_service import CalibrationService, COLOUR_AVAILABLE

    if not COLOUR_AVAILABLE:
        raise HTTPException(status_code=500, detail="colour-science not available")

    try:
        calibration_service = CalibrationService()
        preview = calibration_service.get_preview_comparison(str(batch_path))

        if not preview:
            raise HTTPException(status_code=404, detail="No preview available")

        return preview

    except Exception as e:
        logger.error(f"Get calibration preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── PBR Generation Endpoints ───

@router.post("/pbr")
async def generate_pbr(request: PBRRequest, background_tasks: BackgroundTasks):
    """
    Generate PBR maps (albedo, normals, roughness, height) from calibrated images.

    Modes:
    - grayscale: Uses grayscale photometric stereo (faster)
    - colored: Uses colored photometric stereo (preserves color info)
    - both: Generates both grayscale and colored outputs
    """
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    if request.mode not in ['grayscale', 'colored', 'both']:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {request.mode}")

    from scripts.processing.pbr_service import PBRService

    try:
        pbr_service = PBRService()

        update_batch_status(request.batch_name, 'pbr', 'in_progress', pbr_mode=request.mode)

        result = pbr_service.generate(
            batch_path=str(batch_path),
            mode=request.mode,
            selected_images=request.selected_images
        )

        if result.success:
            update_batch_status(request.batch_name, 'pbr', 'completed', pbr_mode=request.mode)
        else:
            update_batch_status(request.batch_name, 'pbr', 'pending', pbr_mode=request.mode)

        background_tasks.add_task(sync_batch, request.batch_name)

        return {
            "success": result.success,
            "batch_name": request.batch_name,
            "mode": request.mode,
            "images_processed": result.images_processed,
            "outputs": result.outputs,
            "error": result.error,
        }

    except Exception as e:
        logger.error(f"PBR generation failed: {e}")
        update_batch_status(request.batch_name, 'pbr', 'pending')
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pbr/preview/{batch_name}")
async def get_pbr_preview(batch_name: str):
    """Get preview of generated PBR maps"""
    validate_batch(batch_name)
    batch_path = get_batch_path(batch_name)

    # Check for output folders
    grayscale_folder = batch_path / "pbr_grayscale"
    colored_folder = batch_path / "pbr_colored"

    result = {
        "batch_name": batch_name,
        "grayscale": None,
        "colored": None,
    }

    def get_map_urls(folder: Path, mode: str) -> dict:
        if not folder.exists():
            return None

        maps = {}
        for map_type in ['albedo', 'normals', 'roughness', 'height_map']:
            # Check for .png first (new format), then .tiff (legacy)
            for ext in ['.png', '.tiff']:
                map_path = folder / f"{map_type}{ext}"
                if map_path.exists():
                    rel_path = map_path.relative_to(settings.CAPTURES_DIR)
                    maps[map_type] = f"/media/captures/{rel_path}"
                    break

        return maps if maps else None

    result["grayscale"] = get_map_urls(grayscale_folder, "grayscale")
    result["colored"] = get_map_urls(colored_folder, "colored")

    if not result["grayscale"] and not result["colored"]:
        raise HTTPException(status_code=404, detail="No PBR maps generated yet")

    return result


# ─── Pipeline Status ───

@router.get("/status/{batch_name}")
async def get_processing_status(batch_name: str):
    """Get full processing pipeline status for a batch"""
    batch = validate_batch(batch_name)
    batch_path = get_batch_path(batch_name)

    # Check what folders exist
    folders = {
        "tiff": (batch_path / "tiff").exists(),
        "raw": (batch_path / "raw").exists(),
        "cropped": (batch_path / "cropped").exists(),
        "color_calibrated": (batch_path / "color_calibrated").exists(),
        "pbr_grayscale": (batch_path / "pbr_grayscale").exists(),
        "pbr_colored": (batch_path / "pbr_colored").exists(),
    }

    return {
        "batch_name": batch_name,
        "crop_status": batch.get("crop_status", "pending"),
        "crop_type": batch.get("crop_type"),
        "calibration_status": batch.get("calibration_status", "pending"),
        "pbr_status": batch.get("pbr_status", "pending"),
        "pbr_mode": batch.get("pbr_mode"),
        "folders": folders,
    }


# ─── Material Tools Pipeline Status ───

@router.get("/tools/status/{batch_name}")
async def get_tools_status(batch_name: str):
    """Check which pipeline output folders exist for a batch."""
    validate_batch(batch_name)
    batch_path = get_batch_path(batch_name)

    def _exists(name: str) -> bool:
        for candidate in [batch_path / name, batch_path / "output" / name]:
            if candidate.exists() and any(candidate.iterdir()):
                return True
        return False

    return {
        "batch_name": batch_name,
        "perspective_corrected": _exists("perspective_corrected"),
        "equalized": _exists("equalized"),
        "flattened": _exists("flattened"),
        "delighted": _exists("delighted"),
        "seamless": _exists("seamless"),
        "tiled": _exists("tiled"),
    }


# ═══════════════════════════════════════════════════════════
# Material Creation Tools — Equalize, Delight, Perspective,
# Seamless, Tile, Validate, Clone
# ═══════════════════════════════════════════════════════════


# ─── Tool Image Endpoint (shared) ───

@router.get("/{tool}/image/{batch_name}")
async def get_tool_image(tool: str, batch_name: str):
    """
    Get the top/source image for any processing tool.
    Returns image info and thumbnail URLs.
    """
    validate_batch(batch_name)
    batch_path = get_batch_path(batch_name)

    # Determine source folder based on tool pipeline order
    source_priority = {
        'equalize': ['color_calibrated', 'cropped', 'tiff'],
        'flatten': ['equalized', 'color_calibrated', 'cropped', 'tiff'],
        'delight': ['flattened', 'equalized', 'color_calibrated', 'cropped', 'tiff'],
        'perspective': ['cropped', 'tiff'],
        'straighten': ['perspective_corrected', 'color_calibrated', 'cropped', 'tiff', 'raw'],
        'seamless': ['straightened', 'delighted', 'flattened', 'equalized', 'color_calibrated', 'cropped', 'tiff'],
        'tile': ['seamless', 'straightened', 'delighted', 'flattened', 'equalized', 'cropped', 'tiff'],
        'validate': ['pbr_grayscale', 'pbr_colored'],
        'clone': ['seamless', 'straightened', 'delighted', 'flattened', 'equalized', 'cropped', 'tiff'],
    }

    folders_to_check = source_priority.get(tool, ['cropped', 'tiff'])
    source_folder = None
    for folder_name in folders_to_check:
        folder = batch_path / folder_name
        if folder.exists() and any(folder.iterdir()):
            source_folder = folder
            break

    if not source_folder:
        raise HTTPException(status_code=404, detail="No source images found for this tool")

    # List images
    image_exts = {'.tiff', '.tif', '.png', '.jpg', '.jpeg', '.arw', '.cr2', '.nef', '.dng'}
    images = sorted([
        f for f in source_folder.iterdir()
        if f.suffix.lower() in image_exts
    ])

    if not images:
        raise HTTPException(status_code=404, detail="No images in source folder")

    # Find top image
    top = None
    for img in images:
        if '_top' in img.name.lower() or img.name.lower().startswith('top'):
            top = img
            break
    if not top:
        top = images[0]

    # Check for thumbnails
    thumb_folder = source_folder.name + "_thumbnail"
    thumb_path = batch_path / thumb_folder / f"{top.stem}.jpg"
    webview_path = batch_path / "full_webview" / f"{top.stem}.jpg"
    generic_thumb = batch_path / "thumbnail" / f"{top.stem}.jpg"

    if thumb_path.exists():
        preview_url = f"/media/captures/{batch_name}/{thumb_folder}/{top.stem}.jpg"
    elif webview_path.exists():
        preview_url = f"/media/captures/{batch_name}/full_webview/{top.stem}.jpg"
    elif generic_thumb.exists():
        preview_url = f"/media/captures/{batch_name}/thumbnail/{top.stem}.jpg"
    else:
        preview_url = f"/media/captures/{batch_name}/{source_folder.name}/{top.name}"

    return {
        "batch_name": batch_name,
        "source_folder": source_folder.name,
        "filename": top.name,
        "preview_url": preview_url,
        "image_count": len(images),
        "images": [img.name for img in images],
    }


# ─── Equalize Endpoints ───

@router.post("/equalize/preview")
async def equalize_preview(request: EqualizePreviewRequest):
    """Preview equalization on the top image."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.equalize_service import preview

    try:
        result = preview(
            batch_path=str(batch_path),
            method=request.method,
            reference_image=request.reference_image,
            clip_limit=request.clip_limit,
        )
        return result
    except Exception as e:
        logger.error(f"Equalize preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/equalize/apply")
async def equalize_apply(request: EqualizeApplyRequest, background_tasks: BackgroundTasks):
    """Apply equalization to all images in batch."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.equalize_service import apply

    try:
        result = apply(
            batch_path=str(batch_path),
            method=request.method,
            reference_image=request.reference_image,
            clip_limit=request.clip_limit,
        )

        background_tasks.add_task(sync_batch, request.batch_name)
        return result
    except Exception as e:
        logger.error(f"Equalize apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Delight Endpoints ───

@router.post("/delight/preview")
async def delight_preview(request: DelightPreviewRequest):
    """Preview delighting on the top image."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.delight_service import preview

    try:
        result = preview(
            batch_path=str(batch_path),
            blur_radius=request.blur_radius,
            strength=request.strength,
            method=request.method,
        )
        return result
    except Exception as e:
        logger.error(f"Delight preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delight/apply")
async def delight_apply(request: DelightApplyRequest, background_tasks: BackgroundTasks):
    """Apply delighting to all images in batch."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.delight_service import apply

    try:
        result = apply(
            batch_path=str(batch_path),
            blur_radius=request.blur_radius,
            strength=request.strength,
            method=request.method,
        )

        background_tasks.add_task(sync_batch, request.batch_name)
        return result
    except Exception as e:
        logger.error(f"Delight apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Flatten Endpoints ───

@router.post("/flatten/preview")
async def flatten_preview(request: FlattenPreviewRequest):
    """Preview flattening on the top image using PBR normal maps."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.flatten_service import preview

    try:
        result = preview(
            batch_path=str(batch_path),
            strength=request.strength,
            smoothing_radius=request.smoothing_radius,
            pbr_mode=request.pbr_mode,
        )
        return result
    except Exception as e:
        logger.error(f"Flatten preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flatten/apply")
async def flatten_apply(request: FlattenApplyRequest, background_tasks: BackgroundTasks):
    """Apply flattening to all images in batch using PBR normal maps."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.flatten_service import apply

    try:
        result = apply(
            batch_path=str(batch_path),
            strength=request.strength,
            smoothing_radius=request.smoothing_radius,
            pbr_mode=request.pbr_mode,
        )

        background_tasks.add_task(sync_batch, request.batch_name)
        return result
    except Exception as e:
        logger.error(f"Flatten apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Perspective Endpoints ───

@router.post("/perspective/detect-lines")
async def perspective_detect_lines(request: PerspectiveDetectRequest):
    """Detect lines in the top image for perspective correction."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.perspective_service import detect_lines

    try:
        top_image = _find_top_image_for_tool(batch_path, 'perspective')
        result = detect_lines(image_path=top_image)
        result["batch_name"] = request.batch_name
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Perspective detect-lines failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/perspective/preview")
async def perspective_preview(request: PerspectivePreviewRequest):
    """Preview perspective transform on top image."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.perspective_service import preview

    try:
        source_pts = [{"x": p.x, "y": p.y} for p in request.source_points]
        dest_pts = [{"x": p.x, "y": p.y} for p in request.dest_points] if request.dest_points else None
        result = preview(
            batch_path=batch_path,
            source_points=source_pts,
            dest_points=dest_pts,
        )
        return result
    except Exception as e:
        logger.error(f"Perspective preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/perspective/apply")
async def perspective_apply(request: PerspectiveApplyRequest, background_tasks: BackgroundTasks):
    """Apply perspective correction to all images in batch."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.perspective_service import apply

    try:
        source_pts = [{"x": p.x, "y": p.y} for p in request.source_points]
        dest_pts = [{"x": p.x, "y": p.y} for p in request.dest_points] if request.dest_points else None
        result = apply(
            batch_path=batch_path,
            source_points=source_pts,
            dest_points=dest_pts,
        )

        background_tasks.add_task(sync_batch, request.batch_name)
        return result
    except Exception as e:
        logger.error(f"Perspective apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Seamless Endpoints ───

@router.post("/seamless/analyze")
async def seamless_analyze(request: SeamlessAnalyzeRequest):
    """Analyze edge continuity for seamless tiling."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.seamless_service import analyze_seams

    try:
        top_image = _find_top_image_for_tool(batch_path, 'seamless')
        result = analyze_seams(
            image_path=top_image,
            blend_width=request.blend_width or 128,
        )
        result["batch_name"] = request.batch_name
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Seamless analyze failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/seamless/preview")
async def seamless_preview(request: SeamlessPreviewRequest):
    """Preview seamless tiling result."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.seamless_service import preview

    try:
        result = preview(
            batch_path=batch_path,
            method=request.method,
            blend_width=request.blend_width,
            spots_removal=request.spots_removal,
            color_equalizer=request.color_equalizer,
            tile_count=request.tile_count,
        )
        return result
    except Exception as e:
        logger.error(f"Seamless preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/seamless/apply")
async def seamless_apply(request: SeamlessApplyRequest, background_tasks: BackgroundTasks):
    """Apply seamless tiling to all images."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.seamless_service import apply

    try:
        result = apply(
            batch_path=batch_path,
            method=request.method,
            blend_width=request.blend_width,
            spots_removal=request.spots_removal,
            color_equalizer=request.color_equalizer,
        )

        background_tasks.add_task(sync_batch, request.batch_name)
        return result
    except Exception as e:
        logger.error(f"Seamless apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Tile Endpoints ───

@router.post("/tile/preview")
async def tile_preview(request: TilePreviewRequest):
    """Preview tiled output."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.tile_service import preview

    try:
        result = preview(
            batch_path=str(batch_path),
            tile_x=request.tile_x,
            tile_y=request.tile_y,
            offset_x=request.offset_x,
            offset_y=request.offset_y,
            scale=request.scale,
            rotation=request.rotation,
            overlap=request.overlap,
            half_drop=request.half_drop,
        )
        return result
    except Exception as e:
        logger.error(f"Tile preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tile/apply")
async def tile_apply(request: TileApplyRequest, background_tasks: BackgroundTasks):
    """Apply tiling to generate final output."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.tile_service import apply

    try:
        result = apply(
            batch_path=str(batch_path),
            tile_x=request.tile_x,
            tile_y=request.tile_y,
            offset_x=request.offset_x,
            offset_y=request.offset_y,
            scale=request.scale,
            rotation=request.rotation,
            overlap=request.overlap,
            half_drop=request.half_drop,
            output_resolution=tuple(request.output_resolution) if request.output_resolution else (2048, 2048),
        )

        background_tasks.add_task(sync_batch, request.batch_name)
        return result
    except Exception as e:
        logger.error(f"Tile apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Validate Endpoints ───

@router.post("/validate/check")
async def validate_check(request: ValidateCheckRequest):
    """Run PBR validation checks on batch maps."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.validate_service import validate_albedo, validate_metallic

    try:
        checks = []
        albedo_result = validate_albedo(
            batch_path=str(batch_path),
            dark_threshold=int(request.albedo_dark_threshold),
        )
        checks.append({"map": "albedo", **albedo_result})

        metal_range = tuple(request.metal_range) if request.metal_range else (180, 255)
        metallic_result = validate_metallic(
            batch_path=str(batch_path),
            metal_range=metal_range,
        )
        checks.append({"map": "metallic", **metallic_result})

        all_passed = all(c.get("passed", False) for c in checks if c.get("success", True))
        return {
            "success": True,
            "batch_name": request.batch_name,
            "checks": checks,
            "all_passed": all_passed,
        }
    except Exception as e:
        logger.error(f"Validate check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/validate/stats/{batch_name}")
async def validate_stats(batch_name: str):
    """Get PBR map statistics for a batch."""
    validate_batch(batch_name)
    batch_path = get_batch_path(batch_name)

    from scripts.processing.validate_service import get_stats

    try:
        result = get_stats(batch_path=str(batch_path))
        result["batch_name"] = batch_name
        return result
    except Exception as e:
        logger.error(f"Validate stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Clone / Inpaint Endpoints ───

@router.post("/clone/inpaint")
async def clone_inpaint(request: CloneInpaintRequest):
    """Inpaint masked region using surrounding pixels."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.clone_service import preview_inpaint

    try:
        result = preview_inpaint(
            batch_path=str(batch_path),
            mask_data_b64=request.mask_data,
            method=request.method,
            radius=request.radius,
        )
        return result
    except Exception as e:
        logger.error(f"Clone inpaint failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clone/stamp")
async def clone_stamp(request: CloneStampRequest):
    """Clone stamp from source to target position."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.clone_service import preview_stamp

    try:
        result = preview_stamp(
            batch_path=str(batch_path),
            source_pos={"x": request.source_pos.x, "y": request.source_pos.y},
            target_pos={"x": request.target_pos.x, "y": request.target_pos.y},
            radius=request.radius,
            fade=request.fade,
            blur_mask=request.blur_mask,
            mirror=request.mirror,
        )
        return result
    except Exception as e:
        logger.error(f"Clone stamp failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clone/apply")
async def clone_apply(request: CloneApplyRequest, background_tasks: BackgroundTasks):
    """Apply all clone/inpaint operations permanently."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.clone_service import apply

    try:
        result = apply(
            batch_path=str(batch_path),
            operations=request.operations,
        )

        background_tasks.add_task(sync_batch, request.batch_name)
        return result
    except Exception as e:
        logger.error(f"Clone apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Straighten Endpoints ───

@router.post("/straighten/analyze")
async def straighten_analyze(request: StraightenAnalyzeRequest):
    """Analyze yarn alignment — detect skew and bow."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.straighten_service import analyze

    try:
        top_image = _find_top_image_for_tool(batch_path, 'straighten')
        result = analyze(
            image_path=top_image,
            grid_divisions=request.grid_divisions,
            direction=request.direction,
        )
        result["batch_name"] = request.batch_name
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Straighten analyze failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/straighten/preview")
async def straighten_preview(request: StraightenPreviewRequest):
    """Preview straighten correction on top image."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.straighten_service import preview

    try:
        result = preview(
            batch_path=batch_path,
            mode=request.mode,
            strength=request.strength,
            direction=request.direction,
            grid_divisions=request.grid_divisions,
            manual_skew_angle=request.manual_skew_angle,
        )
        return result
    except Exception as e:
        logger.error(f"Straighten preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/straighten/apply")
async def straighten_apply(request: StraightenApplyRequest, background_tasks: BackgroundTasks):
    """Apply straighten correction to all images in batch."""
    validate_batch(request.batch_name)
    batch_path = get_batch_path(request.batch_name)

    from scripts.processing.straighten_service import apply

    try:
        result = apply(
            batch_path=batch_path,
            mode=request.mode,
            strength=request.strength,
            direction=request.direction,
            grid_divisions=request.grid_divisions,
            manual_skew_angle=request.manual_skew_angle,
        )

        background_tasks.add_task(sync_batch, request.batch_name)
        return result
    except Exception as e:
        logger.error(f"Straighten apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
