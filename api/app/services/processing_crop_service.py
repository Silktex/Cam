"""
Crop orchestration service — thin orchestration layer between the processing
router and scripts.processing.crop_service (subprocess/Path work lives there).

Extracted behavior-identically from app/routers/processing.py: response
shapes, error mapping (including the historical 404-swallowed-to-500 paths)
and log messages are unchanged. Heavy scripts.processing imports stay lazy
(per-call) exactly as the router performed them.
"""
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)


def get_top_image(batch_path: Path) -> dict:
    """Top image info for the crop interface.

    Historical quirk preserved: the inner 404 for an empty batch is raised
    inside the guarded block and therefore surfaces as 500 (str(exc) detail).
    """
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


def auto_detect(batch_path: Path, crop_size: int) -> dict:
    """Auto-detect crop boundary on the TOP image (no side effects).

    Exceptions propagate raw; callers own the HTTP error mapping.
    """
    from scripts.processing.crop_service import CropService

    crop_service = CropService(use_gpu=settings.USE_GPU)
    return crop_service.auto_detect_crop(str(batch_path), crop_size=crop_size)


def auto_detect_endpoint(batch_path: Path, crop_size: int) -> dict:
    """/crop/auto-detect flow: raw detection mapped to 500 on failure."""
    try:
        return auto_detect(batch_path, crop_size)
    except Exception as e:
        logger.error(f"Auto-detect crop failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def preview_manual(batch_path: Path, bbox: List[int]) -> dict:
    """Preview manual crop on the TOP image without saving.

    Historical quirk preserved: failures surface as 500 (str(exc) detail).
    """
    from scripts.processing.crop_service import CropService

    try:
        crop_service = CropService()
        return crop_service.preview_manual_crop(str(batch_path), bbox)

    except Exception as e:
        logger.error(f"Preview manual crop failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def apply_crop(
    batch_name: str,
    batch_path: Path,
    bbox: Optional[List[int]],
    crop_type: str,
    points,
    rotation: float,
) -> dict:
    """Apply confirmed crop to ALL images; returns the /crop/apply response.

    Exceptions propagate raw; the router owns status bookkeeping and the
    HTTP error mapping around this call.
    """
    from scripts.processing.crop_service import CropService

    crop_service = CropService()

    # Convert points to dict format if provided
    points_dict = None
    if points and len(points) == 4:
        points_dict = [{'x': p.x, 'y': p.y} for p in points]

    results = crop_service.apply_crop_to_all(
        batch_path=str(batch_path),
        bbox=bbox,
        crop_type=crop_type,
        points=points_dict,
        rotation=rotation,
    )

    success_count = sum(1 for r in results if r.success)
    total_count = len(results)

    return {
        "success": success_count > 0,
        "batch_name": batch_name,
        "crop_type": crop_type,
        "rotation": rotation,
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
        ],
    }


def apply_auto_crop(batch_name: str, batch_path: Path, detect_result: dict) -> dict:
    """Legacy /crop/auto response: apply an accepted auto-detection to all.

    Keeps per-result bbox (and the detected bbox) in the response, unlike
    /crop/apply. Raises raw exceptions; the router owns status bookkeeping
    and HTTP error mapping.
    """
    from scripts.processing.crop_service import CropService

    crop_service = CropService(use_gpu=settings.USE_GPU)

    results = crop_service.apply_crop_to_all(
        batch_path=str(batch_path),
        bbox=detect_result["bbox"],
        crop_type="auto",
    )

    success_count = sum(1 for r in results if r.success)
    total_count = len(results)

    return {
        "success": success_count > 0,
        "batch_name": batch_name,
        "processed": success_count,
        "total": total_count,
        "bbox": detect_result["bbox"],
        "results": [
            {
                "source": r.source_path,
                "output": r.output_path,
                "success": r.success,
                "error": r.error,
                "bbox": r.bbox,
            }
            for r in results
        ],
    }


def reconvert_tiff_flow(request) -> dict:
    """/reconvert-tiff endpoint flow (path validation + orchestration)."""
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

    return {"path": request.path, **reconvert_tiff(batch_path, request.checker_raw_path)}


def apply_crop_flow(request, batch_path: Path, background_tasks, update_status, sync) -> dict:
    """/crop/apply flow; update_status/sync injected so router-level
    patching stays authoritative (behavior-identical to inline router body)."""
    try:
        update_status(request.batch_name, 'crop', 'in_progress', crop_type=request.crop_type)
        result = apply_crop(request.batch_name, batch_path, request.bbox,
                            request.crop_type, request.points, request.rotation)
        update_status(request.batch_name, 'crop',
                      'completed' if result["success"] else 'pending',
                      crop_type=request.crop_type)
        background_tasks.add_task(sync, request.batch_name)
        return result
    except Exception as e:
        logger.error(f"Apply crop failed: {e}")
        update_status(request.batch_name, 'crop', 'pending')
        raise HTTPException(status_code=500, detail=str(e))


def auto_crop_flow(request, batch_path: Path, background_tasks, update_status, sync) -> dict:
    """Legacy /crop/auto flow: detect then apply (injected status deps)."""
    try:
        detect_result = auto_detect(batch_path, request.crop_size)

        if not detect_result.get("success"):
            return {
                "success": False,
                "batch_name": request.batch_name,
                "processed": 0,
                "total": 0,
                "error": detect_result.get("error", "Auto-detect failed"),
                "results": []
            }

        update_status(request.batch_name, 'crop', 'in_progress', crop_type='auto')
        result = apply_auto_crop(request.batch_name, batch_path, detect_result)
        update_status(request.batch_name, 'crop',
                      'completed' if result["success"] else 'pending',
                      crop_type='auto')
        background_tasks.add_task(sync, request.batch_name)
        return result
    except Exception as e:
        logger.error(f"Auto crop failed: {e}")
        update_status(request.batch_name, 'crop', 'pending')
        raise HTTPException(status_code=500, detail=str(e))


def reconvert_tiff(batch_path: Path, checker_raw_path: Optional[str]) -> dict:
    """Re-convert all RAW files under batch_path/raw to TIFF in batch_path/tiff.

    Optionally uses a checker RAW's white balance for all conversions.
    Returns {"fixed_wb", "success", "failed", "total", "files"}; the router
    merges in the echoed request path.
    """
    from scripts.processing.raw_utils import (
        is_raw_file, extract_wb, load_raw, load_raw_with_fixed_wb, save_tiff
    )

    raw_dir = batch_path / "raw"
    tiff_dir = batch_path / "tiff"
    tiff_dir.mkdir(exist_ok=True)

    # Extract fixed WB if checker RAW path provided
    fixed_wb = None
    if checker_raw_path:
        checker_path = Path(checker_raw_path)
        if not checker_path.exists():
            raise HTTPException(status_code=404, detail=f"Checker RAW not found: {checker_raw_path}")
        fixed_wb = extract_wb(checker_path)
        if not fixed_wb:
            raise HTTPException(status_code=500, detail=f"Could not extract WB from {checker_raw_path}")
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

    return {"fixed_wb": fixed_wb, **results}
